package com.example.timetable

import android.util.Base64
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Gitee 仓库配置：手机与电脑填同一份。 */
data class CloudConfig(
    val owner: String,
    val repo: String,
    val branch: String,
    val token: String,
) {
    val configured: Boolean
        get() = owner.isNotBlank() && repo.isNotBlank() && token.isNotBlank()

    val label: String get() = "$owner/$repo"
}

/**
 * Gitee contents 接口的最小封装：读文件、写文件。
 * 所有方法都是阻塞的网络请求，只能在后台线程调用。
 */
class GiteeClient(private val cfg: CloudConfig) {
    private val shaCache = HashMap<String, String>()

    private fun encode(value: String): String =
        URLEncoder.encode(value, "UTF-8").replace("+", "%20")

    private fun pathUrl(path: String): String {
        val quoted = path.split("/").joinToString("/") { encode(it) }
        return "https://gitee.com/api/v5/repos/${cfg.owner}/${cfg.repo}/contents/$quoted"
    }

    private fun open(url: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 8000
            readTimeout = 8000
        }

    private fun readAll(conn: HttpURLConnection): String {
        val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
        return stream?.bufferedReader()?.use { it.readText() } ?: ""
    }

    /** 读不到（文件不存在）时返回 null。 */
    fun getText(path: String): String? {
        val url = "${pathUrl(path)}?access_token=${encode(cfg.token)}&ref=${encode(cfg.branch)}"
        val conn = open(url)
        try {
            val code = conn.responseCode
            if (code == 404) return null
            val body = readAll(conn)
            if (code !in 200..299) {
                RelayLog.log("GET $path → $code ${body.take(200)}")
                throw IOException("Gitee 读取失败 HTTP $code")
            }
            // Gitee 对不存在的文件返回 200 + []，按“不存在”处理
            if (body.trimStart().startsWith("[")) return null
            val json = JSONObject(body)
            val content = json.optString("content", "")
            val sha = json.optString("sha", "")
            if (sha.isNotEmpty()) shaCache[path] = sha
            if (content.isEmpty()) return ""
            return String(Base64.decode(content, Base64.DEFAULT), Charsets.UTF_8)
        } finally {
            conn.disconnect()
        }
    }

    private fun fetchSha(path: String): String? {
        val url = "${pathUrl(path)}?access_token=${encode(cfg.token)}&ref=${encode(cfg.branch)}"
        val conn = open(url)
        return try {
            if (conn.responseCode == 404) {
                null
            } else {
                val body = readAll(conn)
                if (body.trimStart().startsWith("[")) null
                else JSONObject(body).optString("sha", "").ifEmpty { null }
            }
        } catch (_: Exception) {
            null
        } finally {
            conn.disconnect()
        }
    }

    fun putText(path: String, text: String, message: String): Boolean {
        // 内容与远端一致就不提交：既省流量，也避免 Gitee 对重复创建返回 400
        val remote = getText(path)
        if (remote == text) {
            RelayLog.log("跳过写入 $path（内容未变）")
            return true
        }

        // 远端已存在时必须带 sha 走“更新”，只有确认不存在才走“新建”
        var sha = shaCache[path]
        if (sha.isNullOrEmpty() && remote != null) sha = fetchSha(path)

        repeat(2) { attempt ->
            val payload = JSONObject()
                .put("access_token", cfg.token)
                .put("content", Base64.encodeToString(text.toByteArray(Charsets.UTF_8), Base64.NO_WRAP))
                .put("message", message)
                .put("branch", cfg.branch)
            if (!sha.isNullOrEmpty()) payload.put("sha", sha)

            // Gitee：新建文件用 POST，修改已存在文件必须用 PUT
            val method = if (sha.isNullOrEmpty()) "POST" else "PUT"
            RelayLog.log(
                "写入 $path 用 $method sha=" + (sha?.take(10) ?: "无") +
                        " 内容=${text.length}字节"
            )
            val conn = open("${pathUrl(path)}?access_token=${encode(cfg.token)}").apply {
                requestMethod = method
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            val code: Int
            val body: String
            try {
                conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                code = conn.responseCode
                body = readAll(conn)
            } finally {
                conn.disconnect()
            }
            if (code in 200..299) {
                RelayLog.log("$method $path → $code")
                // 写入响应的 sha 在 content.sha（顶层没有），缓存起来省掉下一次 GET
                try {
                    val obj = JSONObject(body)
                    val shaNew = obj.optString("sha", "").ifEmpty {
                        obj.optJSONObject("content")?.optString("sha", "") ?: ""
                    }
                    if (shaNew.isNotEmpty()) shaCache[path] = shaNew
                } catch (_: Exception) {
                }
                return true
            }
            RelayLog.log("$method $path → $code ${body.take(300)}")
            if (attempt == 1 || code !in listOf(400, 409, 422)) {
                val reason = try {
                    JSONObject(body).optString("message", "")
                } catch (_: Exception) {
                    ""
                }
                throw IOException(
                    "Gitee 写入失败 HTTP $code" + if (reason.isEmpty()) "" else "：$reason"
                )
            }
            // 400/409 多为 sha 过期或文件刚被创建：重新取一次 sha 再更新
            shaCache.remove(path)
            sha = fetchSha(path)
        }
        return false
    }
}
