package com.example.timetable

import org.json.JSONArray
import org.json.JSONObject

/**
 * 全局数据仓库：内容全部来自电脑端的 /api/snapshot。
 * 电脑端没连上时只保留固定作息骨架，课表、积分、卫生都为空。
 */
object AppData {

    var className = "七年级10班"
    var stateLine = "等待电脑端数据…"
    var currentDayIndex = -1
    var currentPeriodId = -1
    var currentName = ""
    var isInClass = false

    var periods: List<Period> = listOf(
        Period(1, "第1节", "08:00", "08:45"),
        Period(2, "第2节", "09:00", "09:45"),
        Period(3, "第3节", "10:15", "11:00"),
        Period(4, "第4节", "11:10", "11:50"),
        Period(5, "第5节", "13:45", "14:30"),
        Period(6, "第6节", "14:45", "15:30"),
        Period(7, "第7节", "15:45", "16:30"),
    )

    var extraSlots: List<Period> = listOf(
        Period(99, "午间小练", "12:25", "12:50"),
        Period(100, "晚辅", "17:10", "18:10"),
    )

    var schedule: List<CourseCell> = emptyList()

    val weekDayNames = listOf("周一", "周二", "周三", "周四", "周五")

    var groupScores: List<GroupScore> = emptyList()

    var students: List<StudentRow> = emptyList()

    var hygieneRecords: List<HygieneRecord> = emptyList()
    var hygieneTotalRecords = 0
    var hygieneTotalDeduct = 0
    var hygieneByGroup: List<Pair<String, Int>> = emptyList()
    var hygieneByReason: List<Pair<String, Int>> = emptyList()

    fun buildSchedule(): List<CourseCell> = schedule

    /** 把电脑端 /api/snapshot 返回的 JSON 写入界面数据。 */
    fun applySnapshot(root: JSONObject) {
        root.optString("class_name").takeIf { it.isNotBlank() }?.let { className = it }

        root.optJSONObject("state")?.let { st ->
            currentDayIndex = st.optInt("day", -1)
            val period = st.opt("current_period")
            currentPeriodId = if (period is Number) period.toInt() else -1
            currentName = st.optString("current_name")
            isInClass = st.optString("state") == "in_class"
            val next = st.optString("next_subject")
            stateLine = when (st.optString("state")) {
                "in_class" -> "正在上课 · ${st.optString("current_name")} ${st.optString("current_subject")}"
                "before_class" -> "上课前 · 下一节 $next"
                "between_class" -> "课间 · 下一节 $next"
                "after_school" -> "已放学"
                "weekend" -> "周末"
                "disabled" -> "暂停提醒 · ${st.optString("disabled_note")}"
                else -> stateLine
            }
        }

        root.optJSONArray("periods")?.let { arr ->
            val list = ArrayList<Period>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                list.add(Period(o.optInt("id"), o.optString("name"),
                    o.optString("start"), o.optString("end")))
            }
            if (list.isNotEmpty()) periods = list
        }
        root.optJSONArray("extra_slots")?.let { arr ->
            val list = ArrayList<Period>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                list.add(Period(o.optInt("id"), o.optString("name"),
                    o.optString("start"), o.optString("end")))
            }
            if (list.isNotEmpty()) extraSlots = list
        }

        val cells = ArrayList<CourseCell>()
        listOf("schedule", "extra_schedule").forEach { key ->
            root.optJSONArray(key)?.let { arr ->
                for (i in 0 until arr.length()) {
                    val o = arr.optJSONObject(i) ?: continue
                    cells.add(CourseCell(
                        o.optInt("day_index"), o.optInt("period_id"),
                        o.optString("subject"), o.optString("classroom")))
                }
            }
        }
        schedule = cells

        root.optJSONArray("students")?.let { arr ->
            val list = ArrayList<StudentRow>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                list.add(StudentRow(o.optString("sid"), o.optString("name"),
                    o.optString("group"), o.optInt("total")))
            }
            students = list
        }

        root.optJSONArray("groups")?.let { arr ->
            val list = ArrayList<GroupScore>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val recs = ArrayList<ScoreRecord>()
                o.optJSONArray("records")?.let { rs ->
                    for (j in 0 until rs.length()) {
                        val r = rs.optJSONObject(j) ?: continue
                        recs.add(ScoreRecord(r.optString("time"),
                            r.optString("reason"), r.optInt("delta"),
                            r.optString("member")))
                    }
                }
                list.add(GroupScore(o.optString("name"), o.optString("leader"),
                    o.optInt("total"), recs))
            }
            groupScores = list.sortedByDescending { it.total }
        }

        root.optJSONObject("hygiene")?.let { hy ->
            hygieneTotalRecords = hy.optInt("total_records", 0)
            hygieneTotalDeduct = hy.optInt("total_deduct", 0)
            hygieneByGroup = parsePairs(hy.optJSONArray("by_group"))
            hygieneByReason = parsePairs(hy.optJSONArray("by_reason"))
            val recs = ArrayList<HygieneRecord>()
            hy.optJSONArray("records")?.let { arr ->
                for (i in 0 until arr.length()) {
                    val o = arr.optJSONObject(i) ?: continue
                    recs.add(HygieneRecord(o.optString("group"), o.optString("member"),
                        o.optString("reason"), o.optInt("score"), o.optString("time"),
                        o.optString("date"), o.optString("by")))
                }
            }
            hygieneRecords = recs
        }
    }

    /** [["第一组",5], ...] → List<Pair<String,Int>> */
    private fun parsePairs(arr: JSONArray?): List<Pair<String, Int>> {
        if (arr == null) return emptyList()
        val list = ArrayList<Pair<String, Int>>()
        for (i in 0 until arr.length()) {
            val pair = arr.optJSONArray(i) ?: continue
            list.add(pair.optString(0) to pair.optInt(1))
        }
        return list
    }

    fun hygieneTotalsByGroup(): List<Pair<String, Int>> {
        if (hygieneByGroup.isNotEmpty()) return hygieneByGroup
        val map = linkedMapOf<String, Int>()
        hygieneRecords.forEach { r -> map[r.group] = (map[r.group] ?: 0) + r.score }
        return map.entries.sortedByDescending { it.value }.map { it.key to it.value }
    }

    fun hygieneCountsByReason(): List<Pair<String, Int>> {
        if (hygieneByReason.isNotEmpty()) return hygieneByReason
        val map = linkedMapOf<String, Int>()
        hygieneRecords.forEach { r -> map[r.reason] = (map[r.reason] ?: 0) + 1 }
        return map.entries.sortedByDescending { it.value }.map { it.key to it.value }
    }

    /** 积分理由分布（次数），最多 8 项，避免饼图过长。 */
    fun scoreCountsByReason(): List<Pair<String, Int>> {
        val map = linkedMapOf<String, Int>()
        groupScores.forEach { g ->
            g.records.forEach { r -> map[r.reason] = (map[r.reason] ?: 0) + 1 }
        }
        return map.entries.sortedByDescending { it.value }.take(8).map { it.key to it.value }
    }
}
