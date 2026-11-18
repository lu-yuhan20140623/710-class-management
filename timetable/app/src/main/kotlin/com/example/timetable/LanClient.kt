package com.example.timetable

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * 局域网客户端：与电脑端的 /api/events 建立 SSE 长连接。
 * 电脑端在打分、扣分、调课、上下课时会立即推送 snapshot；断线后每 3 秒自动重连。
 */
class LanClient(
    private val onSnapshot: (JSONObject) -> Unit,
    private val onStatus: (String, Boolean) -> Unit
) {
    @Volatile private var running = false
    @Volatile private var active: HttpURLConnection? = null
    private var worker: Thread? = null

    fun start(baseUrl: String) {
        stop()
        running = true
        val base = baseUrl.trimEnd('/')
        worker = Thread({ loop(base) }, "lan-client").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running = false
        try {
            active?.disconnect()
        } catch (_: Exception) {
        }
        active = null
        worker?.interrupt()
        worker = null
    }

    private fun loop(base: String) {
        while (running) {
            var conn: HttpURLConnection? = null
            try {
                onStatus("连接中…", false)
                conn = (URL("$base/api/events").openConnection() as HttpURLConnection).apply {
                    connectTimeout = 4000
                    readTimeout = 30_000
                    requestMethod = "GET"
                    setRequestProperty("Accept", "text/event-stream")
                    setRequestProperty("Cache-Control", "no-cache")
                }
                active = conn
                if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                    throw java.io.IOException("HTTP ${conn.responseCode}")
                }
                onStatus("已连接", true)

                // SSE 格式：event: snapshot / data: {...} / 空行
                conn.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                    var event = "message"
                    val data = StringBuilder()
                    while (running) {
                        val line = reader.readLine() ?: break
                        when {
                            line.isEmpty() -> {
                                if (data.isNotEmpty()) handle(event, data.toString())
                                event = "message"
                                data.setLength(0)
                            }
                            line.startsWith("event:") -> event = line.substring(6).trim()
                            line.startsWith("data:") -> {
                                if (data.isNotEmpty()) data.append('\n')
                                data.append(line.substring(5).trim())
                            }
                            // 以 ":" 开头的是心跳注释，忽略
                        }
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("LanClient", "连接 $base 失败", e)
                if (running) {
                    onStatus("连接失败：${e.message ?: e.javaClass.simpleName}", false)
                    try {
                        Thread.sleep(3000)
                    } catch (_: InterruptedException) {
                        return
                    }
                }
            } finally {
                try {
                    conn?.disconnect()
                } catch (_: Exception) {
                }
                active = null
            }
        }
    }

    private fun handle(event: String, raw: String) {
        if (event != "snapshot") return
        try {
            onSnapshot(JSONObject(raw))
        } catch (_: Exception) {
            // 单条数据解析失败时忽略，等待下一次推送
        }
    }
}
