package com.example.timetable

import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 云同步诊断日志：写入 filesDir/relay.log，超过 200 KB 自动截断一半。
 * 在「连接设置 → 同步日志」里可以直接查看。
 */
object RelayLog {
    private const val MAX_BYTES = 200 * 1024
    private val fmt = SimpleDateFormat("MM-dd HH:mm:ss", Locale.CHINA)
    private var file: File? = null

    fun init(dir: File) {
        file = File(dir, "relay.log")
    }

    @Synchronized
    fun log(message: String) {
        val f = file ?: return
        try {
            if (f.length() > MAX_BYTES) {
                f.writeText(f.readText().takeLast(MAX_BYTES / 2))
            }
            f.appendText("${fmt.format(Date())}  $message\n")
        } catch (_: Exception) {
        }
    }

    fun read(): String {
        val f = file ?: return "(日志未初始化)"
        return try {
            if (f.exists()) f.readText().ifEmpty { "(暂无日志)" } else "(暂无日志)"
        } catch (e: Exception) {
            "(读取失败：${e.message})"
        }
    }

    fun clear() {
        try {
            file?.writeText("")
        } catch (_: Exception) {
        }
    }
}
