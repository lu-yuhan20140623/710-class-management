package com.example.timetable.desktop

import java.util.concurrent.ConcurrentHashMap

/** 需要手机确认的操作（重置密钥等），结构与 Python 版一致。 */
object Approvals {
    private const val TTL_MS = 120_000L
    private val items = ConcurrentHashMap<String, MutableMap<String, Any?>>()
    private var sequence = 0

    fun submit(kind: String, title: String, detail: String = ""): Map<String, Any?> {
        cleanup()
        val id = "${System.currentTimeMillis()}-${++sequence}"
        items[id] = linkedMapOf<String, Any?>(
            "id" to id,
            "kind" to kind,
            "title" to title,
            "detail" to detail,
            "created" to System.currentTimeMillis(),
            "status" to "pending",
        )
        return linkedMapOf("id" to id, "expires_in" to 120)
    }

    fun pending(): List<Map<String, Any?>> {
        cleanup()
        return items.values
            .filter { it.str("status") == "pending" }
            .sortedBy { it.str("id") }
            .map { linkedMapOf("id" to it.str("id"), "kind" to it.str("kind"), "title" to it.str("title"), "detail" to it.str("detail")) }
    }

    fun decide(id: String, approve: Boolean): Boolean {
        cleanup()
        val item = items[id] ?: return false
        if (item.str("status") != "pending") return false
        item["status"] = if (approve) "approved" else "rejected"
        return true
    }

    private fun cleanup() {
        val now = System.currentTimeMillis()
        items.entries.removeIf { (_, item) ->
            val age = now - (item["created"] as? Long ?: 0L)
            if (item.str("status") == "pending" && age > TTL_MS) item["status"] = "expired"
            age > TTL_MS * 5
        }
    }
}
