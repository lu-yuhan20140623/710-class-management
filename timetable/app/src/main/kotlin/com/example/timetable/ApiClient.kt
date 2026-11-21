package com.example.timetable

import android.content.Context
import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger
import java.net.HttpURLConnection
import java.net.URL

/** 已绑定的一台电脑：id 是电脑端设备 ID，pub 是电脑端公钥。 */
data class BoundPc(val id: String, val name: String, val pub: String)

/** 官网后端的本地存储：设备身份、服务器地址、已绑定电脑列表。 */
object ApiStore {
    const val DEFAULT_BASE = "https://710-class-management.pages.dev"
    // 旧默认站点：已换成 Cloudflare Pages，老配置自动沿用新默认
    private const val LEGACY_BASE = "https://classmanagement.de5.net"
    private const val PREFS = "lan_config"

    private fun prefs(ctx: Context) =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun base(ctx: Context): String {
        val stored = (prefs(ctx).getString("api_base", "") ?: "").trim().trimEnd('/')
        if (stored.isBlank() || stored == LEGACY_BASE) return DEFAULT_BASE
        return stored
    }

    fun setBase(ctx: Context, value: String) {
        prefs(ctx).edit().putString("api_base", value.trim().trimEnd('/')).apply()
    }

    fun deviceId(ctx: Context): String =
        prefs(ctx).getString("api_device_id", "") ?: ""

    fun secret(ctx: Context): String =
        prefs(ctx).getString("api_secret", "") ?: ""

    fun saveDevice(ctx: Context, id: String, secret: String) {
        prefs(ctx).edit().putString("api_device_id", id)
            .putString("api_secret", secret).apply()
    }

    fun clearDevice(ctx: Context) {
        prefs(ctx).edit().remove("api_device_id").remove("api_secret").apply()
    }

    /** 手机端私钥：App 重启后不变，已派生的会话密钥继续可用。 */
    fun priv(ctx: Context): BigInteger {
        val stored = prefs(ctx).getString("api_priv", "") ?: ""
        if (stored.length >= 32) {
            try {
                return BigInteger(stored, 16)
            } catch (_: Exception) {
            }
        }
        return RelayCrypto.randomPrivate().also {
            prefs(ctx).edit().putString("api_priv", it.toString(16)).apply()
        }
    }

