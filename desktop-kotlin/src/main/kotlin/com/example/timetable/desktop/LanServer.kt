package com.example.timetable.desktop

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/** 内置局域网只读服务，接口与原 Python 版一致，手机 App 无需改动。 */
object LanServer {
    private const val DEFAULT_PORT = 8765
    private var server: HttpServer? = null
    private val executor = Executors.newCachedThreadPool { r ->
        Thread(r, "lan-server-worker").apply { isDaemon = true }
    }
    private val subscribers = Collections.newSetFromMap(ConcurrentHashMap<HttpExchange, Boolean>())
    private var lastFingerprint: Any? = null
    private var lastPushAt = 0L

    @Volatile
    var running: Boolean = false
        private set

    @Volatile
    var port: Int = DEFAULT_PORT
        private set

    fun start(port: Int = configuredPort()): String? = synchronized(this) {
        if (running) return "服务已经在运行"
        val bound = runCatching {
            HttpServer.create(InetSocketAddress(port), 0).also { it.executor = executor }
        }.getOrElse { return "端口 $port 启动失败：${it.message}" }

        bound.createContext("/") { exchange ->
            if (exchange.requestURI.path != "/") {
                sendJson(exchange, linkedMapOf("error" to "not found"))
                return@createContext
            }
            sendText(
                exchange,
                "Kotlin 桌面端课堂服务\n\n" +
                    "GET /api/ping       健康检查\n" +
                    "GET /api/snapshot   完整数据快照\n" +
                    "GET /api/state      当前课节状态\n" +
                    "GET /api/schedule   本周课表\n" +
                    "GET /api/scores     小组积分\n" +
                    "GET /api/hygiene    卫生扣分\n" +
                    "GET /api/events     SSE 实时推送\n",
            )
        }
        bound.createContext("/api/ping") { exchange ->
            sendJson(exchange, linkedMapOf(
                "ok" to true, "app" to "class-schedule", "version" to "2.0.0-kotlin", "time" to System.currentTimeMillis(),
            ))
        }
        bound.createContext("/api/snapshot") { exchange ->
            sendJson(exchange, SnapshotBuilder.build())
        }
        bound.createContext("/api/state") { exchange ->
            sendJson(exchange, SnapshotBuilder.build()["state"] ?: emptyMap<String, Any?>())
        }
        bound.createContext("/api/schedule") { exchange ->
            val snapshot = SnapshotBuilder.build()
            sendJson(exchange, linkedMapOf(
                "periods" to snapshot["periods"], "extra_slots" to snapshot["extra_slots"],
                "schedule" to snapshot["schedule"], "extra_schedule" to snapshot["extra_schedule"],
            ))
        }
        bound.createContext("/api/scores") { exchange ->
            val snapshot = SnapshotBuilder.build()
            sendJson(exchange, linkedMapOf(
                "students" to snapshot["students"], "groups" to snapshot["groups"],
            ))
        }
        bound.createContext("/api/hygiene") { exchange ->
            sendJson(exchange, SnapshotBuilder.build()["hygiene"] ?: emptyMap<String, Any?>())
        }
        bound.createContext("/api/events") { exchange -> sse(exchange) }

        bound.start()
        server = bound
        this.port = port
        running = true
        lastFingerprint = null
        null
    }

    fun stop() = synchronized(this) {
        server?.stop(0)
        server = null
        running = false
        subscribers.forEach { runCatching { it.close() } }
        subscribers.clear()
    }

    fun url(): String = "http://${lanIp()}:$port"

    fun configuredPort(): Int {
        val value = DataStore.settings()["lan_port"] ?: return DEFAULT_PORT
        val parsed = value.toString().toIntOrNull() ?: return DEFAULT_PORT
        return if (parsed in 1024..65535) parsed else DEFAULT_PORT
    }

