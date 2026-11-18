"""
密钥管理：SHA256 + 随机 salt，持久化到 password.json
- 默认密码 "710"
- 后台进程（backend_service.py）启动后按“允许读、禁止写/删/改名”的方式锁住
  password.json，防止被篡改后静默回退到默认密码
- GUI 不再直接写密码文件：修改密钥通过请求文件交给后台进程执行
"""
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

# 打包为 exe 后，数据文件放在 exe 同目录；源码运行则放在脚本目录
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
PW_FILE = APP_DIR / "password.json"
PW_REQUEST = APP_DIR / ".pwd_request.json"
PW_RESPONSE = APP_DIR / ".pwd_response.json"
DEFAULT_PASSWORD = "710"
PW_CHANGE_TIMEOUT = 6.0


def _backup_dir() -> Path:
    """备份放在用户目录，避免与安装目录里的 password.json 一起被误删。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "ClassSchedule"
    return Path.home() / ".class_schedule"


# 密码文件的可恢复副本 + “曾经初始化过”的标记（都不含明文，只有 salt/hash）
BACKUP_FILE = _backup_dir() / "password.bak.json"
INIT_MARK = _backup_dir() / "initialized.marker"

# 后台进程持有的锁定句柄（仅 backend_service.py 内有值）
_lock_fd = None
# 上次写入备份的内容，避免每次校验密码都重复落盘
_backup_text = None


class PasswordFileError(Exception):
    """密码文件损坏 / 被篡改。"""


# ---------------- 基础 ----------------
def _hash(password: str, salt: str) -> str:
    """SHA256(password + salt) 返回 hex 字符串。"""
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, data):
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _safe_unlink(path: Path):
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _create_default() -> dict:
    """首次运行：创建默认密码。仅在文件不存在、且从未初始化过时调用。"""
    salt = secrets.token_hex(16)
    data = {"salt": salt, "hash": _hash(DEFAULT_PASSWORD, salt)}
    _atomic_write_json(PW_FILE, data)
    _write_backup(json.dumps(data, ensure_ascii=False))
    return data


# ---------------- 备份 / 恢复 ----------------
def _write_backup(text: str):
    """把当前密码配置写一份到用户目录，供 password.json 被误删后恢复。"""
    global _backup_text
    if text == _backup_text:
        return
    try:
        BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BACKUP_FILE.with_name(f"{BACKUP_FILE.name}.tmp{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, BACKUP_FILE)
        if not INIT_MARK.exists():
            INIT_MARK.write_text("1", encoding="utf-8")
        _backup_text = text
    except OSError:
        pass


def _restore_from_backup():
    """password.json 缺失时尝试从备份恢复；失败返回 None。"""
    if not BACKUP_FILE.exists():
        return None
    try:
        text = BACKUP_FILE.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict) or "salt" not in data or "hash" not in data:
            return None
        _atomic_write_json(PW_FILE, data)
        return data
    except (OSError, ValueError):
        return None


def _load() -> dict:
    """读取密码配置；损坏/被篡改时抛异常，绝不静默回退默认密码。"""
    if PW_FILE.exists():
        try:
            with open(PW_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "salt" not in data or "hash" not in data:
                raise ValueError("缺少 salt/hash 字段")
        except Exception as e:
            raise PasswordFileError(f"password.json 已损坏或被篡改：{e}") from e
        # 每次成功读取都刷新备份，保证备份始终对应当前密码
        _write_backup(json.dumps(data, ensure_ascii=False))
        return data

    # 密码文件被删除：优先用备份恢复，绝不静默回退到默认密码 "710"
    restored = _restore_from_backup()
    if restored is not None:
        return restored
    if INIT_MARK.exists():
        raise PasswordFileError(
            "password.json 已被删除，备份也不可用。为防止他人绕过密钥，"
            "不会自动恢复默认密码；请用教师绑定手机号重置密钥。"
        )
    return _create_default()


# ---------------- 校验 ----------------
def verify(password: str) -> bool:
    """校验密码是否正确；文件损坏时一律不通过。"""
    if not password:
        return False
    try:
        data = _load()
    except PasswordFileError:
        return False
    return hmac.compare_digest(_hash(password, data["salt"]), data["hash"])


def is_default() -> bool:
    """当前是否还是默认密码 '710'。"""
    return verify(DEFAULT_PASSWORD)


# ---------------- 修改密钥（交给后台进程） ----------------
def change_password(old_password: str, new_password: str) -> tuple[bool, str]:
    """
    修改密码。真正的写文件动作由后台进程完成。
    返回 (成功, 消息)
    """
    if not old_password:
        return False, "请输入旧密钥"
    if not new_password:
        return False, "新密钥不能为空"
    if old_password == new_password:
        return False, "新密钥不能与旧密钥相同"
    try:
        _load()
    except PasswordFileError as e:
        return False, str(e)
    if not verify(old_password):
        return False, "旧密钥不正确"

    salt = secrets.token_hex(16)
    request = {
        "id": secrets.token_hex(8),
        "old": old_password,
        "salt": salt,
        "hash": _hash(new_password, salt),
        "time": time.time(),
    }
    _ensure_backend()
    # 后台起不来就直接返回，不要在这里空等 6 秒
    if not _backend_ready():
        return False, "后台服务未启动，密钥未修改"
    ok, msg = _send_request(request)
    return (True, "密钥已更新") if ok else (False, msg)


def reset_password_by_phone(phone: str, new_password: str) -> tuple[bool, str]:
    """忘记密钥：用教师绑定手机号验证后重置（无需验证码）。"""
    if not new_password:
        return False, "新密钥不能为空"
    try:
        import roles
    except Exception:
        return False, "身份模块不可用"
    if not roles.verify_phone(phone):
        return False, "手机号与教师绑定的号码不一致"
    try:
        _load()
    except PasswordFileError as e:
        return False, str(e)

    salt = secrets.token_hex(16)
    new_hash = _hash(new_password, salt)
    payload = {"salt": salt, "hash": new_hash}
    _ensure_backend()
    if _backend_ready():
        request = {
            "id": secrets.token_hex(8),
            "action": "reset_phone",
            "phone": (phone or "").strip(),
            "salt": salt,
            "hash": new_hash,
            "time": time.time(),
        }
        ok, msg = _send_request(request)
        return (True, "密钥已重置") if ok else (False, msg)
    try:
        _atomic_write_json(PW_FILE, payload)
        _write_backup(json.dumps(payload, ensure_ascii=False))
        return True, "密钥已重置"
    except OSError as e:
        return False, f"写入失败：{e}"


def _backend_ready() -> bool:
    """确认后台服务确实在运行（避免无意义地等响应文件）。"""
    try:
        import autostart
        return bool(autostart.is_backend_running())
    except Exception:
        return False


def _ensure_backend():
    """后台服务没跑时先拉起（改密必须由它执行）。"""
    try:
        import autostart
        if autostart.is_backend_running():
            return True
        autostart.start_backend()
        return autostart.is_backend_running()
    except Exception:
        return False


def _send_request(request: dict) -> tuple[bool, str]:
    """写请求文件并等待后台响应。"""
    _safe_unlink(PW_RESPONSE)
    try:
        _atomic_write_json(PW_REQUEST, request)
    except OSError as e:
        return False, f"无法提交改密请求：{e}"

    deadline = time.time() + PW_CHANGE_TIMEOUT
    while time.time() < deadline:
        if PW_RESPONSE.exists():
            try:
                resp = json.loads(PW_RESPONSE.read_text(encoding="utf-8"))
            except Exception:
                resp = {}
            _safe_unlink(PW_RESPONSE)
            _safe_unlink(PW_REQUEST)
            if resp.get("id") != request["id"]:
                return False, "后台响应异常，请重试"
            return bool(resp.get("ok")), resp.get("msg", "")
        time.sleep(0.05)
    _safe_unlink(PW_REQUEST)
    return False, "后台服务未运行或未响应，密钥未修改"


# ---------------- 后台进程：锁定 / 处理请求 ----------------
def is_locked() -> bool:
    return _lock_fd is not None


def lock_password_file() -> tuple[bool, str]:
    """后台进程调用：锁住 password.json（他人可读，不可写/删/改名）。"""
    global _lock_fd
    if _lock_fd is not None:
        return True, "password.json 已处于锁定状态"
    if not PW_FILE.exists():
        try:
            _load()
        except PasswordFileError as e:
            return False, str(e)
        except OSError as e:
            return False, f"创建 password.json 失败：{e}"
    try:
        if os.name == "nt":
            _lock_fd = _open_windows_locked(PW_FILE)
        else:
            fd = os.open(str(PW_FILE), os.O_RDWR)
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception:
                pass
            _lock_fd = fd
        return True, "password.json 已锁定（只读共享）"
    except Exception as e:
        _lock_fd = None
        return False, f"锁定 password.json 失败：{e}"


def unlock_password_file():
    global _lock_fd
    if _lock_fd is not None:
        try:
            os.close(_lock_fd)
        except OSError:
            pass
        _lock_fd = None


def _open_windows_locked(path: Path) -> int:
    """CreateFileW: GENERIC_READ|WRITE + 仅 FILE_SHARE_READ → 禁止他人写入/删除。"""
    import msvcrt

    generic_read = 0x80000000
    generic_write = 0x40000000
    file_share_read = 0x00000001
    open_existing = 3
    file_attribute_normal = 0x80
    invalid_handle = ctypes.c_void_p(-1).value

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    handle = k32.CreateFileW(
        str(path), generic_read | generic_write, file_share_read,
        None, open_existing, file_attribute_normal, None,
    )
    if not handle or handle == invalid_handle:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW 失败（错误码 {err}）")
    return msvcrt.open_osfhandle(handle, os.O_RDWR)


def _read_locked_text() -> str:
    """读取密码文件内容（优先走锁定句柄）。"""
    if _lock_fd is None:
        return PW_FILE.read_text(encoding="utf-8")
    os.lseek(_lock_fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        block = os.read(_lock_fd, 65536)
        if not block:
            break
        chunks.append(block)
    return b"".join(chunks).decode("utf-8")


def _write_locked_text(text: str):
    """写入密码文件内容（优先走锁定句柄）。"""
    data = text.encode("utf-8")
    if _lock_fd is None:
        tmp = PW_FILE.with_name(PW_FILE.name + f".tmp{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, PW_FILE)
    else:
        os.lseek(_lock_fd, 0, os.SEEK_SET)
        view = memoryview(data)
        while view:
            n = os.write(_lock_fd, view)
            view = view[n:]
        os.ftruncate(_lock_fd, len(data))
        os.fsync(_lock_fd)
    # 写成功后再刷新备份，保证备份与当前密码一致
    _write_backup(text)


def process_password_requests() -> bool:
    """
    后台进程调用：处理 GUI 提交的改密请求。
    返回是否处理了一条请求。
    """
    if not PW_REQUEST.exists():
        return False
    try:
        req = json.loads(PW_REQUEST.read_text(encoding="utf-8"))
    except Exception:
        _safe_unlink(PW_REQUEST)
        return False

    resp = {"id": req.get("id", ""), "ok": False, "msg": ""}
    try:
        current = json.loads(_read_locked_text())
        if req.get("action") == "reset_phone":
            import roles
            if not roles.verify_phone(str(req.get("phone", ""))):
                resp["msg"] = "手机号与教师绑定的号码不一致"
            else:
                salt = str(req.get("salt", ""))
                new_hash = str(req.get("hash", ""))
                if not salt or not new_hash:
                    resp["msg"] = "请求数据不完整"
                else:
                    _write_locked_text(json.dumps({"salt": salt, "hash": new_hash}))
                    resp["ok"] = True
                    resp["msg"] = "密钥已重置"
        else:
            old = str(req.get("old", ""))
            if not hmac.compare_digest(_hash(old, current["salt"]), current["hash"]):
                resp["msg"] = "旧密钥不正确"
            else:
                salt = str(req.get("salt", ""))
                new_hash = str(req.get("hash", ""))
                if not salt or not new_hash:
                    resp["msg"] = "请求数据不完整"
                else:
                    _write_locked_text(json.dumps({"salt": salt, "hash": new_hash}))
                    resp["ok"] = True
                    resp["msg"] = "密钥已更新"
    except Exception as e:
        resp["msg"] = f"密钥文件已损坏或被篡改：{e}"

    try:
        _atomic_write_json(PW_RESPONSE, resp)
        _safe_unlink(PW_REQUEST)
    except Exception:
        pass
    return True
