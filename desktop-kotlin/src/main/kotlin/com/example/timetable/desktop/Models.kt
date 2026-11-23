package com.example.timetable.desktop

import java.time.LocalTime

data class Period(val id: Int, val name: String, val start: LocalTime, val end: LocalTime) {
    val clock: String get() = "${start.format(HH_MM)}-${end.format(HH_MM)}"
}

data class Slot(
    val key: Any,
    val name: String,
    val subject: String,
    val start: LocalTime,
    val end: LocalTime,
    val kind: String,
)

data class GroupRow(val name: String, val count: Int, val total: Int, val own: Int, val legacy: Int)

data class StudentRow(
    val sid: String,
    val name: String,
    val group: String,
    val total: Int,
    val isLeader: Boolean,
)

data class PointRow(
    val group: String,
    val sid: String,
    val name: String,
    val time: String,
    val reason: String,
    val delta: Int,
    val recordIndex: Int,
)

data class HygieneRow(
    val id: String,
    val sid: String,
    val name: String,
    val group: String,
    val reason: String,
    val score: Int,
    val note: String,
    val time: String,
    val date: String,
    val by: String,
    val recordIndex: Int,
)

val HH_MM = java.time.format.DateTimeFormatter.ofPattern("HH:mm")
val DATE_TIME = java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
val MINUTE_FORMAT = java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm")
