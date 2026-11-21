"""Gitee 云端中继：电脑与手机通过 Gitee 仓库交换加密数据。

链路：
    电脑 --(AES-GCM 加密快照)--> Gitee 仓库 --(手机每 8 秒拉取)--> 手机
    手机 --(加密的确认/拒绝)--> Gitee 仓库 --(电脑每 4 秒拉取)--> 电脑

密钥：两端用模幂（Diffie-Hellman，2048 位 MODP 群）各自算出同一个共享值，
再 SHA-256 派生 AES-256 密钥；共享密钥本身不经过网络传输。

局域网可用时，手机端会自动改走 lan_server 直连，这里只作为兜底。
"""

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys

import lan_server

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    # 2.1.x 的运行文件里没有打包 cryptography，用增量补丁升级后会走到这里：
    # 只让云同步报错提示换完整安装包，不能连累整个后台启动失败
    AESGCM = None

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

SETTINGS_FILE = APP_DIR / "settings.json"
# 后台服务写、主界面读：两端是不同进程，界面的 status() 只能靠这个文件
STATUS_FILE = APP_DIR / "relay_status.json"

DEFAULT_OWNER = "lu-yuhan20140623"
DEFAULT_REPO = "710"
DEFAULT_BRANCH = "master"
# 令牌不入库：优先读 settings.json，其次读本地 relay_secret.json
SECRET_FILE = APP_DIR / "relay_secret.json"

PC_PUB_PATH = "relay/pc_pub.json"
PHONE_PUB_PATH = "relay/phone_pub.json"
STATE_PATH = "relay/state.enc"
ACTIONS_PATH = "relay/phone.enc"

PUBLISH_MIN_GAP = 10.0
PULL_ACTIONS_GAP = 4.0
PHONE_PUB_CHECK_GAP = 30.0
TICK = 2.0
AAD = b"class-schedule-relay-v1"

# RFC 3526 2048 位 MODP 群（group 14），g = 2
P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74"
    "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14"
    "374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406"
    "B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A1"
    "63BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356"
    "208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E"
    "462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2B"
    "CBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FF"
    "FFFFFFFFFFFFFF",
    16,
)
G = 2
_PRIV_BYTES = 32

_lock = threading.RLock()
_service = None


def _load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _default_token() -> str:
    data = _load_json(SECRET_FILE, {}) or {}
    if isinstance(data, dict):
        return str(data.get("token") or "").strip()
    return ""


def config() -> dict:
    data = _load_json(SETTINGS_FILE, {}) or {}
    raw = data.get("cloud_relay") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "owner": str(raw.get("owner") or DEFAULT_OWNER).strip(),
        "repo": str(raw.get("repo") or DEFAULT_REPO).strip(),
        "branch": str(raw.get("branch") or DEFAULT_BRANCH).strip(),
        "token": str(raw.get("token") or _default_token()).strip(),
        # 持久化的 DH 私钥：上次运行生成的，重启后沿用
        "priv": str(raw.get("priv") or "").strip(),
    }


def save_config(**kwargs):
    data = _load_json(SETTINGS_FILE, {}) or {}
    if not isinstance(data, dict):
        data = {}
    current = config()
    current.update({k: v for k, v in kwargs.items() if v is not None})
    data["cloud_relay"] = current
    _save_json(SETTINGS_FILE, data)


# ===================== 模幂密钥协商 =====================
def _public_value(priv: int) -> int:
    return pow(G, priv, P)


def _shared_secret(priv: int, peer: int) -> int:
    return pow(peer, priv, P)


def _aes_key(shared: int) -> bytes:
    size = (P.bit_length() + 7) // 8
    return hashlib.sha256(shared.to_bytes(size, "big")).digest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


def _require_aes():
    if AESGCM is None:
        raise RuntimeError("当前运行文件缺少加密组件，请用完整安装包覆盖更新")


def encrypt_text(key: bytes, text: str) -> str:
    _require_aes()
    nonce = secrets.token_bytes(12)
    body = AESGCM(key).encrypt(nonce, text.encode("utf-8"), AAD)
    return _b64(nonce + body)


def decrypt_text(key: bytes, token: str) -> str:
    _require_aes()
    raw = _unb64(token)
    return AESGCM(key).decrypt(raw[:12], raw[12:], AAD).decode("utf-8")


