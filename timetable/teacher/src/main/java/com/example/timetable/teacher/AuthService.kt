package com.example.timetable.teacher

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom

/** 教师密钥：SHA256(密钥 + salt)，与 Python auth.py 完全一致。 */
object AuthService {
    private const val DEFAULT_PASSWORD = "710"
    private val random = SecureRandom()

    fun hash(password: String, salt: String): String {
        val bytes = (password + salt).toByteArray(StandardCharsets.UTF_8)
        return MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }

    fun newSalt(): String {
        val bytes = ByteArray(16).also { random.nextBytes(it) }
        return bytes.joinToString("") { "%02x".format(it) }
    }

    fun verify(password: String): Boolean {
        if (password.isEmpty()) return false
        val data = DataStore.loadMap("password.json")
        val salt = data.str("salt")
        val hash = data.str("hash")
        if (salt.isBlank() || hash.isBlank()) return false
        return constantEquals(hash(password, salt), hash)
    }

    fun isDefault(): Boolean = verify(DEFAULT_PASSWORD)

    fun change(old: String, new: String): Pair<Boolean, String> {
        if (old.isBlank()) return false to "请输入旧密钥"
        if (new.isBlank()) return false to "新密钥不能为空"
        if (old == new) return false to "新密钥不能与旧密钥相同"
        if (!verify(old)) return false to "旧密钥不正确"
        val salt = newSalt()
        DataStore.save("password.json", linkedMapOf<String, Any?>("salt" to salt, "hash" to hash(new, salt)))
        return true to "教师密钥已更新"
    }

    fun applyReset(salt: String, hash: String) {
        DataStore.save("password.json", linkedMapOf<String, Any?>("salt" to salt, "hash" to hash))
    }

    fun constantEquals(a: String, b: String): Boolean =
        MessageDigest.isEqual(a.toByteArray(StandardCharsets.UTF_8), b.toByteArray(StandardCharsets.UTF_8))
}

/** roles.json：教师手机号、学生密钥、值日生任命。 */
object RolesService {
    const val KIND_SCORE = "score"
    const val KIND_HYGIENE = "hygiene"

    private fun data(): MutableMap<String, Any?> {
        val map = DataStore.loadMap("roles.json")
        if (map["phone"] == null) map["phone"] = ""
        if (map["students"] == null) map["students"] = linkedMapOf<String, Any?>()
        if (map["duties"] == null) map["duties"] = mutableListOf<Any?>()
        return map
    }

    private fun save(map: Map<String, Any?>) = DataStore.save("roles.json", map)

    fun phone(): String = data().str("phone")

    fun verifyPhone(phone: String): Boolean {
        val saved = phone()
        return saved.isNotBlank() && AuthService.constantEquals(saved, phone.trim())
    }

    fun setPhone(phone: String): Pair<Boolean, String> {
        val value = phone.trim()
        if (value.isNotBlank() && (!value.all { it.isDigit() } || value.length < 6)) {
            return false to "手机号格式不正确"
        }
        val map = data()
        map["phone"] = value
        save(map)
        return true to if (value.isBlank()) "已解绑手机号" else "手机号已绑定"
    }

    private fun studentRecords(): MutableMap<String, Any?> = data()["students"].asMutableMap()

    fun studentVerify(sid: String, key: String): Boolean {
        if (key.isBlank()) return false
        val rec = studentRecords()[sid].asMap()
        if (rec.isEmpty()) return AuthService.constantEquals(key, sid)
        return AuthService.constantEquals(
            AuthService.hash(key, rec.str("salt")), rec.str("hash"),
        )
    }

    fun studentSetKey(sid: String, newKey: String): Pair<Boolean, String> {
        if (newKey.isBlank()) return false to "新密钥不能为空"
        val map = data()
        val students = map["students"].asMutableMap()
        val salt = AuthService.newSalt()
        students[sid] = linkedMapOf<String, Any?>("salt" to salt, "hash" to AuthService.hash(newKey, salt))
        map["students"] = students
        save(map)
        return true to "学生密钥已更新"
    }

    @Suppress("UNCHECKED_CAST")
    fun duties(): List<Map<String, Any?>> = data()["duties"].asList().mapNotNull { it as? Map<*, *> }.map { it as Map<String, Any?> }

    fun dutiesFor(sid: String): List<Map<String, Any?>> = duties().filter { it.str("sid") == sid }

    fun dutyVerify(duty: Map<String, Any?>, key: String): Boolean {
        if (key.isBlank()) return false
        return AuthService.constantEquals(
            AuthService.hash(key, duty.str("salt")), duty.str("hash"),
        )
    }

