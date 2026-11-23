"""身份与密钥存储：教师手机号、学生密钥、值日生任命。

教师密钥仍由 auth.py（password.json + 后台锁定）管理，这里只存扩展数据：
- 教师手机号（用于重置教师密钥、学生密钥、值日生密钥）
- 学生自定义密钥（未设置时默认使用学号）
- 值日生任命（学生 + 职务 + 类型 + 专用密钥）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

ROLES_FILE = APP_DIR / "roles.json"

KIND_SCORE = "score"
KIND_HYGIENE = "hygiene"
KIND_LABELS = {KIND_SCORE: "积分管理", KIND_HYGIENE: "卫生管理"}


# ---------------- 基础 ----------------
def _hash(key: str, salt: str) -> str:
    return hashlib.sha256((key + salt).encode("utf-8")).hexdigest()


def _new_salt() -> str:
    return secrets.token_hex(16)


def _default() -> dict:
    return {"phone": "", "students": {}, "duties": []}


def _load() -> dict:
    if not ROLES_FILE.exists():
        return _default()
    try:
        data = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default()
    except Exception:
        return _default()
    data.setdefault("phone", "")
    data.setdefault("students", {})
    data.setdefault("duties", [])
    if not isinstance(data["students"], dict):
        data["students"] = {}
    if not isinstance(data["duties"], list):
        data["duties"] = []
    return data


def _save(data: dict) -> None:
    tmp = ROLES_FILE.with_name(f"{ROLES_FILE.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ROLES_FILE)


# ---------------- 教师手机号 ----------------
def get_phone() -> str:
    return str(_load().get("phone", "") or "")


def set_phone(phone: str) -> tuple[bool, str]:
    phone = (phone or "").strip()
    if phone and (not phone.isdigit() or len(phone) < 6):
        return False, "手机号格式不正确"
    data = _load()
    data["phone"] = phone
    try:
        _save(data)
    except OSError as e:
        return False, f"保存失败：{e}"
    return True, ("手机号已绑定" if phone else "已解绑手机号")


def verify_phone(phone: str) -> bool:
    saved = get_phone()
    return bool(saved) and hmac.compare_digest(saved, (phone or "").strip())


# ---------------- 学生密钥 ----------------
def student_is_custom(sid: str) -> bool:
    return str(sid) in _load()["students"]


def student_verify(sid: str, key: str) -> bool:
    sid = str(sid)
    key = str(key or "")
    if not key:
        return False
    rec = _load()["students"].get(sid)
    if not rec:
        return hmac.compare_digest(key, sid) if sid else False   # 默认密钥 = 学号
    return hmac.compare_digest(_hash(key, rec.get("salt", "")), rec.get("hash", ""))


def student_set_key(sid: str, new_key: str) -> tuple[bool, str]:
    sid = str(sid)
    if not new_key:
        return False, "新密钥不能为空"
    data = _load()
    salt = _new_salt()
    data["students"][sid] = {"salt": salt, "hash": _hash(new_key, salt)}
    try:
        _save(data)
    except OSError as e:
        return False, f"保存失败：{e}"
    return True, "学生密钥已更新"


def student_reset_with_phone(sid: str, phone: str, new_key: str) -> tuple[bool, str]:
    if not verify_phone(phone):
        return False, "手机号与教师绑定的号码不一致"
    return student_set_key(sid, new_key)


def rename_student(old_sid: str, new_sid: str) -> tuple[bool, str]:
    """学号变更时迁移自定义密钥与值日生任命，避免登录身份丢失。"""
    old, new = str(old_sid), str(new_sid)
    if not old or not new or old == new:
        return True, "无需迁移"
    data = _load()
    students = data.setdefault("students", {})
    if new in students:
        return False, "新学号已有自定义密钥，无法迁移"
    if old in students:
        students[new] = students.pop(old)
    for duty in data.get("duties", []):
        if str(duty.get("sid")) == old:
            duty["sid"] = new
    try:
        _save(data)
    except OSError as e:
        return False, f"保存失败：{e}"
    return True, "已迁移学生密钥与值日生任命"


# ---------------- 值日生任命 ----------------
def duties() -> list[dict]:
    return list(_load()["duties"])


def duties_for(sid: str) -> list[dict]:
    return [d for d in duties() if str(d.get("sid")) == str(sid)]


def add_duty(sid: str, name: str, role: str, kind: str,
             key: str = "") -> tuple[bool, str, dict | None]:
    sid, name, role = str(sid).strip(), name.strip(), role.strip()
    if not sid or not name or not role:
        return False, "学号、姓名、职务都不能为空", None
    if kind not in KIND_LABELS:
        return False, "职务类型不正确", None
    key = (key or "").strip() or "".join(secrets.choice("0123456789") for _ in range(6))
    data = _load()
    for d in data["duties"]:
        if str(d.get("sid")) == sid and d.get("role") == role:
            return False, f"{name} 已经是「{role}」，请勿重复任命", None
    salt = _new_salt()
    duty = {
        "id": secrets.token_hex(6),
        "sid": sid,
        "name": name,
        "role": role,
        "kind": kind,
        "salt": salt,
        "hash": _hash(key, salt),
        "created": time.time(),
    }
    data["duties"].append(duty)
    try:
        _save(data)
    except OSError as e:
        return False, f"保存失败：{e}", None
    return True, f"已任命 {name} 为「{role}」，专用密钥：{key}", dict(duty, plain_key=key)


def remove_duty(duty_id: str) -> tuple[bool, str]:
    data = _load()
    before = len(data["duties"])
    data["duties"] = [d for d in data["duties"] if d.get("id") != duty_id]
    if len(data["duties"]) == before:
        return False, "未找到该任命"
    try:
        _save(data)
    except OSError as e:
        return False, f"保存失败：{e}"
    return True, "任命已撤销"


def find_duty(duty_id: str) -> dict | None:
    return next((d for d in duties() if d.get("id") == duty_id), None)


def duty_verify(duty: dict, key: str) -> bool:
    key = str(key or "")
    if not duty or not key:
        return False
    return hmac.compare_digest(_hash(key, duty.get("salt", "")),
                               duty.get("hash", ""))


def duty_set_key(duty_id: str, new_key: str) -> tuple[bool, str]:
    if not new_key:
        return False, "新密钥不能为空"
    data = _load()
    duty = next((d for d in data["duties"] if d.get("id") == duty_id), None)
    if not duty:
        return False, "未找到该任命"
    salt = _new_salt()
    duty["salt"] = salt
    duty["hash"] = _hash(new_key, salt)
    try:
        _save(data)
    except OSError as e:
        return False, f"保存失败：{e}"
    return True, "值日生密钥已更新"


def duty_reset_with_phone(duty_id: str, phone: str, new_key: str) -> tuple[bool, str]:
    if not verify_phone(phone):
        return False, "手机号与教师绑定的号码不一致"
    return duty_set_key(duty_id, new_key)


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)