# ===================== Gitee 仓库读写 =====================
class GiteeRepo:
    """只封装 contents 接口：读文件、写文件。"""

    def __init__(self, cfg: dict, timeout: float = 8.0):
        self.owner = cfg["owner"]
        self.repo = cfg["repo"]
        self.branch = cfg["branch"]
        self.token = cfg["token"]
        self.timeout = timeout
        self._sha_cache: dict = {}

    def _url(self, path: str) -> str:
        quoted = urllib.parse.quote(path)
        return (
            f"https://gitee.com/api/v5/repos/{self.owner}/{self.repo}"
            f"/contents/{quoted}"
        )

    def _request(self, req) -> dict:
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_text(self, path: str):
        query = urllib.parse.urlencode(
            {"access_token": self.token, "ref": self.branch}
        )
        req = urllib.request.Request(f"{self._url(path)}?{query}")
        try:
            data = self._request(req)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        if isinstance(data, list):
            # Gitee 对不存在的文件返回 200 + []，按“不存在”处理
            return None
        if isinstance(data, dict) and data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8")
            self._sha_cache[path] = data.get("sha")
            return content
        if isinstance(data, dict) and data.get("sha"):
            self._sha_cache[path] = data["sha"]
        return ""

    def _fetch_sha(self, path: str):
        query = urllib.parse.urlencode(
            {"access_token": self.token, "ref": self.branch}
        )
        req = urllib.request.Request(f"{self._url(path)}?{query}")
        try:
            data = self._request(req)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        if isinstance(data, list):
            return None
        return data.get("sha")

    def put_text(self, path: str, text: str, message: str) -> bool:
        for attempt in (0, 1):
            payload = {
                "access_token": self.token,
                "content": _b64(text.encode("utf-8")),
                "message": message,
                "branch": self.branch,
            }
            sha = self._sha_cache.get(path)
            if sha is None:
                sha = self._fetch_sha(path)
            if sha:
                payload["sha"] = sha
            req = urllib.request.Request(
                self._url(path),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                # Gitee：新建用 POST，更新已存在文件必须用 PUT
                method="PUT" if sha else "POST",
            )
            try:
                data = self._request(req)
            except urllib.error.HTTPError as e:
                # 409/400 多为 sha 过期，重新取一次再试
                if attempt == 0 and e.code in (400, 409, 422):
                    self._sha_cache.pop(path, None)
                    continue
                raise
            if isinstance(data, dict):
                # 写入响应的 sha 在 content.sha，兼容顶层没有 sha 的情况
                new_sha = data.get("sha")
                if not new_sha and isinstance(data.get("content"), dict):
                    new_sha = data["content"].get("sha")
                if new_sha:
                    self._sha_cache[path] = new_sha
            return True
        return False


# ===================== 快照稳定化（去掉秒级变化字段） =====================
def _stable_view(snap: dict) -> dict:
    view = json.loads(json.dumps(snap, ensure_ascii=False))
    view.pop("server_time", None)
    view.pop("epoch_ms", None)
    state = view.get("state")
    if isinstance(state, dict):
        for key in (
            "server_time", "server_epoch_ms",
            "seconds_to_current_end", "seconds_to_next", "seconds_to_prebell",
        ):
            state.pop(key, None)
    return view


