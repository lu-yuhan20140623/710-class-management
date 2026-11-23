package com.example.timetable.desktop

import java.math.BigInteger
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** 官网云端同步：沿用 Python 版的 DH + AES-256-GCM 协议，手机端无需改动。 */
object CloudService {
    private const val AAD = "class-schedule-relay-v1"
    private val prime = BigInteger(
        "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74" +
            "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14" +
            "374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406" +
            "B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A1" +
            "63BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356" +
            "208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E" +
            "462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2B" +
            "CBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FF" +
            "FFFFFFFFFFFFFF", 16,
    )
    private val generator = BigInteger.valueOf(2)
    private val keySize = (prime.bitLength() + 7) / 8
    private val secureRandom = SecureRandom()
    private val aesKeys = ConcurrentHashMap<String, SecretKeySpec>()
    private val publishedDigest = ConcurrentHashMap<String, String>()

    @Volatile
    var status: String = "未启用"

    @Volatile
    var pairedPhones: Int = 0

    private var lastPhones = 0L
    private var lastPublish = 0L
    private var lastActions = 0L
    private var lastApprovals = ""

    private fun config(): MutableMap<String, Any?> = DataStore.settings()["cloud_api"].asMutableMap().apply {
        if (str("base").isBlank()) this["base"] = "https://710-class-management.pages.dev"
        if (str("name").isBlank()) this["name"] = "Kotlin 桌面端"
    }

    private fun saveConfig(cfg: Map<String, Any?>) {
        val settings = DataStore.settings()
        settings["cloud_api"] = cfg
        DataStore.saveSettings(settings)
    }

    private fun call(
        method: String,
        path: String,
        payload: Any? = null,
        device: Map<String, Any?>? = null,
        timeout: Int = 6000,
    ): Map<String, Any?> {
        val cfg = config()
        val base = cfg.str("base").trimEnd('/')
        val connection = URL(base + path).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = timeout
        connection.readTimeout = timeout
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        connection.setRequestProperty("User-Agent", "ClassScheduleDesktopKotlin/2.0")
        device?.let {
            connection.setRequestProperty("X-Device-Id", it.str("device_id"))
            connection.setRequestProperty("Authorization", "Bearer " + it.str("secret"))
        }
        if (payload != null) {
            connection.doOutput = true
            connection.outputStream.use { out ->
                out.write(Json.stringify(payload).toByteArray(StandardCharsets.UTF_8))
            }
        }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
        connection.disconnect()
        val parsed = runCatching { Json.parse(body).asMap() }.getOrElse { emptyMap() }
        if (code !in 200..299) {
            error(parsed.str("error").ifBlank { "HTTP $code" })
        }
        return parsed
    }

    fun tick() {
        val cfg = config()
        if (!cfg.flag("enabled")) {
            status = "未启用"
            return
        }
        try {
            val deviceId = cfg.str("device_id")
            val secret = cfg.str("secret")
            if (deviceId.isBlank() || secret.isBlank()) {
                val data = call("POST", "/api/register", linkedMapOf("kind" to "pc", "name" to cfg.str("name")))
                cfg["device_id"] = data.str("deviceId")
                cfg["secret"] = data.str("secret")
                saveConfig(cfg)
                status = "已注册到官网后端，等待手机绑定"
                return
            }
            if (cfg.str("priv").isBlank()) {
                cfg["priv"] = BigInteger(256, secureRandom).setBit(0).toString(16)
                saveConfig(cfg)
                return
            }

            val device = linkedMapOf<String, Any?>(
                "device_id" to deviceId, "secret" to secret,
            )
            val now = System.currentTimeMillis()
            if (now - lastPhones >= 10_000) {
                lastPhones = now
                refreshPhones(cfg, device)
            }
            if (aesKeys.isNotEmpty()) {
                val snapshot = SnapshotBuilder.build()
                val digest = sha256(Json.stringify(snapshot))
                val approvals = Json.stringify(snapshot["approvals"] ?: emptyList<Any?>())
                if (approvals != lastApprovals || now - lastPublish >= 10_000) {
                    var uploaded = false
                    aesKeys.forEach { (phoneId, key) ->
                        if (approvals == lastApprovals && publishedDigest[phoneId] == digest) return@forEach
                        call(
                            "PUT", "/api/pc/$deviceId/snapshot/$phoneId",
                            linkedMapOf("cipher" to encrypt(key, Json.stringify(snapshot)), "version" to "2.0.0-kotlin"),
                            device,
                        )
                        publishedDigest[phoneId] = digest
                        uploaded = true
                    }
                    if (uploaded) {
                        lastPublish = now
                        lastApprovals = approvals
                    }
                }
            }
            if (now - lastActions >= 4_000) {
                lastActions = now
                pollActions(deviceId, device)
            }
            status = if (pairedPhones > 0) "已连接 · $pairedPhones 台手机" else "已注册，等待手机绑定"
        } catch (e: Exception) {
            status = "云端暂不可用：${e.message?.take(80)}"
        }
    }

