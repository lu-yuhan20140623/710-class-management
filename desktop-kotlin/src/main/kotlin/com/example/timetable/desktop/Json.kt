package com.example.timetable.desktop

/** 不依赖第三方库的最小 JSON 实现，兼容 Python json.dump 的常见输出。 */
object Json {
    fun parse(text: String): Any? = Parser(text).parseValue()

    fun stringify(value: Any?): String {
        val sb = StringBuilder()
        write(value, sb)
        return sb.toString()
    }

    fun pretty(value: Any?): String {
        val sb = StringBuilder()
        write(value, sb, 0, "  ")
        return sb.toString()
    }

    fun obj(vararg pairs: Pair<String, Any?>): MutableMap<String, Any?> = linkedMapOf(*pairs)

    private class Parser(private val src: String) {
        private var pos = 0

        fun parseValue(): Any? {
            skipWs()
            if (pos >= src.length) return null
            return when (src[pos]) {
                '{' -> parseObject()
                '[' -> parseArray()
                '"' -> parseString()
                't' -> { expect("true"); true }
                'f' -> { expect("false"); false }
                'n' -> { expect("null"); null }
                else -> parseNumber()
            }
        }

        private fun skipWs() {
            while (pos < src.length && src[pos].isWhitespace()) pos++
        }

        private fun expect(word: String) {
            if (!src.startsWith(word, pos)) error("JSON 解析失败：位置 $pos 期望 $word")
            pos += word.length
        }

        private fun parseObject(): MutableMap<String, Any?> {
            pos++
            val result = linkedMapOf<String, Any?>()
            skipWs()
            if (pos < src.length && src[pos] == '}') { pos++; return result }
            while (pos < src.length) {
                skipWs()
                val key = parseString()
                skipWs()
                if (pos >= src.length || src[pos] != ':') error("JSON 解析失败：位置 $pos 期望 :")
                pos++
                result[key] = parseValue()
                skipWs()
                if (pos >= src.length) error("JSON 解析失败：对象未闭合")
                if (src[pos] == ',') { pos++; continue }
                if (src[pos] == '}') { pos++; return result }
                error("JSON 解析失败：位置 $pos 出现非法字符 ${src[pos]}")
            }
            error("JSON 解析失败：对象未闭合")
        }

        private fun parseArray(): MutableList<Any?> {
            pos++
            val result = mutableListOf<Any?>()
            skipWs()
            if (pos < src.length && src[pos] == ']') { pos++; return result }
            while (pos < src.length) {
                result.add(parseValue())
                skipWs()
                if (pos >= src.length) error("JSON 解析失败：数组未闭合")
                if (src[pos] == ',') { pos++; continue }
                if (src[pos] == ']') { pos++; return result }
                error("JSON 解析失败：位置 $pos 出现非法字符 ${src[pos]}")
            }
            error("JSON 解析失败：数组未闭合")
        }

        private fun parseString(): String {
            if (pos >= src.length || src[pos] != '"') error("JSON 解析失败：位置 $pos 期望字符串")
            pos++
            val sb = StringBuilder()
            while (pos < src.length) {
                val c = src[pos++]
                when (c) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        if (pos >= src.length) error("JSON 解析失败：转义未结束")
                        when (val e = src[pos++]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000C')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> {
                                if (pos + 4 > src.length) error("JSON 解析失败：Unicode 转义不完整")
                                val hex = src.substring(pos, pos + 4)
                                sb.append(hex.toInt(16).toChar())
                                pos += 4
                            }
                            else -> error("JSON 解析失败：未知转义 \\$e")
                        }
                    }
                    else -> sb.append(c)
                }
            }
            error("JSON 解析失败：字符串未闭合")
        }

        private fun parseNumber(): Number {
            val start = pos
            while (pos < src.length && src[pos] in "-+0123456789.eE") pos++
            if (start == pos) error("JSON 解析失败：位置 $pos 出现非法字符 ${src[pos]}")
            val text = src.substring(start, pos)
            return if (text.any { it == '.' || it == 'e' || it == 'E' }) text.toDouble() else text.toLong()
        }
    }

    private fun write(value: Any?, sb: StringBuilder, depth: Int = 0, indent: String? = null) {
        when (value) {
            null -> sb.append("null")
            is String -> writeString(value, sb)
            is Boolean, is Number -> sb.append(value.toString())
            is Map<*, *> -> {
                sb.append('{')
                if (value.isNotEmpty()) {
                    value.entries.forEachIndexed { index, entry ->
                        if (index > 0) sb.append(',')
                        newline(sb, depth + 1, indent)
                        writeString(entry.key?.toString() ?: "", sb)
                        sb.append(':')
                        if (indent != null) sb.append(' ')
                        write(entry.value, sb, depth + 1, indent)
                    }
                    newline(sb, depth, indent)
                }
                sb.append('}')
            }
            is Iterable<*> -> {
                sb.append('[')
                value.forEachIndexed { index, item ->
                    if (index > 0) sb.append(',')
                    newline(sb, depth + 1, indent)
                    write(item, sb, depth + 1, indent)
                }
                newline(sb, depth, indent)
                sb.append(']')
            }
            is Array<*> -> write(value.toList(), sb, depth, indent)
            else -> writeString(value.toString(), sb)
        }
    }

    private fun newline(sb: StringBuilder, depth: Int, indent: String?) {
        if (indent == null) return
        sb.append('\n')
        repeat(depth) { sb.append(indent) }
    }

    private fun writeString(text: String, sb: StringBuilder) {
        sb.append('"')
        for (c in text) {
            when (c) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                '\b' -> sb.append("\\b")
                '\u000C' -> sb.append("\\f")
                else -> if (c < ' ') sb.append("\\u%04X".format(c.code)) else sb.append(c)
            }
        }
        sb.append('"')
    }
}

@Suppress("UNCHECKED_CAST")
fun Any?.asMap(): Map<String, Any?> = this as? Map<String, Any?> ?: emptyMap()

@Suppress("UNCHECKED_CAST")
fun Any?.asMutableMap(): MutableMap<String, Any?> = this as? MutableMap<String, Any?> ?: linkedMapOf()

@Suppress("UNCHECKED_CAST")
fun Any?.asList(): List<Any?> = this as? List<Any?> ?: emptyList()

@Suppress("UNCHECKED_CAST")
fun Any?.asMutableList(): MutableList<Any?> = this as? MutableList<Any?> ?: mutableListOf()

fun Map<*, *>.str(key: String, default: String = ""): String = when (val v = this[key]) {
    null -> default
    is String -> v
    else -> v.toString()
}

fun Map<*, *>.num(key: String, default: Int = 0): Int = when (val v = this[key]) {
    is Number -> v.toInt()
    is String -> v.toIntOrNull() ?: default
    else -> default
}

fun Map<*, *>.flag(key: String): Boolean = when (val v = this[key]) {
    is Boolean -> v
    is Number -> v.toInt() != 0
    is String -> v.equals("true", ignoreCase = true) || v == "1"
    else -> false
}
