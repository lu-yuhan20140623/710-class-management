package com.example.timetable.desktop

import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** 生成与 Python 版 /api/snapshot 完全兼容的数据结构，供手机端直接消费。 */
object SnapshotBuilder {
    private val shortTimeFormat = DateTimeFormatter.ofPattern("MM-dd HH:mm")

    fun build(): MutableMap<String, Any?> {
        val cls = DataStore.className()
        val now = LocalDateTime.now()
        val state = ScheduleService.state(now)
        return linkedMapOf<String, Any?>(
            "type" to "snapshot",
            "app" to "class-schedule",
            "version" to "2.0.0-kotlin",
            "class_name" to cls,
            "server_time" to now.format(DATE_TIME),
            "epoch_ms" to System.currentTimeMillis(),
            "state" to stateView(state),
            "reset_hint" to "积分每周一 12:00 归档 · 卫生每天 12:00 归档",
            "periods" to periodView(ScheduleService.periods),
            "extra_slots" to periodView(ScheduleService.extraSlots),
            "schedule" to scheduleView(),
            "extra_schedule" to extraScheduleView(),
            "students" to studentRows(cls),
            "groups" to groupScores(cls),
            "hygiene" to hygieneView(cls),
            "approvals" to Approvals.pending(),
        )
    }

    private fun periodView(periods: List<Period>) = periods.map { p ->
        linkedMapOf<String, Any?>(
            "id" to p.id, "name" to p.name,
            "start" to p.start.format(HH_MM), "end" to p.end.format(HH_MM),
        )
    }

    private fun stateView(info: Map<*, *>): Map<String, Any?> {
        val now = LocalDateTime.now()
        var secondsToEnd: Long = 0
        val end = info.str("current_end")
        if (info.str("state") == "in_class" && end.isNotBlank()) {
            runCatching {
                val endDt = LocalDateTime.of(now.toLocalDate(), java.time.LocalTime.parse(end, HH_MM))
                secondsToEnd = maxOf(0, java.time.Duration.between(now, endDt).seconds)
            }
        }
        val day = info.num("day")
        return linkedMapOf<String, Any?>(
            "state" to info.str("state"),
            "weekday" to if (day >= 0) ScheduleService.weekdayNames.getOrElse(day) { "" } else "周末",
            "day" to day,
            "current_period" to info["current_period"],
            "current_name" to info.str("current_name"),
            "current_subject" to info.str("current_subject"),
            "current_start" to info["current_start"],
            "current_end" to info["current_end"],
            "seconds_to_current_end" to secondsToEnd,
            "next_period" to info["next_period"],
            "next_name" to info.str("next_name"),
            "next_subject" to info.str("next_subject"),
            "next_start" to info["next_start"],
            "next_end" to info["next_end"],
            "seconds_to_next" to info.num("seconds_to_next"),
            "is_counting" to info.flag("is_counting"),
            "is_prebell" to info.flag("is_prebell"),
            "seconds_to_prebell" to info.num("seconds_to_prebell"),
            "disabled" to info.flag("disabled"),
            "disabled_note" to info.str("disabled_note"),
            "school_end" to info["school_end"],
            "server_epoch_ms" to System.currentTimeMillis(),
            "server_time" to now.format(DATE_TIME),
        )
    }

    private fun scheduleView() = ScheduleService.defaultSchedule.flatMap { (day, periods) ->
        periods.map { (pid, default) ->
            linkedMapOf<String, Any?>(
                "day_index" to day,
                "period_id" to pid,
                "subject" to ScheduleService.subject(day, pid).ifBlank { default },
                "classroom" to "",
            )
        }
    }

    private fun extraScheduleView() = (0 until 5).flatMap { day ->
        listOf(
            linkedMapOf<String, Any?>(
                "day_index" to day, "period_id" to 99,
                "subject" to (ScheduleService.practiceSubjects[day] ?: "小练"), "classroom" to "",
            ),
            linkedMapOf<String, Any?>(
                "day_index" to day, "period_id" to 100,
                "subject" to "晚辅", "classroom" to "",
            ),
        )
    }

    private fun studentRows(cls: String) = ScoreService.studentRows(cls)
        .map { row ->
            linkedMapOf<String, Any?>(
                "sid" to row.sid,
                "name" to row.name,
                "group" to if (row.group == "未分组") "" else row.group,
                "total" to row.total,
            )
        }
        .sortedWith(compareBy({ it["group"] as String }, { it["sid"] as String }))

    private fun groupScores(cls: String): List<Map<String, Any?>> {
        val stu = ScoreService.classStudents(cls)
        return ScoreService.groupRows(cls).map { row ->
            val group = ScoreService.classGroups(cls)[row.name].asMap()
            val leaderSid = group.str("leader")
            val leader = stu[leaderSid].asMap().str("name").ifBlank { leaderSid }
            val records = mutableListOf<Map<String, Any?>>()
            val members = mutableListOf<Map<String, Any?>>()
            group["members"].asList().forEach { raw ->
                val sid = raw?.toString() ?: return@forEach
                val info = stu[sid].asMap()
                if (info.isEmpty()) return@forEach
                members.add(linkedMapOf<String, Any?>(
                    "sid" to sid,
                    "name" to info.str("name"),
                    "total" to ScoreService.studentTotal(info),
                    "leader" to (sid == leaderSid),
                ))
                info["records"].asList().forEach { rec ->
                    val item = rec.asMap()
                    records.add(linkedMapOf<String, Any?>(
                        "time" to shortTime(item.str("time")),
                        "reason" to item.str("reason"),
                        "delta" to ScoreService.recordDelta(item),
                        "member" to info.str("name"),
                    ))
                }
            }
            linkedMapOf<String, Any?>(
                "name" to row.name,
                "leader" to leader,
                "total" to row.total,
                "records" to records.sortedByDescending { it["time"] as String }.take(50),
                "members" to members,
            )
        }
    }

    private fun shortTime(value: String): String = runCatching {
        LocalDateTime.parse(value, DATE_TIME).format(shortTimeFormat)
    }.getOrDefault(value)

    private fun hygieneView(cls: String): Map<String, Any?> {
        val rows = HygieneService.records(cls)
        val groupNames = ScoreService.classGroups(cls).keys.toList()
        val byGroup = linkedMapOf<String, Int>().apply { groupNames.forEach { this[it] = 0 } }
        val byReason = linkedMapOf<String, Int>()
        rows.forEach { row ->
            byGroup[row.group] = (byGroup[row.group] ?: 0) + row.score
            val reason = row.reason.ifBlank { "未填写" }
            byReason[reason] = (byReason[reason] ?: 0) + 1
        }
        return linkedMapOf<String, Any?>(
            "total_records" to rows.size,
            "total_deduct" to rows.sumOf { it.score },
            "by_group" to byGroup.entries.sortedByDescending { it.value }.map { listOf(it.key, it.value) },
            "by_reason" to byReason.entries.sortedByDescending { it.value }.map { listOf(it.key, it.value) },
            "records" to rows.take(300).map { row ->
                linkedMapOf<String, Any?>(
                    "group" to row.group,
                    "member" to row.name,
                    "reason" to row.reason.ifBlank { "未填写" },
                    "score" to row.score,
                    "time" to shortTime(row.time),
                    "date" to row.date,
                    "by" to row.by.ifBlank { "未记录" },
                    "by_sid" to "",
                )
            },
        )
    }
}
