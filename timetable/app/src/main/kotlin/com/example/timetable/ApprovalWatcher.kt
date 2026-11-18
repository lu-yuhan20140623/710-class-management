package com.example.timetable

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

// ============================================================================
// 手机端确认：轮询电脑端的“待确认”重置请求，用户点同意/拒绝后回传
// ============================================================================
class ApprovalWatcher(
    private val base: String,
    private val onAsk: (String, String, String) -> Unit
) {
    @Volatile private var running = true
    private val seen = HashSet<String>()
    private var thread: Thread? = null

    fun start() {
        thread = Thread {
            while (running) {
                try {
                    val conn = (URL("$base/api/approvals/pending")
                        .openConnection() as HttpURLConnection).apply {
                        requestMethod = "GET"
                        connectTimeout = 3_000
                        readTimeout = 5_000
                    }
                    val body = conn.inputStream.bufferedReader().use { it.readText() }
                    conn.disconnect()
                    val arr = JSONObject(body).optJSONArray("items") ?: JSONArray()
                    for (i in 0 until arr.length()) {
                        val item = arr.getJSONObject(i)
                        val id = item.optString("id")
                        if (id.isNotEmpty() && seen.add(id)) {
                            onAsk(id, item.optString("title"), item.optString("detail"))
                        }
                    }
                } catch (_: Throwable) {
                    // 网络中断：下轮继续
                }
                try {
                    Thread.sleep(2_000)
                } catch (_: InterruptedException) {
                    break
                }
            }
        }.also {
            it.isDaemon = true
            it.start()
        }
    }

    fun postDecision(id: String, approve: Boolean) {
        Thread {
            try {
                val conn = (URL("$base/api/approvals/decide")
                    .openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    doOutput = true
                    connectTimeout = 3_000
                    readTimeout = 5_000
                    setRequestProperty("Content-Type", "application/json")
                }
                conn.outputStream.use {
                    it.write("""{"id":"$id","approve":$approve}""".toByteArray())
                }
                conn.inputStream.close()
                conn.disconnect()
            } catch (_: Throwable) {
            }
        }.also {
            it.isDaemon = true
            it.start()
        }
    }

    fun stop() {
        running = false
        thread?.interrupt()
    }
}