    private fun lanIp(): String {
        var socket: DatagramSocket? = null
        try {
            socket = DatagramSocket()
            socket.connect(InetAddress.getByName("223.5.5.5"), 80)
            val ip = socket.localAddress.hostAddress
            if (!ip.isNullOrBlank() && !ip.startsWith("127.")) return ip
        } catch (_: Exception) {
        } finally {
            runCatching { socket?.close() }
        }
        return runCatching {
            InetAddress.getLocalHost().hostAddress
        }.getOrDefault("127.0.0.1")
    }

    private fun sendJson(exchange: HttpExchange, value: Any?) {
        val bytes = Json.stringify(value).toByteArray(StandardCharsets.UTF_8)
        exchange.responseHeaders.set("Content-Type", "application/json; charset=utf-8")
        exchange.responseHeaders.set("Access-Control-Allow-Origin", "*")
        exchange.sendResponseHeaders(200, bytes.size.toLong())
        exchange.responseBody.use { it.write(bytes) }
    }

    private fun sendText(exchange: HttpExchange, text: String) {
        val bytes = text.toByteArray(StandardCharsets.UTF_8)
        exchange.responseHeaders.set("Content-Type", "text/plain; charset=utf-8")
        exchange.responseHeaders.set("Access-Control-Allow-Origin", "*")
        exchange.sendResponseHeaders(200, bytes.size.toLong())
        exchange.responseBody.use { it.write(bytes) }
    }

    private fun sse(exchange: HttpExchange) {
        exchange.responseHeaders.set("Content-Type", "text/event-stream; charset=utf-8")
        exchange.responseHeaders.set("Cache-Control", "no-cache")
        exchange.responseHeaders.set("Connection", "keep-alive")
        exchange.responseHeaders.set("Access-Control-Allow-Origin", "*")
        exchange.sendResponseHeaders(200, 0)
        val out = exchange.responseBody
        out.write(": connected\n\n".toByteArray(StandardCharsets.UTF_8))
        out.flush()
        subscribers.add(exchange)
        var lastHeartbeat = System.currentTimeMillis()
        try {
            while (running && exchange in subscribers) {
                Thread.sleep(500)
                if (System.currentTimeMillis() - lastHeartbeat >= 12_000) {
                    out.write(": heartbeat\n\n".toByteArray(StandardCharsets.UTF_8))
                    out.flush()
                    lastHeartbeat = System.currentTimeMillis()
                }
            }
        } catch (_: Exception) {
        } finally {
            subscribers.remove(exchange)
            runCatching { out.close() }
            runCatching { exchange.close() }
        }
    }

    /** 由主界面定时器调用，数据或课节状态变化时主动推送。 */
    fun checkAndPublish() {
        if (!running) return
        val key = fingerprint()
        val now = System.currentTimeMillis()
        if (key != lastFingerprint || now - lastPushAt >= 60_000) {
            lastFingerprint = key
            lastPushAt = now
            publish("snapshot", SnapshotBuilder.build())
        }
    }

    fun publish(event: String, payload: Any?) {
        if (!running) return
        val message = "event: $event\ndata: ${Json.stringify(payload)}\n\n".toByteArray(StandardCharsets.UTF_8)
        subscribers.toList().forEach { exchange ->
            try {
                synchronized(exchange) {
                    exchange.responseBody.write(message)
                    exchange.responseBody.flush()
                }
            } catch (_: Exception) {
                subscribers.remove(exchange)
            }
        }
    }

    private fun fingerprint(): Any {
        val info = ScheduleService.state()
        val stateKey = listOf(
            info.str("state"), info["current_period"], info["next_period"],
            info.flag("is_counting"), info.flag("is_prebell"), info.flag("disabled"),
        )
        val watched = listOf(
            "class_data.txt", "student_data.txt", "group_data.txt", "hygiene_data.txt",
            "overrides.json", "disabled_ranges.json", "settings.json",
        )
        val stamps = watched.map { name ->
            val file = DataStore.path(name)
            if (java.nio.file.Files.exists(file)) {
                listOf(name, java.nio.file.Files.getLastModifiedTime(file).toMillis(), java.nio.file.Files.size(file))
            } else listOf(name, 0L, 0L)
        }
        return stateKey to stamps
    }
}
