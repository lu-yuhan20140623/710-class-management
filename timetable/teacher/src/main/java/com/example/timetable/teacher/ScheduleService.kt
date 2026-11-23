package com.example.timetable.teacher

import java.time.LocalDateTime
import java.time.LocalTime

/** 课表、调课、禁用时间段与当前课节状态。作息沿用 Python 版。 */
object ScheduleService {
    val periods = listOf(
        Period(1, "第1节", LocalTime.of(8, 0), LocalTime.of(8, 45)),
        Period(2, "第2节", LocalTime.of(9, 0), LocalTime.of(9, 45)),
        Period(3, "第3节", LocalTime.of(10, 15), LocalTime.of(11, 0)),
        Period(4, "第4节", LocalTime.of(11, 10), LocalTime.of(11, 50)),
        Period(5, "第5节", LocalTime.of(13, 45), LocalTime.of(14, 30)),
        Period(6, "第6节", LocalTime.of(14, 45), LocalTime.of(15, 30)),
        Period(7, "第7节", LocalTime.of(15, 45), LocalTime.of(16, 30)),
    )

    val practice = Period(99, "午间小练", LocalTime.of(12, 25), LocalTime.of(12, 50))
    val evening = Period(100, "晚辅", LocalTime.of(17, 10), LocalTime.of(18, 10))
    val extraSlots = listOf(practice, evening)

    val practiceSubjects = mapOf(0 to "数学", 1 to "数学", 2 to "英语", 3 to "语文", 4 to "数学")

    val defaultSchedule: Map<Int, Map<Int, String>> = mapOf(
        0 to mapOf(1 to "语文", 2 to "数学", 3 to "生物", 4 to "英语", 5 to "体育", 6 to "道法", 7 to "地理"),
        1 to mapOf(1 to "历史", 2 to "语文", 3 to "英语", 4 to "信息", 5 to "英语/心理", 6 to "数学", 7 to "班会"),
        2 to mapOf(1 to "数学", 2 to "英语", 3 to "音乐", 4 to "生物", 5 to "体育", 6 to "语文", 7 to "选修课"),
        3 to mapOf(1 to "英语", 2 to "语文", 3 to "数学", 4 to "地理", 5 to "历史", 6 to "语文", 7 to "劳动"),
        4 to mapOf(1 to "语文", 2 to "英语", 3 to "体育", 4 to "道法", 5 to "数学", 6 to "数学", 7 to "美术"),
    )

    val weekdayNames = listOf("星期一", "星期二", "星期三", "星期四", "星期五")
    private const val REMIND_AHEAD = 4L
    private const val PREBELL_AHEAD = 2L

    fun overrides(): MutableMap<String, Any?> = DataStore.loadMap("overrides.json")

    fun subject(day: Int, period: Int): String =
        defaultSchedule[day]?.get(period)?.let { default ->
            overrides()["$day-$period"]?.toString()?.takeIf { it.isNotBlank() } ?: default
        } ?: ""

    fun setOverride(day: Int, period: Int, subject: String) {
        val data = overrides()
        val key = "$day-$period"
        if (subject.isBlank()) data.remove(key) else data[key] = subject
        DataStore.save("overrides.json", data)
    }

    fun clearOverrides() = DataStore.save("overrides.json", linkedMapOf<String, Any?>())

    fun disabledRanges(): MutableList<MutableMap<String, Any?>> {
        val result = mutableListOf<MutableMap<String, Any?>>()
        DataStore.loadList("disabled_ranges.json").forEach { item ->
            val map = item.asMap()
            val start = runCatching { LocalDateTime.parse(map.str("start"), MINUTE_FORMAT) }.getOrNull()
            val end = runCatching { LocalDateTime.parse(map.str("end"), MINUTE_FORMAT) }.getOrNull()
            if (start != null && end != null && end.isAfter(start)) {
                result.add(linkedMapOf("start" to start, "end" to end, "note" to map.str("note")))
            }
        }
        return result.sortedBy { (it["start"] as LocalDateTime) }.toMutableList()
    }

    fun addDisabled(start: LocalDateTime, end: LocalDateTime, note: String): Boolean {
        if (!end.isAfter(start)) return false
        val merged = disabledRanges()
        merged.add(linkedMapOf("start" to start, "end" to end, "note" to note))
        merged.sortBy { it["start"] as LocalDateTime }
        val result = mutableListOf<MutableMap<String, Any?>>()
        for (range in merged) {
            val last = result.lastOrNull()
            if (last == null) {
                result.add(range)
                continue
            }
            val lastEnd = last["end"] as LocalDateTime
            if ((range["start"] as LocalDateTime) <= lastEnd) {
                if (lastEnd < (range["end"] as LocalDateTime)) last["end"] = range["end"]
                val nextNote = range.str("note")
                if (nextNote.isNotBlank() && nextNote != last.str("note")) last["note"] = nextNote
            } else {
                result.add(range)
            }
        }
        saveDisabled(result)
        return true
    }