def _digest(snap: dict) -> str:
    raw = json.dumps(_stable_view(snap), ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _persistent_priv() -> int:
    """中继用的 DH 私钥必须持久化：每次重启都换密钥会让手机端全部失配。"""
    raw = str(config().get("priv") or "").strip()
    if raw:
        try:
            value = int(raw, 16)
            if value > 1:
                return value
        except ValueError:
            pass
    value = secrets.randbits(256) | 1
    save_config(priv=format(value, "x"))
    return value


# ===================== 中继服务 =====================
class RelayService:
    def __init__(self, log=print):
        self.log = log
        self._thread = None
        self._stop = threading.Event()
        self._priv = _persistent_priv()
        self._key = None
        self._peer_pub = None
        self._pc_pub_uploaded_for = None
        self._last_digest = None
        self._last_approvals_key = None
        self._last_publish = 0.0
        self._last_actions_poll = 0.0
        self._last_phone_pub_check = 0.0
        self._seen_decisions = set()
        self._last_actions_text = None
        self._status = {
            "enabled": False, "paired": False, "uploaded_at": 0.0,
            "last_error": "", "repo": "",
        }
        self._written = None
        self._written_at = 0.0

    # ---- 对外 ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="cloud-relay", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
        self._thread = None

    def status(self) -> dict:
        with _lock:
            return dict(self._status)

    # ---- 主循环 ----
    def _run(self):
        while not self._stop.is_set():
            cfg = config()
            if not cfg["enabled"] or not cfg["token"]:
                self._set_status(enabled=False, last_error="")
                self._stop.wait(TICK)
                continue

            repo_key = (cfg["owner"], cfg["repo"], cfg["branch"], cfg["token"])
            if repo_key != self._pc_pub_uploaded_for:
                self._key = None
                self._peer_pub = None
                self._last_digest = None
                self._last_approvals_key = None
                self._last_actions_text = None
            self._set_status(
                enabled=True, repo=f'{cfg["owner"]}/{cfg["repo"]}',
                paired=self._key is not None,
            )

            repo = GiteeRepo(cfg)
            try:
                self._sync(repo, cfg, repo_key)
            except Exception as e:
                self._set_status(last_error=f"{type(e).__name__}: {e}")
            self._stop.wait(TICK)

    def _sync(self, repo: GiteeRepo, cfg: dict, repo_key: tuple):
        # 1) 发布本机公钥（进程生命周期内只需成功一次）
        if self._pc_pub_uploaded_for != repo_key:
            body = json.dumps({
                "v": 1, "g": G, "p": format(P, "x"),
                "A": format(_public_value(self._priv), "x"),
                "ts": int(time.time()),
            })
            repo.put_text(PC_PUB_PATH, body, "relay: publish pc public key")
            self._pc_pub_uploaded_for = repo_key
            self.log("云同步：已发布电脑公钥")

        # 2) 读取手机公钥，派生共享密钥（定期复查：手机重装后换了公钥要重新协商）
        now = time.time()
        if self._key is None or now - self._last_phone_pub_check >= PHONE_PUB_CHECK_GAP:
            self._last_phone_pub_check = now
            text = repo.get_text(PHONE_PUB_PATH)
            if text:
                data = json.loads(text)
                peer = int(str(data.get("B", "0")), 16)
                if peer > 1 and peer != self._peer_pub:
                    self._peer_pub = peer
                    self._key = _aes_key(_shared_secret(self._priv, peer))
                    # 密钥换了，旧快照手机解不开，强制重新上传
                    self._last_digest = None
                    self._last_approvals_key = None
                    self.log("云同步：密钥协商完成")
                    self._set_status(paired=True)

        if self._key is None:
            return

        # 3) 数据变化且距上次上传 ≥10 秒才写入
        snap = lan_server.snapshot()
        digest = _digest(snap)
        # 审批请求/结果变化时不走 10 秒限流，让手机端尽快拿到或收回弹窗
        appr_key = json.dumps(snap.get("approvals") or [], sort_keys=True,
                              ensure_ascii=False)
        urgent = appr_key != self._last_approvals_key
        if digest != self._last_digest and (urgent or now - self._last_publish >= PUBLISH_MIN_GAP):
            text = encrypt_text(self._key, json.dumps(snap, ensure_ascii=False))
            repo.put_text(STATE_PATH, text, "relay: update snapshot")
            self._last_digest = digest
            self._last_publish = now
            self._last_approvals_key = appr_key
            self._set_status(uploaded_at=now, last_error="")

        # 4) 拉取手机端的确认结果
        if now - self._last_actions_poll >= PULL_ACTIONS_GAP:
            self._last_actions_poll = now
            text = repo.get_text(ACTIONS_PATH)
            if text and text != self._last_actions_text:
                self._last_actions_text = text
                data = None
                try:
                    data = json.loads(decrypt_text(self._key, text))
                except Exception as e:
                    # 兼容 1.0.x 手机端：它把确认结果写成明文
                    try:
                        legacy = json.loads(text)
                    except Exception:
                        legacy = None
                    if isinstance(legacy, dict) and "decisions" in legacy:
                        data = legacy
                        self.log("云同步：确认消息为旧版明文，已兼容处理")
                    else:
                        self._set_status(last_error=f"确认消息无法解析: {e}")
                        return
                applied = 0
                for item in data.get("decisions", []):
                    rid = str(item.get("id", ""))
                    if not rid or rid in self._seen_decisions:
                        continue
                    self._seen_decisions.add(rid)
                    if lan_server.decide_approval(rid, bool(item.get("approve"))):
                        applied += 1
                if applied:
                    self.log(f"云同步：已应用手机确认 {applied} 条")

    def _set_status(self, **kwargs):
        with _lock:
            self._status.update(kwargs)
            snapshot = dict(self._status)
        # 状态没变也要每 10 秒写一次心跳，主界面才知道后台还活着
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
            _service = RelayService(log)
        _service.start()
    return _service


def stop():
    global _service
    with _lock:
        svc, _service = _service, None
    if svc:
        svc.stop()


_DEFAULT_STATUS = {
    "enabled": False, "paired": False, "uploaded_at": 0.0,
    "last_error": "", "repo": "",
}


def status() -> dict:
    with _lock:
        svc = _service
    if svc is not None:
        return svc.status()
    # 主界面进程没有中继服务，读后台服务写下的状态文件
    data = _load_json(STATUS_FILE, {}) or {}
    if isinstance(data, dict) and time.time() - float(data.get("ts") or 0) < 30:
        return {k: data.get(k, v) for k, v in _DEFAULT_STATUS.items()}
    return dict(_DEFAULT_STATUS)
