"""官网后端同步：电脑与手机通过 710-class-management.pages.dev 交换加密数据。

链路：
    电脑 --(AES-GCM 加密快照)--> Netlify Functions + Blobs --(手机每 8 秒拉取)--> 手机
    手机 --(加密的确认/拒绝)--> 后端 --(电脑每 4 秒拉取)--> 电脑

和 cloud_relay.py 的区别：不再走 Gitee 的 Contents API（有频率限制），
但沿用同一套模幂（Diffie-Hellman）+ AES-256-GCM 密钥协商，服务端只存密文。

官网后端不可达时由本模块拉起 cloud_relay.py 作为备用通道。
"""

import json
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

import lan_server
import cloud_relay
from cloud_relay import (
    _aes_key, _digest, _public_value, _shared_secret,
    decrypt_text, encrypt_text,
)

try:
    from version import VERSION
except Exception:                                    # pragma: no cover
    VERSION = ""

BASE_DEFAULT = "https://710-class-management.pages.dev"
# 旧默认站点：仍可用，但配置里留着它就自动换成新默认（Cloudflare Pages 更快）
LEGACY_BASES = {"https://classmanagement.de5.net"}
SETTINGS_FILE = cloud_relay.SETTINGS_FILE
STATUS_FILE = cloud_relay.APP_DIR / "cloud_status.json"

TICK = 2.0
ACTIONS_POLL_GAP = 4.0
PHONES_REFRESH_GAP = 10.0
PUBLISH_MIN_GAP = 10.0
RELAY_FALLBACK_AFTER = 20.0

UA = f"ClassSchedulePC/{VERSION or '2.2.2'}"

_lock = threading.RLock()
_service = None


class ApiUnreachable(Exception):
    """网络/证书/超时：换用 Gitee 中继兜底。"""


class ApiError(Exception):
    """后端明确返回了错误（code 为 HTTP 状态码，0 表示响应无法解析）。"""

    def __init__(self, message, code: int = 0):
        super().__init__(message)
        self.code = code


# ===================== 配置 =====================
def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _default_name() -> str:
    try:
        return socket.gethostname()[:24] or "教师电脑"
    except Exception:
        return "教师电脑"


def config() -> dict:
    data = _load_json(SETTINGS_FILE, {}) or {}
    raw = data.get("cloud_api") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    base = str(raw.get("base") or "").strip().rstrip("/")
    if not base or base in LEGACY_BASES:
        if raw.get("base"):
            # 老配置里的旧站点地址一次性迁到新默认（直接写文件，避免 config 递归）
            raw["base"] = BASE_DEFAULT
            data["cloud_api"] = raw
            try:
                _save_json(SETTINGS_FILE, data)
            except OSError:
                pass
        base = BASE_DEFAULT
    return {
        "enabled": bool(raw.get("enabled", True)),
        "base": base,
        "name": str(raw.get("name") or _default_name()).strip(),
        "device_id": str(raw.get("device_id") or "").strip(),
        "secret": str(raw.get("secret") or "").strip(),
        "priv": str(raw.get("priv") or "").strip(),
    }


def save_config(**kwargs):
    data = _load_json(SETTINGS_FILE, {}) or {}
    if not isinstance(data, dict):
        data = {}
    current = config()
    current.update({k: v for k, v in kwargs.items() if v is not None})
    data["cloud_api"] = current
    _save_json(SETTINGS_FILE, data)


