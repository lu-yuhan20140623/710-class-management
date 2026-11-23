package com.example.timetable.desktop

import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.nio.file.StandardCopyOption
import kotlin.io.path.exists

/** 直接使用原 Python 版的数据文件，保证手机端 / 旧版数据无缝衔接。 */
object DataStore {
    val dataDir: Path = locateDataDir()

    private fun locateDataDir(): Path {
        System.getProperty("timetable.data.dir")?.let { return Paths.get(it).toAbsolutePath().normalize() }
        var dir = Paths.get("").toAbsolutePath().normalize()
        if (dir.resolve("student_data.txt").exists()) return dir
        dir.parent?.let { parent ->
            if (parent.resolve("student_data.txt").exists()) return parent
        }
        return dir
    }

    fun path(name: String): Path = dataDir.resolve(name)

    fun loadMap(name: String): MutableMap<String, Any?> {
        val path = path(name)
        if (!path.exists()) return linkedMapOf()
        val parsed = runCatching { Json.parse(Files.readString(path, StandardCharsets.UTF_8)) }.getOrNull()
        return parsed.asMutableMap()
    }

    fun loadList(name: String): MutableList<Any?> {
        val path = path(name)
        if (!path.exists()) return mutableListOf()
        val parsed = runCatching { Json.parse(Files.readString(path, StandardCharsets.UTF_8)) }.getOrNull()
        return parsed.asMutableList()
    }

    fun save(name: String, value: Any?) {
        val target = path(name)
        val tmp = target.resolveSibling(target.fileName.toString() + ".ktmp")
        Files.createDirectories(target.parent)
        Files.writeString(tmp, Json.pretty(value), StandardCharsets.UTF_8)
        runCatching {
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        }.onFailure {
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING)
        }
    }

    fun settings(): MutableMap<String, Any?> = loadMap("settings.json")

    fun saveSettings(settings: Map<String, Any?>) = save("settings.json", settings)

    fun className(): String {
        val classes = loadList("class_data.txt")
        return classes.firstOrNull { it is String && it.isNotBlank() }?.toString() ?: "七年级10班"
    }
}
