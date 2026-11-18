package com.example.timetable

// ============================================================================
// 一、数据层（来自电脑端局域网接口）
// ============================================================================

data class Period(
    val id: Int, val name: String, val start: String, val end: String
)

data class CourseCell(
    val dayIndex: Int, val periodId: Int, val subject: String, val classroom: String
)

data class ScoreRecord(
    val time: String, val reason: String, val delta: Int
)

data class GroupScore(
    val name: String, val leader: String, val total: Int, val records: List<ScoreRecord>
)

data class HygieneRecord(
    val group: String, val member: String, val reason: String, val score: Int, val time: String
)
