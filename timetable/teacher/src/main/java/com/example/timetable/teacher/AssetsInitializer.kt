package com.example.timetable.teacher

import android.content.Context
import java.io.File

/** 首次启动时把内置的班级数据复制到应用私有目录。 */
object AssetsInitializer {
    fun copyIfNeeded(context: Context) {
        val names = runCatching { context.assets.list("") }.getOrNull() ?: return
        names.filter { it.endsWith(".json") || it.endsWith(".txt") }.forEach { name ->
            val target = File(context.filesDir, name)
            if (target.exists()) return@forEach
            runCatching {
                context.assets.open(name).use { input ->
                    target.outputStream().use { output ->
                        input.copyTo(output)
                    }
                }
            }
        }
    }
}
