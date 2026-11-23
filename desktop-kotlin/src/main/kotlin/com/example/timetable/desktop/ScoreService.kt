package com.example.timetable.desktop

import java.time.LocalDateTime
import java.time.temporal.WeekFields

/** 积分数据层，直接读写 student_data.txt / group_data.txt，字段与原版一致。 */
object ScoreService {
    private const val TIME_PATTERN = "yyyy-MM-dd HH:mm:ss"

    fun students(): MutableMap<String, Any?> = DataStore.loadMap("student_data.txt")

    fun groups(): MutableMap<String, Any?> = DataStore.loadMap("group_data.txt")

    fun classStudents(cls: String): MutableMap<String, Any?> = students()[cls].asMutableMap()

    fun classGroups(cls: String): MutableMap<String, Any?> = groups()[cls].asMutableMap()

    fun recordDelta(rec: Map<*, *>): Int {
        val score = kotlin.math.abs(rec.num("score"))
        return if (rec.str("operate") == "扣分") -score else score
    }

    fun studentTotal(info: Map<*, *>): Int = info.asList("records").sumOf { rec ->
        (rec as? Map<*, *>)?.let { recordDelta(it) } ?: 0
    }

    private fun Map<*, *>.asList(key: String): List<Any?> = this[key].asList()

    fun groupOwnRecords(group: Map<*, *>): List<Map<*, *>> =
        group["group_records"].asList().mapNotNull { it as? Map<*, *> }

    fun groupOwnTotal(group: Map<*, *>): Int = groupOwnRecords(group).sumOf { recordDelta(it) }

    fun groupLegacyTotal(group: Map<*, *>): Int =
        group["record"].asList().mapNotNull { it as? Map<*, *> }.sumOf { recordDelta(it) }

    fun groupTotal(group: Map<*, *>, stu: Map<*, *>): Int {
        var total = groupLegacyTotal(group) + groupOwnTotal(group)
        group["members"].asList().forEach { sid ->
            val info = stu[sid?.toString()].asMap()
            if (info.isNotEmpty()) total += studentTotal(info)
        }
        return total
    }

    fun groupOf(groups: Map<*, *>, stu: Map<*, *>): Map<String, String> {
        val result = linkedMapOf<String, String>()
        groups.forEach { (gname, value) ->
            value.asMap()["members"].asList().forEach { sid ->
                val key = sid?.toString() ?: return@forEach
                if (stu.containsKey(key) && !result.containsKey(key)) result[key] = gname.toString()
            }
        }
        return result
    }

    fun addPoint(cls: String, sids: List<String>, reason: String, delta: Int): Int {
        if (sids.isEmpty() || delta == 0) return 0
        val allStudents = students()
        val allGroups = groups()
        val stu = allStudents[cls].asMutableMap()
        val now = LocalDateTime.now()
        val stamp = now.format(java.time.format.DateTimeFormatter.ofPattern(TIME_PATTERN))
        val week = "%04d-W%02d".format(
            now.get(WeekFields.ISO.weekBasedYear()),
            now.get(WeekFields.ISO.weekOfWeekBasedYear()),
        )
        val mode = if (delta > 0) "加分" else "扣分"
        var count = 0
        sids.forEach { sid ->
            val info = stu[sid].asMutableMap()
            if (info.isEmpty()) return@forEach
            val records = info.getOrPut("records") { mutableListOf<Any?>() }.asMutableList()
            records.add(linkedMapOf<String, Any?>(
                "operate" to mode,
                "score" to kotlin.math.abs(delta),
                "reason" to reason,
                "time" to stamp,
                "week" to week,
            ))
            info["records"] = records
            info["total_score"] = studentTotal(info)
            stu[sid] = info
            count++
        }
        if (count == 0) return 0
        allStudents[cls] = stu
        syncGroupTotals(allStudents, allGroups)
        DataStore.save("student_data.txt", allStudents)
        DataStore.save("group_data.txt", allGroups)
        return count
    }