    fun removeDisabled(index: Int): Boolean {
        val ranges = disabledRanges()
        if (index !in ranges.indices) return false
        ranges.removeAt(index)
        saveDisabled(ranges)
        return true
    }

    private fun saveDisabled(ranges: List<Map<String, Any?>>) {
        val saved = ranges.map { range ->
            linkedMapOf<String, Any?>(
                "start" to (range["start"] as LocalDateTime).format(MINUTE_FORMAT),
                "end" to (range["end"] as LocalDateTime).format(MINUTE_FORMAT),
                "note" to range.str("note"),
            )
        }
        DataStore.save("disabled_ranges.json", saved)
    }

    fun disabledNow(now: LocalDateTime = LocalDateTime.now()): Pair<Boolean, String> {
        for (range in disabledRanges()) {
            if ((range["start"] as LocalDateTime) <= now && now <= (range["end"] as LocalDateTime)) {
                return true to range.str("note").ifBlank { "禁用中" }
            }
        }
        return false to ""
    }

    fun slots(day: Int): List<Slot> {
        val list = mutableListOf<Slot>()
        periods.forEach { p ->
            list.add(Slot(p.id, p.name, subject(day, p.id), p.start, p.end, "period"))
        }
        list.add(Slot(practice.id, practice.name, practiceSubjects[day] ?: "小练", practice.start, practice.end, "practice"))
        list.add(Slot(evening.id, evening.name, evening.name, evening.start, evening.end, "evening"))
        return list.sortedBy { it.start }
    }

    fun state(now: LocalDateTime = LocalDateTime.now()): MutableMap<String, Any?> {
        val day = now.dayOfWeek.value - 1
        val weekday = if (day <= 4) day else -1
        val (disabled, disabledNote) = disabledNow(now)
        val result = linkedMapOf<String, Any?>(
            "state" to if (weekday < 0) "weekend" else "after_school",
            "current_period" to null,
            "current_name" to "",
            "current_subject" to "",
            "current_start" to null,
            "current_end" to null,
            "next_period" to null,
            "next_name" to "",
            "day" to weekday,
            "seconds_to_next" to 0,
            "next_subject" to "",
            "next_start" to null,
            "next_end" to null,
            "is_counting" to false,
            "is_prebell" to false,
            "seconds_to_prebell" to 0,
            "disabled" to disabled,
            "disabled_note" to disabledNote,
            "school_end" to evening.end.format(HH_MM),
        )
        if (disabled || weekday < 0) {
            if (disabled) result["state"] = "disabled"
            return result
        }

        val today = now.toLocalDate()
        val blocks = slots(weekday)
        for ((index, slot) in blocks.withIndex()) {
            val start = LocalDateTime.of(today, slot.start)
            val end = LocalDateTime.of(today, slot.end)
            when {
                now >= start && now < end -> {
                    result["state"] = "in_class"
                    result["current_period"] = slot.key
                    result["current_name"] = slot.name
                    result["current_subject"] = slot.subject
                    result["current_start"] = slot.start.format(HH_MM)
                    result["current_end"] = slot.end.format(HH_MM)
                    if (index + 1 < blocks.size) {
                        val next = blocks[index + 1]
                        result["next_period"] = next.key
                        result["next_name"] = next.name
                        result["next_subject"] = next.subject
                        result["next_start"] = next.start.format(HH_MM)
                        result["next_end"] = next.end.format(HH_MM)
                    }
                    break
                }
                now < start -> {
                    result["state"] = if (index == 0) "before_class" else "between_class"
                    result["next_period"] = slot.key
                    result["next_name"] = slot.name
                    result["next_subject"] = slot.subject
                    result["next_start"] = slot.start.format(HH_MM)
                    result["next_end"] = slot.end.format(HH_MM)
                    val seconds = java.time.Duration.between(now, start).seconds
                    result["seconds_to_next"] = seconds
                    result["is_counting"] = seconds in (PREBELL_AHEAD * 60 + 1)..(REMIND_AHEAD * 60)
                    result["is_prebell"] = seconds in 1..(PREBELL_AHEAD * 60)
                    result["seconds_to_prebell"] = java.time.Duration.between(now, start.minusMinutes(PREBELL_AHEAD)).seconds
                    break
                }
            }
        }
        return result
    }

    fun stateLine(info: Map<*, *>): String = when (info.str("state")) {
        "in_class" -> "正在上课 · ${info.str("current_name")} ${info.str("current_subject")}"
        "before_class" -> "上课前 · 下一节 ${info.str("next_subject")}"
        "between_class" -> "课间 · 下一节 ${info.str("next_subject")}"
        "after_school" -> "已放学"
        "weekend" -> "周末"
        "disabled" -> "暂停提醒 · ${info.str("disabled_note")}"
        else -> "等待状态更新"
    }
}
