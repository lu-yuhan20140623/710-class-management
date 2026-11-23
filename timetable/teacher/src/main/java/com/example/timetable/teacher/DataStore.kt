package com.example.timetable.teacher

import android.content.Context
import java.io.File

/** Android 端数据目录：应用私有 files 目录，避免权限问题。 */
object DataStore {
    @Volatile
    var context: Context? = null

    private val directory: File
        get() = context?.filesDir ?: File(System.getProperty("java.io.tmpdir"), "timetable-teacher")

    fun path(name: String): File = File(directory, name)

    @Synchronized
    fun loadMap(name: String): MutableMap<String, Any?> {
        val file = path(name)
        if (!file.exists()) return linkedMapOf()
        val parsed = runCatching { Json.parse(file.readText(Charsets.UTF_8)) }.getOrNull()
        return parsed.asMutableMap()
    }

    @Synchronized
    fun loadList(name: String): MutableList<Any?> {
        val file = path(name)
        if (!file.exists()) return mutableListOf()
        val parsed = runCatching { Json.parse(file.readText(Charsets.UTF_8)) }.getOrNull()
        return parsed.asMutableList()
    }

    @Synchronized
    fun save(name: String, value: Any?) {
        directory.mkdirs()
        val target = path(name)
        val tmp = File(directory, "$name.tmp")
        tmp.writeText(Json.pretty(value), Charsets.UTF_8)
        if (target.exists()) target.delete()
        tmp.renameTo(target)
    }

    fun settings(): MutableMap<String, Any?> = loadMap("settings.json")

    fun saveSettings(settings: Map<String, Any?>) = save("settings.json", settings)

    fun className(): String {
        val classes = loadList("class_data.txt")
        return classes.firstOrNull { it is String && it.isNotBlank() }?.toString() ?: "七年级10班"
    }
}