    fun duty(id: String): Map<String, Any?>? = duties().firstOrNull { it.str("id") == id }

    fun dutySetKey(id: String, newKey: String): Pair<Boolean, String> {
        if (newKey.isBlank()) return false to "新密钥不能为空"
        val map = data()
        val list = map["duties"].asMutableList()
        var changed = false
        for (i in list.indices) {
            val duty = list[i].asMutableMap()
            if (duty.str("id") != id) continue
            val salt = AuthService.newSalt()
            duty["salt"] = salt
            duty["hash"] = AuthService.hash(newKey, salt)
            list[i] = duty
            changed = true
            break
        }
        if (!changed) return false to "未找到该任命"
        map["duties"] = list
        save(map)
        return true to "专用密钥已更新"
    }

    fun addDuty(sid: String, name: String, role: String, kind: String, key: String = ""): Triple<Boolean, String, Map<String, Any?>?> {
        if (sid.isBlank() || name.isBlank() || role.isBlank()) return Triple(false, "学号、姓名、职务都不能为空", null)
        if (kind != KIND_SCORE && kind != KIND_HYGIENE) return Triple(false, "职务类型不正确", null)
        val plain = key.ifBlank { (1..6).map { ('0'..'9').random() }.joinToString("") }
        val map = data()
        val list = map["duties"].asMutableList()
        if (list.any { it.asMap().str("sid") == sid && it.asMap().str("role") == role }) {
            return Triple(false, "$name 已经是「$role」，请勿重复任命", null)
        }
        val salt = AuthService.newSalt()
        val duty = linkedMapOf<String, Any?>(
            "id" to (1..12).map { "0123456789abcdef".random() }.joinToString(""),
            "sid" to sid, "name" to name, "role" to role, "kind" to kind,
            "salt" to salt, "hash" to AuthService.hash(plain, salt),
            "created" to System.currentTimeMillis() / 1000.0,
        )
        list.add(duty)
        map["duties"] = list
        save(map)
        return Triple(true, "已任命 $name 为「$role」，专用密钥：$plain", duty)
    }

    fun removeDuty(id: String): Pair<Boolean, String> {
        val map = data()
        val list = map["duties"].asMutableList()
        val before = list.size
        val result = list.removeAll { it.asMap().str("id") == id }
        if (!result || list.size == before) return false to "未找到该任命"
        map["duties"] = list
        save(map)
        return true to "任命已撤销"
    }

    fun applyStudentReset(sid: String, salt: String, hash: String) {
        val map = data()
        val students = map["students"].asMutableMap()
        students[sid] = linkedMapOf<String, Any?>("salt" to salt, "hash" to hash)
        map["students"] = students
        save(map)
    }

    fun applyDutyReset(id: String, salt: String, hash: String) {
        val map = data()
        val list = map["duties"].asMutableList()
        for (i in list.indices) {
            val duty = list[i].asMutableMap()
            if (duty.str("id") != id) continue
            duty["salt"] = salt
            duty["hash"] = hash
            list[i] = duty
            break
        }
        map["duties"] = list
        save(map)
    }
}

/** 手机确认后生效的密钥重置请求。 */
object KeyResetService {
    fun submit(kind: String, target: String, title: String, detail: String, newKey: String): Pair<Boolean, String> {
        val salt = AuthService.newSalt()
        val hash = AuthService.hash(newKey, salt)
        val approval = Approvals.submit("reset", title, detail)
        val id = approval.str("id")
        val pending = DataStore.loadMap("pending_resets.json")
        pending[id] = linkedMapOf<String, Any?>(
            "kind" to kind, "target" to target, "salt" to salt, "hash" to hash,
        )
        DataStore.save("pending_resets.json", pending)
        return true to id
    }

    fun status(id: String): String = Approvals.status(id)

    fun apply(id: String): Pair<Boolean, String> {
        if (Approvals.status(id) != "approved") return false to "手机尚未确认"
        val pending = DataStore.loadMap("pending_resets.json")
        val item = pending[id].asMap()
        if (item.isEmpty()) return false to "重置请求已失效"
        when (item.str("kind")) {
            "teacher" -> AuthService.applyReset(item.str("salt"), item.str("hash"))
            "student" -> RolesService.applyStudentReset(item.str("target"), item.str("salt"), item.str("hash"))
            "duty" -> RolesService.applyDutyReset(item.str("target"), item.str("salt"), item.str("hash"))
            else -> return false to "未知的重置类型"
        }
        pending.remove(id)
        DataStore.save("pending_resets.json", pending)
        return true to "密钥已重置"
    }
}
