package com.example.timetable

import android.content.Context
import org.json.JSONObject
import java.math.BigInteger
import java.net.HttpURLConnection
import java.net.URL

/**
 * 连接调度：
 * 1. 启动时并行发起「局域网探测」和「Gitee 云同步」，谁先拿到数据用谁
 * 2. 局域网探测超时 1.2 秒，失败就落到云同步
 * 3. 云同步期间每 45 秒静默探测一次上次可用的地址，通了自动切回直连
 */
class ConnectionManager(
    private val ctx: Context,
    private val onSnapshot: (JSONObject) -> Unit,
    private val onStatus: (String, Boolean) -> Unit,
    private val onApproval: (String, String, String) -> Unit,
    private val onBindRequest: (JSONObject) -> Unit,
) {
    companion object {
        const val MODE_NONE = "none"
        const val MODE_LAN = "lan"
        const val MODE_CLOUD = "cloud"

        const val KEY_URL = "server_url"
        private const val KEY_LAST = "last_lan_url"
        private const val KEY_OWNER = "gitee_owner"
        private const val KEY_REPO = "gitee_repo"
        private const val KEY_BRANCH = "gitee_branch"
        private const val KEY_TOKEN = "gitee_token"
        private const val KEY_ANSWERED = "answered_approvals"

        private const val LAN_PROBE_TIMEOUT = 1200
        private const val LAN_RETRY_GAP = 45000L
    }

    private val prefs = ctx.getSharedPreferences("lan_config", Context.MODE_PRIVATE)
    private val lock = Any()

    @Volatile
    var mode: String = MODE_NONE
        private set

    val modeLabel: String
        get() = when (mode) {
            MODE_LAN -> "局域网"
            MODE_CLOUD -> "云同步"
            else -> ""
        }

    @Volatile private var running = false
    private var lan: LanClient? = null
    private var watcher: ApprovalWatcher? = null
    private var cloud: CloudClient? = null
    private var api: ApiClient? = null
    private var apiFails = 0
    private var lanConnected = false
    private var probeThread: Thread? = null
    private val shownApprovals = HashSet<String>()
    // 已点过“同意/拒绝”的请求：电脑端清理前不再重复弹窗（存本地，重启 App 也不重复弹）
    private val answered: MutableSet<String> =
        (prefs.getStringSet(KEY_ANSWERED, null) ?: emptySet<String>()).toMutableSet()

    private val defaultToken: String = BuildConfig.RELAY_TOKEN

    /** 手机端私钥持久化：App 重启后公钥不变，电脑端已协商的密钥继续可用。 */
    private val phonePriv: BigInteger by lazy {
        val stored = prefs.getString("relay_priv", "") ?: ""
        if (stored.length >= 32) {
            try {
                BigInteger(stored, 16)
            } catch (_: Exception) {
                RelayCrypto.randomPrivate()
            }
        } else {
            RelayCrypto.randomPrivate().also {
                prefs.edit().putString("relay_priv", it.toString(16)).apply()
            }
        }
    }

    // ---------------- 配置 ----------------
    fun cloudConfig(): CloudConfig = CloudConfig(
        owner = prefs.getString(KEY_OWNER, "lu-yuhan20140623") ?: "lu-yuhan20140623",
        repo = prefs.getString(KEY_REPO, "710") ?: "710",
        branch = prefs.getString(KEY_BRANCH, "master") ?: "master",
        token = prefs.getString(KEY_TOKEN, defaultToken) ?: defaultToken,
    )

    fun saveConfig(lanUrl: String, cfg: CloudConfig) {
        prefs.edit()
            .putString(KEY_URL, lanUrl.trim())
            .putString(KEY_OWNER, cfg.owner.trim())
            .putString(KEY_REPO, cfg.repo.trim())
            .putString(KEY_BRANCH, cfg.branch.trim().ifEmpty { "master" })
            .putString(KEY_TOKEN, cfg.token.trim().ifEmpty { defaultToken })
            .apply()
    }

    fun lanUrl(): String = prefs.getString(KEY_URL, "") ?: ""

    private fun lanCandidate(): String {
        val manual = lanUrl()
        if (manual.isNotBlank()) return manual
        return prefs.getString(KEY_LAST, "") ?: ""
    }

    // ---------------- 生命周期 ----------------
    fun start() {
        if (running) return
        running = true
        val cfg = cloudConfig()
        // 没绑定电脑时也要连官网：电脑端发起的绑定申请要在收件箱里收到
        startCloud(cfg)

        val target = lanCandidate()
        if (target.isNotBlank()) {
            Thread({
                if (probe(target) && running) {
                    switchToLan(target)
                } else if (!cfg.configured && ApiStore.activeId(ctx).isBlank() &&
                    running && mode == MODE_NONE
                ) {
                    onStatus("局域网连接失败 · 点此设置", false)
                }
            }, "lan-probe").apply { isDaemon = true; start() }
        } else if (!cfg.configured && ApiStore.activeId(ctx).isBlank()) {
            onStatus("未连接 · 点此设置电脑地址或云同步", false)
        }
        startProbeLoop()
    }

    fun restart() {
        stop()
        start()
    }

    fun stop() {
        running = false
        synchronized(lock) {
            lan?.stop(); lan = null
            watcher?.stop(); watcher = null
            cloud?.stop(); cloud = null
            api?.stop(); api = null
            lanConnected = false
            mode = MODE_NONE
        }
        probeThread = null
    }

    @Synchronized
    fun postDecision(id: String, approve: Boolean) {
        if (mode == MODE_LAN) {
            watcher?.postDecision(id, approve)
        } else {
            // 不要在这里移出 shownApprovals：电脑端还没处理完时，
            // 下一轮快照会把同一个请求又弹一次
            answered.add(id)
            persistAnswered()
            val a = api
            if (a != null) a.enqueueDecision(id, approve)
            else cloud?.enqueueDecision(id, approve)
        }
    }

    private fun persistAnswered() {
        prefs.edit().putStringSet(KEY_ANSWERED, HashSet(answered)).apply()
    }

    // ---------------- 局域网 ----------------
    private fun probe(url: String): Boolean {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL("$url/api/ping").openConnection() as HttpURLConnection).apply {
                connectTimeout = LAN_PROBE_TIMEOUT
                readTimeout = LAN_PROBE_TIMEOUT
            }
            conn.responseCode == 200
        } catch (_: Exception) {
            false
        } finally {
            conn?.disconnect()
        }
    }

    @Synchronized
    private fun switchToLan(url: String) {
        if (!running) return
        cloud?.stop()
        cloud = null
        api?.stop()
        api = null
        lan?.stop()
        watcher?.stop()
        lanConnected = false
        mode = MODE_LAN
        val base = url.trimEnd('/')

        lan = LanClient(
            onSnapshot = { json ->
                lanConnected = true
                prefs.edit().putString(KEY_LAST, base).apply()
                mode = MODE_LAN
                handleSnapshot(json)
            },
            onStatus = { text, ok ->
                onStatus(text, ok)
                if (!ok && lanConnected && running) fallbackToCloud()
            },
        ).also { it.start(base) }

        watcher = ApprovalWatcher(base) { id, title, detail ->
            onApproval(id, title, detail)
        }.also { it.start() }
    }

    // ---------------- 云同步 ----------------
    private fun startCloud(cfg: CloudConfig) {
        synchronized(lock) {
            cloud?.stop(); cloud = null
            api?.stop(); api = null
            // 官网后端是主通道；连续失败且配了 Gitee 令牌时再兜底切中继
            startApiLocked(cfg)
        }
    }

    /** 官网后端：连续失败约 1 分钟且配了 Gitee 令牌时自动切到中继兜底。 */
    private fun startApiLocked(cfg: CloudConfig) {
        mode = MODE_CLOUD
        apiFails = 0
        api = ApiClient(
            ctx,
            onSnapshot = { json -> if (mode == MODE_CLOUD) handleSnapshot(json) },
            onStatus = { text, ok ->
                if (ok) {
                    apiFails = 0
                } else {
                    apiFails++
                    if (apiFails >= 8 && cfg.configured && running) {
                        RelayLog.log("官网后端连续失败，改用 Gitee 中继")
                        synchronized(lock) {
                            api?.stop(); api = null
                            if (mode == MODE_CLOUD) startGiteeLocked(cfg)
                        }
                    }
                }
                if (mode == MODE_CLOUD) onStatus(text, ok)
            },
            onBindRequest = { item -> onBindRequest(item) },
        ).also { it.start() }
    }

    private fun startGiteeLocked(cfg: CloudConfig) {
        mode = MODE_CLOUD
        cloud = CloudClient(
            cfg = cfg,
            priv = phonePriv,
            onSnapshot = { json -> if (mode == MODE_CLOUD) handleSnapshot(json) },
            onStatus = { text, ok -> if (mode == MODE_CLOUD) onStatus(text, ok) },
        ).also { it.start() }
    }

    @Synchronized
    private fun fallbackToCloud() {
        if (!running) return
        lan?.stop(); lan = null
        watcher?.stop(); watcher = null
        lanConnected = false
        // 绑定需要官网在线，所以任何时候都回到云同步
        startCloud(cloudConfig())
    }

    private fun startProbeLoop() {
        if (probeThread != null) return
        probeThread = Thread({
            while (running) {
                try {
                    Thread.sleep(LAN_RETRY_GAP)
                } catch (_: InterruptedException) {
                    return@Thread
                }
                if (!running) return@Thread
                if (mode == MODE_LAN) continue
                val target = lanCandidate()
                if (target.isNotBlank() && probe(target)) switchToLan(target)
            }
        }, "lan-retry").apply { isDaemon = true; start() }
    }

    // ---------------- 快照与审批 ----------------
    @Synchronized
    private fun handleSnapshot(json: JSONObject) {
        val pending = HashSet<String>()
        // 局域网模式由 ApprovalWatcher 轮询，避免同一个请求弹两次
        val arr = if (mode == MODE_CLOUD) json.optJSONArray("approvals") else null
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val item = arr.optJSONObject(i) ?: continue
                val id = item.optString("id")
                if (id.isEmpty()) continue
                pending.add(id)
                if (shownApprovals.add(id) && !answered.contains(id)) {
                    onApproval(id, item.optString("title"), item.optString("detail"))
                }
            }
        }
        shownApprovals.retainAll(pending)
        if (answered.retainAll(pending)) persistAnswered()
        onSnapshot(json)
    }
}
