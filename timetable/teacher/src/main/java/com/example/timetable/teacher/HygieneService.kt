package com.example.timetable.teacher

import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** 卫生扣分数据层：记录仍按人保存，字段与 Python 版一致。 */
object HygieneService {
    private val defaultReasons = listOf(
        "地面有纸屑", "桌椅摆放不齐", "垃圾桶未倒", "讲台杂乱",
        "卫生角不整洁", "黑板未擦", "窗台有灰", "包干区未打扫",
    )

    fun data(): MutableMap<String, Any?> = DataStore.loadMap("hygiene_data.txt")

    fun block(cls: String): MutableMap<String, Any?> = data()[cls].asMutableMap()

    fun reasons(cls: String): List<String> {
        val block = block(cls)
        val seen = linkedSetOf<String>()
        val history = block["reasons"].asList().map { it.toString() } +
            block["records"].asList().mapNotNull { it.asMap()["reason"]?.toString() }.asReversed()
        (history + defaultReasons).forEach { reason ->
            val trimmed = reason.trim()
            if (trimmed.isNotEmpty()) seen.add(trimmed)
        }
        return seen.toList()
    }

    fun addRecord(cls: String, sids: List<String>, reason: String, score: Int, note: String, by: String): Int {
        if (sids.isEmpty() || score <= 0) return 0
        val all = data()
        val block = all[cls].asMutableMap()
        val records = block.getOrPut("records") { mutableListOf<Any?>() }.asMutableList()
        val stu = ScoreService.classStudents(cls)
        val groupOf = ScoreService.groupOf(ScoreService.classGroups(cls), stu)
        val now = LocalDateTime.now()
        val stamp = now.format(DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSSSSS"))
        var count = 0
        sids.forEach { sid ->
            val info = stu[sid].asMap()
            if (info.isEmpty()) return@forEach
            records.add(linkedMapOf<String, Any?>(
                "id" to "$stamp-$sid",
                "sid" to sid,
                "name" to info.str("name"),
                "group" to (groupOf[sid] ?: "未分组"),
                "reason" to reason,
                "score" to score,
                "note" to note,
                "time" to now.format(DATE_TIME),
                "date" to now.toLocalDate().toString(),
                "by" to by,
                "by_sid" to "",
            ))
            count++
        }
        if (count == 0) return 0
        if (reason.isNotBlank()) {
            val reasonList = block.getOrPut("reasons") { mutableListOf<Any?>() }.asMutableList()
            if (!reasonList.contains(reason)) reasonList.add(reason)
            block["reasons"] = reasonList
        }
        block["records"] = records
        all[cls] = block
        DataStore.save("hygiene_data.txt", all)
        return count
    }

    fun revoke(cls: String, index: Int): Boolean {
        val all = data()
        val block = all[cls].asMutableMap()
        val records = block["records"].asMutableList()
        if (index !in records.indices) return false
        records.removeAt(index)
        block["records"] = records
        all[cls] = block
        DataStore.save("hygiene_data.txt", all)
        return true
    }

    fun records(cls: String): List<HygieneRow> =
        block(cls)["records"].asList().mapIndexed { index, raw ->
            val rec = raw.asMap()
            HygieneRow(
                id = rec.str("id"),
                sid = rec.str("sid"),
                name = rec.str("name"),
                group = rec.str("group").ifBlank { "未分组" },
                reason = rec.str("reason"),
                score = rec.num("score"),
                note = rec.str("note"),
                time = rec.str("time"),
                date = rec.str("date"),
                by = rec.str("by"),
                recordIndex = index,
            )
        }.sortedByDescending { it.time }

    fun groupRows(cls: String): List<Pair<String, Int>> {
        val totals = linkedMapOf<String, Int>()
        ScoreService.classGroups(cls).keys.forEach { totals[it] = 0 }
        records(cls).forEach { row ->
            totals[row.group] = (totals[row.group] ?: 0) + row.score
        }
        return totals.entries.sortedByDescending { it.value }.map { it.key to it.value }
    }

    fun reasonRows(cls: String): List<Pair<String, Int>> {
        val counts = linkedMapOf<String, Int>()
        records(cls).forEach { row ->
            val reason = row.reason.ifBlank { "未填写" }
            counts[reason] = (counts[reason] ?: 0) + 1
        }
        return counts.entries.sortedByDescending { it.value }.map { it.key to it.value }
    }
}
