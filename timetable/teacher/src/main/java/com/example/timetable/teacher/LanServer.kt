package com.example.timetable.teacher

import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/** Android 版局域网只读服务，接口与 Python 电脑端一致。 */
object LanServer {
    private const val DEFAULT_PORT = 8765
    private var server: ServerSocket? = null
    private val executor = Executors.newCachedThreadPool { r ->
        Thread(r, "lan-teacher").apply { isDaemon = true }
    }
    private val subscribers = Collections.newSetFromMap(ConcurrentHashMap<Socket, Boolean>())
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
        val socket = runCatching { ServerSocket(port) }
            .getOrElse { return "端口 $port 启动失败：${it.message}" }
        server = socket
        this.port = port
        running = true
        lastFingerprint = null
        executor.execute {
            while (running) {
                try {
                    val client = socket.accept() ?: break
                    executor.execute { handle(client) }
                } catch (_: Exception) {
                    break
                }
            }
        }
        null
    }

    fun stop() = synchronized(this) {
        running = false
        runCatching { server?.close() }
        server = null
        subscribers.forEach { runCatching { it.close() } }
        subscribers.clear()
    }

    fun configuredPort(): Int {
        val value = DataStore.settings()["lan_port"]?.toString()?.toIntOrNull() ?: return DEFAULT_PORT
        return if (value in 1024..65535) value else DEFAULT_PORT
    }

    fun url(): String = "http://${lanIp()}:$port"

    private fun lanIp(): String {
        runCatching {
            NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
                .firstOrNull { it is Inet4Address && !it.isLoopbackAddress && it.isSiteLocalAddress }
                ?.hostAddress
                ?.let { return it }
        }
        return runCatching { InetAddress.getByName("127.0.0.1").hostAddress }.getOrDefault("127.0.0.1")
    }

    private fun handle(socket: Socket) {
        try {
            socket.soTimeout = 5000
            val reader = BufferedReader(InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8))
            val request = reader.readLine() ?: return
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
            }
            val path = request.split(" ").getOrNull(1) ?: "/"
            when {
                path == "/" -> sendText(socket, "课程表教师端（Android）\n/api/snapshot /api/state /api/schedule /api/scores /api/hygiene /api/events\n")
                path == "/api/ping" -> sendJson(socket, linkedMapOf(
                    "ok" to true, "app" to "class-schedule", "device" to "android-teacher", "time" to System.currentTimeMillis(),
                ))
                path == "/api/snapshot" -> sendJson(socket, SnapshotBuilder.build())
                path == "/api/state" -> sendJson(socket, SnapshotBuilder.build()["state"] ?: emptyMap<String, Any?>())
                path == "/api/schedule" -> {
                    val snap = SnapshotBuilder.build()
                    sendJson(socket, linkedMapOf(
                        "periods" to snap["periods"], "extra_slots" to snap["extra_slots"],
                        "schedule" to snap["schedule"], "extra_schedule" to snap["extra_schedule"],
                    ))
                }
                path == "/api/scores" -> {
                    val snap = SnapshotBuilder.build()
                    sendJson(socket, linkedMapOf("students" to snap["students"], "groups" to snap["groups"]))
                }
                path == "/api/hygiene" -> sendJson(socket, SnapshotBuilder.build()["hygiene"] ?: emptyMap<String, Any?>())
                path == "/api/events" -> sse(socket)
                else -> sendJson(socket, linkedMapOf("error" to "not found"))
            }
        } catch (_: Exception) {
            runCatching { socket.close() }
        }
    }

    private fun sendJson(socket: Socket, value: Any?) {
        val body = Json.stringify(value).toByteArray(StandardCharsets.UTF_8)
        val header = "HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n" +
            "Access-Control-Allow-Origin: *\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n"
        socket.getOutputStream().write(header.toByteArray(StandardCharsets.UTF_8) + body)
        socket.getOutputStream().flush()
        socket.close()
    }

    private fun sendText(socket: Socket, text: String) {
        val body = text.toByteArray(StandardCharsets.UTF_8)
        val header = "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n" +
            "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n"
        socket.getOutputStream().write(header.toByteArray(StandardCharsets.UTF_8) + body)
        socket.getOutputStream().flush()
        socket.close()
    }

    private fun sse(socket: Socket) {
        val out = socket.getOutputStream()
        val header = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\n" +
            "Cache-Control: no-cache\r\nAccess-Control-Allow-Origin: *\r\n\r\n"
        out.write(header.toByteArray(StandardCharsets.UTF_8))
        out.write(": connected\n\n".toByteArray(StandardCharsets.UTF_8))
        out.flush()
        subscribers.add(socket)
        var last = System.currentTimeMillis()
        try {
            while (running && socket in subscribers) {
                Thread.sleep(500)
                if (System.currentTimeMillis() - last > 12_000) {
                    out.write(": heartbeat\n\n".toByteArray(StandardCharsets.UTF_8))
                    out.flush()
                    last = System.currentTimeMillis()
                }
            }
        } catch (_: Exception) {
        } finally {
            subscribers.remove(socket)
            runCatching { socket.close() }
        }
    }

    fun publish(event: String, payload: Any?) {
        if (!running) return
        val message = "event: $event\ndata: ${Json.stringify(payload)}\n\n".toByteArray(StandardCharsets.UTF_8)
        subscribers.toList().forEach { socket ->
            try {
                synchronized(socket) {
                    socket.getOutputStream().write(message)
                    socket.getOutputStream().flush()
                }
            } catch (_: Exception) {
                subscribers.remove(socket)
            }
        }
    }

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

    private fun fingerprint(): Any {
        val info = ScheduleService.state()
        val stateKey = listOf(
            info.str("state"), info["current_period"], info["next_period"],
            info.flag("is_counting"), info.flag("is_prebell"), info.flag("disabled"),
        )
        val stamps = listOf(
            "class_data.txt", "student_data.txt", "group_data.txt", "hygiene_data.txt",
            "overrides.json", "disabled_ranges.json", "settings.json",
        ).map { name ->
            val file = DataStore.path(name)
            if (file.exists()) listOf(name, file.lastModified(), file.length()) else listOf(name, 0L, 0L)
        }
        return stateKey to stamps
    }
}