# ===================== HTTP =====================
def _call(method: str, base: str, path: str, payload=None,
          device=None, timeout: float = 6.0) -> dict:
    data = None
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if device:
        headers["X-Device-Id"] = device["device_id"]
        headers["Authorization"] = "Bearer " + device["secret"]
    req = urllib.request.Request(base + path, data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        raise ApiError(body.get("error") or f"HTTP {e.code}", e.code)
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        raise ApiUnreachable(f"{type(e).__name__}: {e}")
    except ValueError as e:
        raise ApiError(f"响应不是合法 JSON: {e}")


# ===================== 由电脑端发起绑定 =====================
def _pc_device() -> dict:
    cfg = config()
    if not (cfg["device_id"] and cfg["secret"]):
        raise ApiError("本机尚未注册，请稍后再试")
    return cfg


def bind_phone(phone_id: str, replace: bool = False) -> dict:
    """电脑端输入手机设备 ID 发起绑定；手机确认后才生效。"""
    cfg = _pc_device()
    if not cfg["priv"]:
        save_config(priv=format(secrets.randbits(256) | 1, "x"))
        cfg = config()
    payload = {
        "phoneId": phone_id.strip(),
        "pub": format(_public_value(int(cfg["priv"], 16)), "x"),
        "replace": bool(replace),
    }
    return _call("POST", cfg["base"], "/api/bind", payload,
                 device=cfg, timeout=8.0)


def bind_status(phone_id: str, request_id: str) -> dict:
    """查这次绑定手机有没有确认（pending / approved / denied / expired）。"""
    cfg = _pc_device()
    return _call("GET", cfg["base"], f"/api/bind/{phone_id}/{request_id}",
                 device=cfg, timeout=6.0)


# ===================== 同步服务 =====================
class CloudApiService:
    def __init__(self, log=print):
        self.log = log
        self._thread = None
        self._stop = threading.Event()
        self._priv = None
        self._phones = {}
        self._keys = {}
        self._publish_digest = {}
        self._last_publish = 0.0
        self._last_approvals = None
        self._last_actions = 0.0
        self._last_phones = 0.0
        self._unreachable_since = 0.0
        self._relay_running = False
        self._net = False
        self._status = {
            "enabled": False, "reachable": False, "paired": False,
            "device_id": "", "base": "", "phones": 0,
            "uploaded_at": 0.0, "last_error": "", "mode": "api",
        }
        self._written = None
        self._written_at = 0.0

    # ---- 对外 ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cloud-api",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
        self._thread = None
        if self._relay_running:
            cloud_relay.stop()
            self._relay_running = False

    def status(self) -> dict:
        with _lock:
            return dict(self._status)

    # ---- 主循环 ----
    def _run(self):
        while not self._stop.is_set():
            cfg = config()
            if not cfg["enabled"]:
                self._set_status(enabled=False, reachable=False, mode="api")
                self._stop.wait(TICK)
                continue

            try:
                self._sync(cfg)
                if not self._net:
                    # 本轮没向后端发请求（轮询间隔未到）：沿用上一次的判定，
                    # 但兜底计时仍在走，到点就拉起中继
                    self._maybe_start_relay()
                    self._stop.wait(TICK)
                    continue
                if self._unreachable_since:
                    self.log("云同步：官网后端已恢复")
                self._unreachable_since = 0.0
                # 官网后端没有绑定手机（例如手机只配了 Gitee 通道）时，中继必须继续跑，
                # 否则手机端会一直收不到数据，界面却只显示官网后端在线
                relay_cfg = cloud_relay.config()
                keep_relay = (not self._phones) and relay_cfg["enabled"] \
                    and bool(relay_cfg["token"])
                if self._relay_running and not keep_relay:
                    cloud_relay.stop()
                    self._relay_running = False
                    self.log("云同步：已切回官网后端，Gitee 中继已停用")
                elif not self._relay_running and keep_relay:
                    self.log("云同步：官网后端暂无绑定手机，保留 Gitee 中继给已配对设备")
                    cloud_relay.start(self.log)
                    self._relay_running = True
                self._set_status(enabled=True, reachable=True,
                                 mode="dual" if self._relay_running else "api",
                                 base=cfg["base"], device_id=cfg["device_id"])
            except ApiUnreachable as e:
                self._fallback_to_relay(cfg, str(e))
            except ApiError as e:
                if "未授权" in str(e) or e.code == 401:
                    # 后端不认识本机（清库/换站点），重新注册一次
                    forget_binding()
                    self.log("云同步：设备凭据失效，已重新注册")
                # 5xx / 响应异常说明后端本身有问题，和“不可达”一样走 Gitee 兜底，
                # 否则手机端会一直收不到数据，界面却只显示官网报错
                if e.code >= 500 or e.code == 0:
                    self._fallback_to_relay(cfg, str(e))
                else:
                    self._set_status(enabled=True, reachable=True,
                                     last_error=str(e), base=cfg["base"])
            except Exception as e:                   # pragma: no cover
                self._set_status(last_error=f"{type(e).__name__}: {e}",
                                 base=cfg["base"])
            self._stop.wait(TICK)

    def _fallback_to_relay(self, cfg: dict, err_text: str):
        """官网后端不可用：稳住状态并拉起 Gitee 中继兜底。"""
        if not self._unreachable_since:
            self._unreachable_since = time.time()
            self.log(f"云同步：官网后端不可用（{err_text}）")
        self._set_status(enabled=True, reachable=False,
                         last_error=err_text, base=cfg["base"])
        self._maybe_start_relay()

    def _maybe_start_relay(self):
        """后端持续不可用超过阈值后，拉起 Gitee 中继（只拉一次）。"""
        if self._relay_running or not self._unreachable_since:
            return
        if time.time() - self._unreachable_since < RELAY_FALLBACK_AFTER:
            return
        self.log("云同步：改用 Gitee 中继兜底")
        cloud_relay.start(self.log)
        self._relay_running = True
        self._set_status(mode="gitee")

    def _sync(self, cfg: dict):
        base = cfg["base"]
        self._net = False
        if not (cfg["device_id"] and cfg["secret"]):
            self._net = True
            data = _call("POST", base, "/api/register",
                         {"kind": "pc", "name": cfg["name"]})
            save_config(device_id=data["deviceId"], secret=data["secret"])
            self.log("云同步：电脑端已注册到官网后端")
            return

        if not cfg["priv"]:
            save_config(priv=format(secrets.randbits(256) | 1, "x"))
            return

        self._priv = int(cfg["priv"], 16)
        device = {"device_id": cfg["device_id"], "secret": cfg["secret"]}
        now = time.time()

        # 1) 已绑定手机列表：决定给谁加密上传
        if now - self._last_phones >= PHONES_REFRESH_GAP:
            self._last_phones = now
            self._net = True
            data = _call("GET", base, f'/api/pc/{cfg["device_id"]}/phones',
                         device=device)
            phones = {}
            for item in data.get("phones", []):
                pub = str(item.get("pub") or "")
                if pub:
                    phones[item["phoneId"]] = item
            self._phones = phones
            self._keys = {}
            for phone_id, item in phones.items():
                try:
                    peer = int(item["pub"], 16)
                except ValueError:
                    continue
                self._keys[phone_id] = _aes_key(_shared_secret(self._priv, peer))
            self._set_status(paired=bool(phones), phones=len(phones))

        # 2) 变化且距上次上传 ≥10 秒才写；审批变化时立即上传
        if not self._keys:
            return
        snap = lan_server.snapshot()
        digest = _digest(snap)
        appr_key = json.dumps(snap.get("approvals") or [],
                              sort_keys=True, ensure_ascii=False)
        urgent = appr_key != self._last_approvals
        if urgent or now - self._last_publish >= PUBLISH_MIN_GAP:
            text = json.dumps(snap, ensure_ascii=False)
            uploaded = False
            for phone_id, key in self._keys.items():
                if not urgent and self._publish_digest.get(phone_id) == digest:
                    continue
                cipher = encrypt_text(key, text)
                self._net = True
                _call("PUT", base,
                      f'/api/pc/{cfg["device_id"]}/snapshot/{phone_id}',
                      {"cipher": cipher, "version": VERSION}, device=device)
                self._publish_digest[phone_id] = digest
                uploaded = True
            if uploaded:
                self._last_publish = now
                self._last_approvals = appr_key
                self._set_status(uploaded_at=now, last_error="")

        # 3) 手机端的确认结果
        if now - self._last_actions >= ACTIONS_POLL_GAP:
            self._last_actions = now
            self._net = True
            data = _call("GET", base, f'/api/pc/{cfg["device_id"]}/actions',
                         device=device)
            applied = 0
            for act in data.get("actions", []):
                key = self._keys.get(act.get("phoneId"))
                if key is not None:
                    try:
                        payload = json.loads(decrypt_text(key, act.get("cipher", "")))
                        for item in payload.get("decisions", []):
                            if lan_server.decide_approval(
                                    str(item.get("id", "")),
                                    bool(item.get("approve"))):
                                applied += 1
                    except Exception as e:
                        self._set_status(last_error=f"确认消息无法解析: {e}")
                _call("DELETE", base,
                      f'/api/pc/{cfg["device_id"]}/actions/{act["id"]}',
                      device=device)
            if applied:
                self.log(f"云同步：已应用手机确认 {applied} 条")

    def _set_status(self, **kwargs):
        with _lock:
            self._status.update(kwargs)
            snapshot = dict(self._status)
        now = time.time()
        if snapshot == self._written and now - self._written_at < 10.0:
            return
        try:
            _save_json(STATUS_FILE, {**snapshot, "ts": now})
        except OSError:
            return
        self._written = snapshot
        self._written_at = now


# ===================== 模块级接口 =====================
def start(log=print):
    global _service
    with _lock:
        if _service is None:
            _service = CloudApiService(log)
        _service.start()
    return _service


def stop():
    global _service
    with _lock:
        svc, _service = _service, None
    if svc:
        svc.stop()


_DEFAULT_STATUS = {
    "enabled": False, "reachable": False, "paired": False,
    "device_id": "", "base": "", "phones": 0,
    "uploaded_at": 0.0, "last_error": "", "mode": "api",
}


def status() -> dict:
    with _lock:
        svc = _service
    if svc is not None:
        return svc.status()
    data = _load_json(STATUS_FILE, {}) or {}
    if isinstance(data, dict) and time.time() - float(data.get("ts") or 0) < 30:
        return {k: data.get(k, v) for k, v in _DEFAULT_STATUS.items()}
    return dict(_DEFAULT_STATUS)


def forget_binding():
    """重新注册设备：只清设备凭据，保留密钥对。

    以前连 priv 一起清，导致每次重新注册都换一套密钥、手机端全部失配。
    """
    save_config(device_id="", secret="")


# ===================== 设置界面用 =====================
def list_phones() -> list:
    """读当前已绑定手机（主界面进程直接调后端，后台不在也能看）。"""
    cfg = config()
    if not (cfg["device_id"] and cfg["secret"]):
        return []
    data = _call("GET", cfg["base"], f'/api/pc/{cfg["device_id"]}/phones',
                  device=cfg, timeout=5.0)
    return data.get("phones", [])


def revoke_phone(phone_id: str):
    cfg = config()
    if not (cfg["device_id"] and cfg["secret"]):
        return
    _call("DELETE", cfg["base"],
          f'/api/pc/{cfg["device_id"]}/phones/{phone_id}',
          device=cfg, timeout=5.0)