    fun pcs(ctx: Context): List<BoundPc> {
        val raw = prefs(ctx).getString("api_pcs", "[]") ?: "[]"
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                val id = o.optString("id")
                if (id.isBlank()) null
                else BoundPc(id, o.optString("name"), o.optString("pub"))
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun savePcs(ctx: Context, list: List<BoundPc>) {
        val arr = JSONArray()
        list.forEach {
            arr.put(JSONObject().put("id", it.id).put("name", it.name).put("pub", it.pub))
        }
        prefs(ctx).edit().putString("api_pcs", arr.toString()).apply()
    }

    fun upsertPc(ctx: Context, pc: BoundPc) {
        val list = pcs(ctx).filterNot { it.id == pc.id } + pc
        savePcs(ctx, list)
    }

    fun removePc(ctx: Context, id: String) {
        savePcs(ctx, pcs(ctx).filterNot { it.id == id })
        if (activeId(ctx) == id) setActive(ctx, pcs(ctx).firstOrNull()?.id ?: "")
    }

    fun find(ctx: Context, id: String): BoundPc? = pcs(ctx).firstOrNull { it.id == id }

    fun activeId(ctx: Context): String =
        prefs(ctx).getString("api_active_pc", "") ?: ""

    fun setActive(ctx: Context, id: String) {
        prefs(ctx).edit().putString("api_active_pc", id).apply()
    }
}

/**
 * 官网后端客户端（替代 Gitee 中继）：
 * 每 8 秒拉一次自己那份加密快照，确认结果加密后回传。
 */
class ApiClient(
    private val ctx: Context,
    private val onSnapshot: (JSONObject) -> Unit,
    private val onStatus: (String, Boolean) -> Unit,
    private val onBindRequest: (JSONObject) -> Unit,
) {
    companion object {
        // RFC 3526 group 14，与电脑端 cloud_relay.py 的 P 完全一致
        val P: BigInteger = BigInteger(
            "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74" +
                    "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14" +
                    "374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406" +
                    "B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A1" +
                    "63BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356" +
                    "208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E" +
                    "462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2B" +
                    "CBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FF" +
                    "FFFFFFFFFFFFFF", 16)

        // 上一次请求一结束就发下一次，只留极小间隔；失败才退避
        private const val IDLE_GAP_MS = 600L
        private const val ERROR_GAP_MS = 5000L

        class HttpError(val code: Int, message: String) : Exception(message)

        fun request(
            ctx: Context, method: String, path: String,
            body: JSONObject? = null, auth: Boolean = true,
        ): JSONObject {
            val conn = (URL(ApiStore.base(ctx) + path).openConnection() as HttpURLConnection)
            try {
                conn.requestMethod = method
                conn.connectTimeout = 6000
                conn.readTimeout = 8000
                if (auth) {
                    conn.setRequestProperty("X-Device-Id", ApiStore.deviceId(ctx))
                    conn.setRequestProperty("Authorization", "Bearer " + ApiStore.secret(ctx))
                }
                if (body != null) {
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/json")
                    conn.outputStream.use { it.write(body.toString().toByteArray()) }
                }
                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
                val json = if (text.isBlank()) JSONObject() else JSONObject(text)
                if (code !in 200..299) {
                    throw HttpError(code, json.optString("error", "HTTP $code"))
                }
                return json
            } finally {
                conn.disconnect()
            }
        }

        /**
         * 收件箱：电脑端输入本机设备 ID 发起绑定后，申请会出现在这里；
         * 由用户在手机上点「同意」后才真正绑定。
         */
        fun inbox(ctx: Context): JSONArray {
            ensureDevice(ctx)
            return request(ctx, "GET", "/api/pair/inbox")
                .optJSONArray("requests") ?: JSONArray()
        }

        /** 同意/拒绝某次绑定；同意时带上本机公钥，电脑端靠它派生会话密钥。 */
        fun decide(ctx: Context, requestId: String, approve: Boolean): JSONObject {
            ensureDevice(ctx)
            val body = JSONObject().put("approve", approve)
            if (approve) {
                body.put("pub", RelayCrypto.publicValue(ApiStore.priv(ctx), P).toString(16))
            }
            return request(ctx, "POST", "/api/pair/inbox/$requestId/decide", body)
        }

        private fun ensureDevice(ctx: Context) {
            if (ApiStore.deviceId(ctx).isNotBlank() && ApiStore.secret(ctx).isNotBlank()) return
            val res = request(
                ctx, "POST", "/api/register",
                JSONObject().put("kind", "phone").put("name", android.os.Build.MODEL),
                auth = false,
            )
            ApiStore.saveDevice(ctx, res.getString("deviceId"), res.getString("secret"))
            RelayLog.log("官网云端：手机端已注册")
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var running = false
    private var thread: Thread? = null
    private var lastStatus = ""
    private val pendingDecisions = ArrayList<JSONObject>()
    // 已经弹过窗的绑定申请：手机没点之前不重复弹
    private val shownRequests = HashSet<String>()

    fun start() {
        if (running) return
        running = true
        RelayLog.log("官网云端启动：${ApiStore.base(ctx)} / ${ApiStore.activeId(ctx).take(8)}")
        thread = Thread({ loop() }, "api-cloud").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running = false
        thread = null
    }

    fun enqueueDecision(id: String, approve: Boolean) {
        synchronized(pendingDecisions) {
            pendingDecisions.add(JSONObject().put("id", id).put("approve", approve))
        }
        thread?.interrupt()
    }

    private fun status(text: String, ok: Boolean) {
        if (!running) return
        if (text != lastStatus) {
            lastStatus = text
            RelayLog.log("状态：$text")
        }
        handler.post { onStatus(text, ok) }
    }

    private fun loop() {
        while (running) {
            val started = System.currentTimeMillis()
            var ok = true
            try {
                pollInbox()
                tick()
            } catch (e: HttpError) {
                ok = false
                when (e.code) {
                    403 -> {
                        ApiStore.setActive(ctx, "")
                        status("已被电脑端解绑，等待重新绑定", true)
                    }
                    401 -> {
                        ApiStore.clearDevice(ctx)
                        status("云端身份失效，正在重新注册…", false)
                    }
                    else -> status("官网云端异常：${e.message}", false)
                }
            } catch (e: Exception) {
                ok = false
                status("官网云端不可达：${e.message ?: e.javaClass.simpleName}", false)
            }
            // 请求完成即进入下一轮，不再固定等 8 秒
            val spent = System.currentTimeMillis() - started
            val gap = if (ok) IDLE_GAP_MS else ERROR_GAP_MS
            try {
                Thread.sleep((gap - spent).coerceAtLeast(0))
            } catch (_: InterruptedException) {
            }
        }
    }

    /** 轮询绑定收件箱：电脑端发起后在这里弹窗确认。 */
    private fun pollInbox() {
        val arr = inbox(ctx)
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            val rid = item.optString("requestId")
            if (rid.isEmpty()) continue
            val fresh = synchronized(shownRequests) { shownRequests.add(rid) }
            if (!fresh) continue
            handler.post { if (running) onBindRequest(item) }
        }
    }

    private fun tick() {
        val pcId = ApiStore.activeId(ctx)
        if (pcId.isBlank()) {
            status("官网云端在线 · 等待电脑端绑定", true)
            return
        }
        val pc = ApiStore.find(ctx, pcId)
        if (pc == null || pc.pub.isBlank()) {
            status("官网云端在线 · 需要重新绑定电脑", true)
            return
        }
        ensureDevice(ctx)

        val k = RelayCrypto.deriveKey(
            BigInteger(pc.pub, 16), ApiStore.priv(ctx), P
        )

        val res = request(ctx, "GET", "/api/pc/$pcId/snapshot")
        if (res.optBoolean("exists")) {
            try {
                val json = JSONObject(RelayCrypto.decrypt(k, res.getString("cipher")))
                if (running) handler.post { onSnapshot(json) }
                status("官网云端 · 已连接", true)
            } catch (_: Exception) {
                status("官网云端 · 等待电脑端刷新…", false)
            }
        } else {
            status("官网云端 · 等待电脑上传…", false)
        }

        flushDecisions(pcId, k)
    }

    private fun flushDecisions(pcId: String, k: javax.crypto.spec.SecretKeySpec) {
        val list = synchronized(pendingDecisions) {
            if (pendingDecisions.isEmpty()) return
            ArrayList(pendingDecisions)
        }
        val payload = JSONObject()
            .put("ts", System.currentTimeMillis() / 1000)
            .put("decisions", JSONArray(list))
        request(
            ctx, "POST", "/api/pc/$pcId/actions",
            JSONObject().put("cipher", RelayCrypto.encrypt(k, payload.toString())),
        )
        synchronized(pendingDecisions) { pendingDecisions.removeAll(list) }
        RelayLog.log("已回传确认结果 ${list.size} 条")
    }
}