    fun addGroupPoint(cls: String, groupNames: List<String>, reason: String, delta: Int): Int {
        if (groupNames.isEmpty() || delta == 0) return 0
        val allStudents = students()
        val allGroups = groups()
        val classGroups = allGroups[cls].asMutableMap()
        val stu = allStudents[cls].asMap()
        val now = LocalDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern(TIME_PATTERN))
        val week = "%04d-W%02d".format(
            LocalDateTime.now().get(WeekFields.ISO.weekBasedYear()),
            LocalDateTime.now().get(WeekFields.ISO.weekOfWeekBasedYear()),
        )
        var count = 0
        groupNames.forEach { name ->
            val group = classGroups[name].asMutableMap()
            if (group.isEmpty()) return@forEach
            val records = group.getOrPut("group_records") { mutableListOf<Any?>() }.asMutableList()
            records.add(linkedMapOf<String, Any?>(
                "operate" to if (delta > 0) "加分" else "扣分",
                "score" to kotlin.math.abs(delta),
                "reason" to reason,
                "time" to now,
                "week" to week,
            ))
            group["group_records"] = records
            group["total_score"] = groupTotal(group, stu)
            classGroups[name] = group
            count++
        }
        if (count == 0) return 0
        allGroups[cls] = classGroups
        syncGroupTotals(allStudents, allGroups)
        DataStore.save("student_data.txt", allStudents)
        DataStore.save("group_data.txt", allGroups)
        return count
    }

    fun revokeStudentRecord(cls: String, sid: String, index: Int): Boolean {
        val all = students()
        val stu = all[cls].asMutableMap()
        val info = stu[sid].asMutableMap()
        val records = info["records"].asMutableList()
        if (index !in records.indices) return false
        records.removeAt(index)
        info["records"] = records
        info["total_score"] = studentTotal(info)
        stu[sid] = info
        all[cls] = stu
        val allGroups = groups()
        syncGroupTotals(all, allGroups)
        DataStore.save("student_data.txt", all)
        DataStore.save("group_data.txt", allGroups)
        return true
    }

    fun syncGroupTotals(allStudents: Map<String, Any?>, allGroups: MutableMap<String, Any?>) {
        allGroups.forEach { (cls, value) ->
            val stu = allStudents[cls].asMap()
            value.asMap().forEach { (_, g) ->
                val group = g.asMutableMap()
                if (group.isEmpty()) return@forEach
                group["total_score"] = groupTotal(group, stu)
            }
        }
    }

    fun groupRows(cls: String): List<GroupRow> {
        val stu = classStudents(cls)
        return classGroups(cls).map { (name, value) ->
            val group = value.asMap()
            val members = group["members"].asList().mapNotNull { it?.toString() }.filter { stu.containsKey(it) }
            GroupRow(
                name = name,
                count = members.size,
                total = groupTotal(group, stu),
                own = groupOwnTotal(group),
                legacy = groupLegacyTotal(group),
            )
        }.sortedByDescending { it.total }
    }

    fun studentRows(cls: String): List<StudentRow> {
        val stu = classStudents(cls)
        val groupOf = groupOf(classGroups(cls), stu)
        val leaders = classGroups(cls).values.mapNotNull { it.asMap()["leader"]?.toString() }.toSet()
        return stu.map { (sid, info) ->
            StudentRow(
                sid = sid,
                name = info.asMap().str("name"),
                group = groupOf[sid] ?: "未分组",
                total = studentTotal(info.asMap()),
                isLeader = sid in leaders,
            )
        }.sortedWith(compareBy<StudentRow> { it.group }.thenBy { sidKey(it.sid) })
    }

    private fun sidKey(sid: String): String =
        sid.toIntOrNull()?.let { "0${it.toString().padStart(6, '0')}" } ?: "1$sid"

    fun pointRows(cls: String): List<PointRow> {
        val stu = classStudents(cls)
        val groupOf = groupOf(classGroups(cls), stu)
        val result = mutableListOf<PointRow>()
        stu.forEach { (sid, info) ->
            info.asMap()["records"].asList().forEachIndexed { index, raw ->
                val rec = raw.asMap()
                result.add(PointRow(
                    group = groupOf[sid] ?: "未分组",
                    sid = sid,
                    name = info.asMap().str("name"),
                    time = rec.str("time"),
                    reason = rec.str("reason"),
                    delta = recordDelta(rec),
                    recordIndex = index,
                ))
            }
        }
        return result.sortedByDescending { it.time }
    }

    fun addStudent(cls: String, sid: String, name: String): String? {
        if (sid.isBlank() || name.isBlank()) return "学号与姓名不能为空"
        val all = students()
        val stu = all[cls].asMutableMap()
        if (stu.containsKey(sid)) return "学号已存在"
        stu[sid] = linkedMapOf<String, Any?>(
            "stu_id" to sid,
            "name" to name,
            "records" to mutableListOf<Any?>(),
            "total_score" to 0,
        )
        all[cls] = stu
        DataStore.save("student_data.txt", all)
        return null
    }

    fun removeStudent(cls: String, sid: String) {
        val all = students()
        val stu = all[cls].asMutableMap()
        stu.remove(sid)
        all[cls] = stu
        val allGroups = groups()
        val classGroups = allGroups[cls].asMutableMap()
        classGroups.values.forEach { g ->
            val group = g.asMutableMap()
            val members = group["members"].asMutableList()
            members.removeAll { it?.toString() == sid }
            group["members"] = members
            if (group.str("leader") == sid) group["leader"] = members.firstOrNull()?.toString() ?: ""
        }
        allGroups[cls] = classGroups
        syncGroupTotals(all, allGroups)
        DataStore.save("student_data.txt", all)
        DataStore.save("group_data.txt", allGroups)
    }

    fun addGroup(cls: String, name: String): String? {
        if (name.isBlank()) return "小组名不能为空"
        val all = groups()
        val classGroups = all[cls].asMutableMap()
        if (classGroups.containsKey(name)) return "小组已存在"
        classGroups[name] = linkedMapOf<String, Any?>(
            "leader" to "",
            "members" to mutableListOf<Any?>(),
            "total_score" to 0,
            "record" to mutableListOf<Any?>(),
        )
        all[cls] = classGroups
        DataStore.save("group_data.txt", all)
        return null
    }

    fun deleteGroup(cls: String, name: String) {
        val all = groups()
        val classGroups = all[cls].asMutableMap()
        classGroups.remove(name)
        all[cls] = classGroups
        DataStore.save("group_data.txt", all)
    }

    fun setGroupMembers(cls: String, name: String, members: List<String>, leader: String) {
        val all = groups()
        val classGroups = all[cls].asMutableMap()
        val group = classGroups[name].asMutableMap()
        group["members"] = members.toMutableList<Any?>()
        group["leader"] = leader
        classGroups[name] = group
        all[cls] = classGroups
        val allStudents = students()
        syncGroupTotals(allStudents, all)
        DataStore.save("group_data.txt", all)
        DataStore.save("student_data.txt", allStudents)
    }
}
