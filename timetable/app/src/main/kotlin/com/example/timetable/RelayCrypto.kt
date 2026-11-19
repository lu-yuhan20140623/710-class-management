package com.example.timetable

import android.util.Base64
import java.math.BigInteger
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 与电脑端 cloud_relay.py 对应的加解密：
 * - 模幂（Diffie-Hellman）协商共享值，再 SHA-256 派生 AES-256 密钥
 * - 数据用 AES/GCM 加密，格式为 base64(nonce[12] + 密文 + tag)
 */
object RelayCrypto {
    private val G = BigInteger.valueOf(2)
    private const val MOD_BYTES = 256
    private val AAD = "class-schedule-relay-v1".toByteArray(Charsets.UTF_8)
    private const val GCM_TAG_BITS = 128

    fun randomPrivate(): BigInteger {
        val buf = ByteArray(32)
        SecureRandom().nextBytes(buf)
        return BigInteger(1, buf).or(BigInteger.ONE)
    }

    fun publicValue(priv: BigInteger, p: BigInteger): BigInteger =
        G.modPow(priv, p)

    fun deriveKey(peerPublic: BigInteger, priv: BigInteger, p: BigInteger): SecretKeySpec {
        val shared = peerPublic.modPow(priv, p)
        val digest = MessageDigest.getInstance("SHA-256").digest(fixedBytes(shared))
        return SecretKeySpec(digest, "AES")
    }

    /** 与 Python 的 int.to_bytes(256, "big") 保持一致。 */
    private fun fixedBytes(value: BigInteger): ByteArray {
        val raw = value.toByteArray()
        val out = ByteArray(MOD_BYTES)
        if (raw.size >= MOD_BYTES) {
            System.arraycopy(raw, raw.size - MOD_BYTES, out, 0, MOD_BYTES)
        } else {
            System.arraycopy(raw, 0, out, MOD_BYTES - raw.size, raw.size)
        }
        return out
    }

    fun encrypt(key: SecretKeySpec, text: String): String {
        val nonce = ByteArray(12).also { SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, nonce))
        cipher.updateAAD(AAD)
        val body = cipher.doFinal(text.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(nonce + body, Base64.NO_WRAP)
    }

    fun decrypt(key: SecretKeySpec, token: String): String {
        val raw = Base64.decode(token, Base64.DEFAULT)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, raw, 0, 12))
        cipher.updateAAD(AAD)
        return String(cipher.doFinal(raw, 12, raw.size - 12), Charsets.UTF_8)
    }
}
