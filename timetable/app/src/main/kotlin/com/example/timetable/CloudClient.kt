package com.example.timetable

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger

/**
 * Gitee 云端中继客户端：
 * 每 8 秒拉取一次加密快照，解密后交给界面；确认结果加密后回写。
 * 所有网络请求都在独立线程，回调切回主线程。
 */
class CloudClient(
    private val cfg: CloudConfig,
    private val priv: BigInteger,
    private val onSnapshot: (JSONObject) -> Unit,
    private val onStatus: (String, Boolean) -> Unit,
) {
    companion object {
        const val PC_PUB = "relay/pc_pub.json"
        const val PHONE_PUB = "relay/phone_pub.json"
        const val STATE = "relay/state.enc"
        const val ACTIONS = "relay/phone.enc"
        private const val POLL_MS = 8000L
    }

    private val handler = Handler(Looper.getMainLooper())
    private var running = false
    private var thread: Thread? = null

    private var key: javax.crypto.spec.SecretKeySpec? = null
    private var peerA: String = ""
    private var phonePubUploaded = ""
    private var lastStatus = ""
    private val pendingDecisions = ArrayList<JSONObject>()
    private var decisionsDirty = false

    fun start() {
        if (running) return
        running = true
        RelayLog.log(
            "云同步启动 ${cfg.label} 分支=${cfg.branch} " +
                    "令牌长度=${cfg.token.length} 私钥位数=${priv.bitLength()}"
        )
        thread = Thread({ loop() }, "cloud-relay").apply {
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
            decisionsDirty = true
        }
        // 立刻唤醒轮询线程，别让“同意”等满 8 秒
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
            try {
                tick()
            } catch (e: Exception) {
                val msg = "云同步异常：${e.message ?: e.javaClass.simpleName}"
                RelayLog.log("异常：${e.javaClass.simpleName} ${e.message ?: ""}")
                status(msg, false)
            }
            val spent = System.currentTimeMillis() - started
            val wait = (POLL_MS - spent).coerceAtLeast(1500)
            try {
                Thread.sleep(wait)
            } catch (_: InterruptedException) {
                // 被 enqueueDecision 唤醒：马上回传确认结果
            }
        }
    }

    private fun tick() {
        val repo = GiteeClient(cfg)

        // 1) 取电脑公钥，用模幂算出共享密钥
        val pubText = repo.getText(PC_PUB)
        if (pubText.isNullOrBlank()) {
            status("云同步 · 等待电脑端…", false)
            return
        }
        val pub = JSONObject(pubText)
        val p = BigInteger(pub.getString("p"), 16)
        val aHex = pub.getString("A")
        if (key == null || aHex != peerA) {
            key = RelayCrypto.deriveKey(BigInteger(aHex, 16), priv, p)
            peerA = aHex
            status("云同步 · 已配对", true)
        }

        // 2) 上传手机公钥（只传一次）
        val bHex = RelayCrypto.publicValue(priv, p).toString(16)
        if (phonePubUploaded != bHex) {
            val body = JSONObject()
                .put("v", 1)
                .put("B", bHex)
                .put("ts", System.currentTimeMillis() / 1000)
                .toString()
            repo.putText(PHONE_PUB, body, "relay: phone public key")
            phonePubUploaded = bHex
        }

        // 3) 拉取并解密快照
        val state = repo.getText(STATE)
        if (!state.isNullOrBlank()) {
            try {
                val json = JSONObject(RelayCrypto.decrypt(key!!, state))
                if (running) handler.post { onSnapshot(json) }
                status("云同步 · 已连接", true)
            } catch (_: Exception) {
                // 电脑端刚重启、密钥还没同步过来：下一轮重新协商即可
                key = null
                peerA = ""
                status("云同步 · 等待电脑端刷新…", false)
            }
        } else {
            status("云同步 · 等待电脑端上传…", false)
        }

        // 4) 回传确认结果
        flushDecisions(repo)
    }

    private fun flushDecisions(repo: GiteeClient) {
        val k = key ?: return
        val list: List<JSONObject>
        synchronized(pendingDecisions) {
            if (!decisionsDirty || pendingDecisions.isEmpty()) return
            list = ArrayList(pendingDecisions)
        }
        val payload = JSONObject()
            .put("ts", System.currentTimeMillis() / 1000)
            .put("decisions", JSONArray(list))
        // 与快照同一套加密：电脑端会用共享密钥解密，明文会被当成损坏数据
        repo.putText(ACTIONS, RelayCrypto.encrypt(k, payload.toString()),
            "relay: phone decisions")
        synchronized(pendingDecisions) {
            // 只清掉这次已上传的，上传期间新点的继续留着
            pendingDecisions.removeAll(list)
            decisionsDirty = pendingDecisions.isNotEmpty()
        }
        RelayLog.log("已回传确认结果 ${list.size} 条")
    }
}