    private fun refreshPhones(cfg: Map<String, Any?>, device: Map<String, Any?>) {
        val priv = BigInteger(cfg.str("priv"), 16)
        val data = call("GET", "/api/pc/${cfg.str("device_id")}/phones", device = device)
        val phones = data["phones"].asList()
        aesKeys.clear()
        phones.forEach { raw ->
            val item = raw.asMap()
            val pubHex = item.str("pub")
            if (pubHex.isBlank()) return@forEach
            val peer = runCatching { BigInteger(pubHex, 16) }.getOrNull() ?: return@forEach
            val shared = peer.modPow(priv, prime)
            aesKeys[item.str("phoneId")] = aesKey(shared)
        }
        pairedPhones = aesKeys.size
    }

    private fun pollActions(deviceId: String, device: Map<String, Any?>) {
        val data = call("GET", "/api/pc/$deviceId/actions", device = device)
        data["actions"].asList().forEach { raw ->
            val action = raw.asMap()
            val key = aesKeys[action.str("phoneId")]
            if (key != null) {
                runCatching {
                    val payload = Json.parse(decrypt(key, action.str("cipher"))).asMap()
                    payload["decisions"].asList().forEach { item ->
                        val decision = item.asMap()
                        Approvals.decide(decision.str("id"), decision.flag("approve"))
                    }
                }
            }
            runCatching { call("DELETE", "/api/pc/$deviceId/actions/${action.str("id")}", device = device) }
        }
    }

    fun bindPhone(phoneId: String): String {
        val cfg = config()
        if (cfg.str("device_id").isBlank()) return "电脑尚未注册，请稍后重试"
        if (cfg.str("priv").isBlank()) {
            cfg["priv"] = BigInteger(256, secureRandom).setBit(0).toString(16)
            saveConfig(cfg)
        }
        val priv = BigInteger(cfg.str("priv"), 16)
        val pub = generator.modPow(priv, prime).toString(16)
        val data = call(
            "POST", "/api/bind",
            linkedMapOf("phoneId" to phoneId.trim(), "pub" to pub, "replace" to false),
            cfg, 8000,
        )
        return "已发起绑定请求（${data.str("requestId").ifBlank { "等待手机确认" }}）"
    }

    private fun aesKey(shared: BigInteger): SecretKeySpec {
        val bytes = shared.toByteArray()
        val fixed = if (bytes.size == keySize) {
            bytes
        } else if (bytes.size > keySize) {
            bytes.copyOfRange(bytes.size - keySize, bytes.size)
        } else {
            ByteArray(keySize - bytes.size) + bytes
        }
        return SecretKeySpec(MessageDigest.getInstance("SHA-256").digest(fixed), "AES")
    }

    private fun encrypt(key: SecretKeySpec, text: String): String {
        val nonce = ByteArray(12).also { secureRandom.nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(128, nonce))
        cipher.updateAAD(AAD.toByteArray(StandardCharsets.UTF_8))
        val body = cipher.doFinal(text.toByteArray(StandardCharsets.UTF_8))
        return Base64.getEncoder().encodeToString(nonce + body)
    }

    private fun decrypt(key: SecretKeySpec, token: String): String {
        val raw = Base64.getDecoder().decode(token)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, raw.copyOfRange(0, 12)))
        cipher.updateAAD(AAD.toByteArray(StandardCharsets.UTF_8))
        return String(cipher.doFinal(raw.copyOfRange(12, raw.size)), StandardCharsets.UTF_8)
    }

    private fun sha256(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(StandardCharsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
}
