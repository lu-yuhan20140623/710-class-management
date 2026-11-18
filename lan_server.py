"""局域网直连服务：把课表、积分、卫生数据实时发给手机端。

设计目标：
- 只用标准库（http.server / socket），不引入 Web 框架，打包后无需额外依赖
- 手机与电脑连同一个 Wi-Fi，直接访问 http://<电脑IP>:8765 即可，不经过任何云服务
- 数据变化（打分、扣分、调课、上下课状态切换）时，通过 SSE 主动推送给手机

接口：
    GET /                 浏览器可读的接口说明页
    GET /api/ping         健康检查（手机用来发现电脑）
    GET /api/snapshot     完整数据快照（课表 + 状态 + 积分 + 卫生）
    GET /api/state        当前课节状态与倒计时
    GET /api/schedule     本周课表
    GET /api/scores       小组积分榜与记录
    GET /api/hygiene      卫生扣分统计与记录
    GET /api/events       SSE 实时推送（默认事件：snapshot，另有 heartbeat）

数据都是只读的，手机端不需要密码；请只在可信的教室局域网内开启。
"""

import ipaddress
import json
import queue
import socket
import sys
import threading
import time
from datetime import datetime, time as dt_time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import schedule_core as schedule
import score_records as store
from version import VERSION

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

DEFAULT_PORT = 8765
DEFAULT_CLASS = "七年级10班"
HEARTBEAT_SECONDS = 12

# 参与“数据变化”判断的文件：任何一个被改写都会触发一次推送
WATCH_FILES = [
    APP_DIR / "class_data.txt",
    APP_DIR / "student_data.txt",
    APP_DIR / "group_data.txt",
    APP_DIR / "hygiene_data.txt",
    APP_DIR / "overrides.json",
    APP_DIR / "disabled_ranges.json",
    APP_DIR / "settings.json",
]

_server: ThreadingHTTPServer | None = None
_server_port = DEFAULT_PORT
_server_lock = threading.Lock()
_watch_started = False

_subscribers: set = set()
_subscribers_lock = threading.Lock()

# ===================== 手机端确认（重置密钥授权） =====================
# 密钥重置不再仅凭“知道教师手机号”即可完成，必须由手机 App 点击“同意”。
APPROVAL_TTL = 120          # 请求有效期（秒）
_approvals: dict = {}
_approval_lock = threading.RLock()
_approval_seq = 0


def _cleanup_approvals():
    now = time.time()
    with _approval_lock:
        for rid, item in list(_approvals.items()):
            if item["status"] == "pending" and now - item["created"] > APPROVAL_TTL:
                item["status"] = "expired"
            if now - item["created"] > APPROVAL_TTL * 5:
                _approvals.pop(rid, None)


def submit_approval(kind: str, title: str, detail: str = "") -> dict:
    global _approval_seq
    _cleanup_approvals()
    with _approval_lock:
        _approval_seq += 1
        rid = f"{int(time.time())}-{_approval_seq}"
        _approvals[rid] = {
            "id": rid, "kind": kind, "title": title, "detail": detail,
            "created": time.time(), "status": "pending",
        }
    return {"id": rid, "expires_in": APPROVAL_TTL}


def pending_approvals() -> list:
    _cleanup_approvals()
    with _approval_lock:
        return [{"id": it["id"], "kind": it["kind"], "title": it["title"],
                 "detail": it["detail"]}
                for it in _approvals.values() if it["status"] == "pending"]


def decide_approval(rid: str, approve: bool) -> bool:
    _cleanup_approvals()
    with _approval_lock:
        item = _approvals.get(rid)
        if not item or item["status"] != "pending":
            return False
        item["status"] = "approved" if approve else "rejected"
        return True


def approval_status(rid: str) -> str:
    _cleanup_approvals()
    with _approval_lock:
        item = _approvals.get(rid)
        return item["status"] if item else "missing"


# ===================== 基础工具 =====================
def _load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def configured_port() -> int:
    """端口可在 settings.json 里用 lan_port 覆盖。"""
    data = _load_json(APP_DIR / "settings.json", {})
    try:
        port = int((data or {}).get("lan_port", DEFAULT_PORT))
        if 1024 <= port <= 65535:
            return port
    except (TypeError, ValueError, AttributeError):
        pass
    return DEFAULT_PORT


def lan_ip() -> str:
    """本机在局域网中的 IPv4 地址。UDP connect 只用于选路，不会真的发包。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("223.5.5.5", 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def base_url() -> str:
    port = _server_port if _server is not None else configured_port()
    return f"http://{lan_ip()}:{port}"


def status() -> dict:
    return {
        "running": _server is not None,
        "ip": lan_ip(),
        "port": _server_port,
        "url": base_url(),
        "clients": len(_subscribers),
    }


# ===================== 数据组装 =====================
def _class_name() -> str:
    classes = _load_json(APP_DIR / "class_data.txt", [])
    if isinstance(classes, list):
        for name in classes:
            if isinstance(name, str) and name.strip():
                return name.strip()
    return DEFAULT_CLASS


def _clock(value) -> str | None:
    """把 datetime / time 统一成 HH:MM。"""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, dt_time):
        return value.strftime("%H:%M")
    return None


def _short_time(value) -> str:
    """'2026-11-16 08:12:34' → '11-16 08:12'；解析失败时原样返回。"""
    text = str(value or "")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M")
    except ValueError:
        return text


def _state_view(info: dict) -> dict:
    now = datetime.now()
    seconds_to_end = None
    if info.get("state") == "in_class" and info.get("current_end"):
        end_dt = datetime.combine(now.date(), info["current_end"])
        seconds_to_end = max(0, int((end_dt - now).total_seconds()))

    return {
        "state": info.get("state", ""),
        "weekday": schedule.WEEKDAY_NAMES[info["day"]] if info.get("day", -1) >= 0 else "周末",
        "day": info.get("day", -1),
        "current_period": info.get("current_period"),
        "current_name": info.get("current_name", ""),
        "current_subject": info.get("current_subject", ""),
        "current_start": _clock(info.get("current_start")),
        "current_end": _clock(info.get("current_end")),
        "seconds_to_current_end": seconds_to_end,
        "next_period": info.get("next_period"),
        "next_name": info.get("next_name", ""),
        "next_subject": info.get("next_subject", ""),
        "next_start": _clock(info.get("next_start")),
        "next_end": _clock(info.get("next_end")),
        "seconds_to_next": int(info.get("seconds_to_next", 0) or 0),
        "is_counting": bool(info.get("is_counting")),
        "is_prebell": bool(info.get("is_prebell")),
        "seconds_to_prebell": int(info.get("seconds_to_prebell", 0) or 0),
        "disabled": bool(info.get("disabled")),
        "disabled_note": info.get("disabled_note", ""),
        "school_end": _clock(info.get("school_end")),
        "server_epoch_ms": int(now.timestamp() * 1000),
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _schedule_view() -> dict:
    overrides = schedule.get_all_overrides()
    periods = [
        {"id": pid, "name": f"第{pid}节",
         "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
        for pid, (start, end) in sorted(schedule.PERIODS.items())
    ]

    cells = []
    for day in sorted(schedule.DEFAULT_SCHEDULE):
        for pid in sorted(schedule.DEFAULT_SCHEDULE[day]):
            subject = overrides.get(f"{day}-{pid}") or schedule.DEFAULT_SCHEDULE[day][pid]
            cells.append({
                "day_index": day, "period_id": pid,
                "subject": subject, "classroom": "",
            })

    extra_slots = [
        {"id": 99, "name": schedule.PRACTICE_NAME,
         "start": schedule.PRACTICE_START.strftime("%H:%M"),
         "end": schedule.PRACTICE_END.strftime("%H:%M")},
        {"id": 100, "name": schedule.EVENING_NAME,
         "start": schedule.EVENING_START.strftime("%H:%M"),
         "end": schedule.EVENING_END.strftime("%H:%M")},
    ]
    extra_cells = []
    for day in range(5):
        extra_cells.append({
            "day_index": day, "period_id": 99,
            "subject": schedule.PRACTICE_SUBJECTS.get(day, "小练"),
            "classroom": "",
        })
        extra_cells.append({
            "day_index": day, "period_id": 100,
            "subject": schedule.EVENING_NAME, "classroom": "",
        })

    return {
        "periods": periods,
        "extra_slots": extra_slots,
        "schedule": cells,
        "extra_schedule": extra_cells,
    }


def _group_scores(cls: str) -> list:
    students = store.load_students()
    groups = store.load_groups()
    stu = students.get(cls, {}) if isinstance(students, dict) else {}
    group_map = groups.get(cls, {}) if isinstance(groups, dict) else {}
    if not isinstance(stu, dict):
        stu = {}
    if not isinstance(group_map, dict):
        group_map = {}

    rows = []
    for gname, group in group_map.items():
        if not isinstance(group, dict):
            continue
        members = [sid for sid in group.get("members", []) if sid in stu]
        records = []
        member_rows = []
        for sid in members:
            info = stu.get(sid) or {}
            if not isinstance(info, dict):
                info = {}
            member_rows.append({
                "sid": sid,
                "name": info.get("name", ""),
                "total": store.student_total(info),
                "leader": sid == group.get("leader"),
            })
            for rec in info.get("records", []):
                if not isinstance(rec, dict):
                    continue
                records.append({
                    "time": _short_time(rec.get("time", "")),
                    "reason": rec.get("reason", ""),
                    "delta": store.record_delta(rec),
                    "member": info.get("name", ""),
                })
        records.sort(key=lambda item: item["time"], reverse=True)

        leader_sid = group.get("leader") or ""
        leader = (stu.get(leader_sid) or {}).get("name") or leader_sid
        rows.append({
            "name": gname,
            "leader": leader,
            "total": store.group_total(group, stu),
            "records": records[:50],
            "members": member_rows,
        })

    rows.sort(key=lambda row: -row["total"])
    return rows


def _group_names(cls: str) -> list:
    groups = store.load_groups()
    block = groups.get(cls, {}) if isinstance(groups, dict) else {}
    return list(block) if isinstance(block, dict) else []


def _hygiene_view(cls: str) -> dict:
    data = store.load_hygiene()
    block = data.get(cls, {}) if isinstance(data, dict) else {}
    raw = block.get("records", []) if isinstance(block, dict) else []

    by_group = {name: 0 for name in _group_names(cls)}
    by_reason: dict[str, int] = {}
    records = []
    total = 0

    for rec in raw:
        if not isinstance(rec, dict):
            continue
        try:
            score = abs(int(rec.get("score", 0) or 0))
        except (TypeError, ValueError):
            score = 0
        gname = rec.get("group") or "未分组"
        reason = rec.get("reason") or "未填写"
        by_group[gname] = by_group.get(gname, 0) + score
        by_reason[reason] = by_reason.get(reason, 0) + 1
        total += score
        records.append({
            "group": gname,
            "member": rec.get("name", ""),
            "reason": reason,
            "score": score,
            "time": _short_time(rec.get("time", "")),
        })

    records.sort(key=lambda item: item["time"], reverse=True)
    return {
        "total_records": len(records),
        "total_deduct": total,
        "by_group": sorted(by_group.items(), key=lambda kv: -kv[1]),
        "by_reason": sorted(by_reason.items(), key=lambda kv: -kv[1]),
        "records": records[:300],
    }


def snapshot() -> dict:
    now = datetime.now()
    cls = _class_name()
    current = schedule.find_current_period(now)
    return {
        "type": "snapshot",
        "app": "class-schedule",
        "version": VERSION,
        "class_name": cls,
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch_ms": int(now.timestamp() * 1000),
        "state": _state_view(current),
        "reset_hint": store.next_reset_text(now),
        **_schedule_view(),
        "groups": _group_scores(cls),
        "hygiene": _hygiene_view(cls),
    }


# ===================== 实时推送 =====================
def _fingerprint():
    info = schedule.find_current_period()
    state_key = (
        info.get("state"), info.get("current_period"), info.get("next_period"),
        bool(info.get("is_counting")), bool(info.get("is_prebell")),
        bool(info.get("disabled")),
    )
    stamps = []
    for path in WATCH_FILES:
        try:
            stat = path.stat()
            stamps.append((path.name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append((path.name, 0, 0))
    return state_key, tuple(stamps)


def _publish(event: str, payload: dict):
    with _subscribers_lock:
        targets = list(_subscribers)
    for q in targets:
        try:
            q.put_nowait((event, payload))
        except queue.Full:
            # 慢客户端直接丢弃最旧的一条，避免拖住其他手机
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait((event, payload))
            except queue.Full:
                pass


def _watch_loop():
    last_key = None
    last_push = 0.0
    while True:
        try:
            key = _fingerprint()
            now = time.time()
            payload = None
            if key != last_key:
                payload = snapshot()
                last_key = key
            elif now - last_push >= 60:
                # 每 60 秒补一次全量，修正手机端累计的计时误差
                payload = snapshot()
            if payload is not None:
                _publish("snapshot", payload)
                last_push = now
        except Exception as exc:  # 单个循环出错不能把推送线程带崩
            print(f"[LAN] watch 异常: {exc}", flush=True)
        time.sleep(1.0)


# ===================== HTTP 接口 =====================
def _sse_message(event: str, payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>课程表 · 局域网数据</title>
<style>
body{margin:0;background:#0f1117;color:#e8eaf1;font-family:"Microsoft YaHei UI",sans-serif;line-height:1.8}
.wrap{max-width:640px;margin:0 auto;padding:36px 22px}
h1{font-size:24px;margin:0 0 6px}
p{color:#9aa3b8;font-size:14px}
.card{background:#171b26;border:1px solid #2a3042;border-radius:12px;padding:16px 18px;margin-top:18px}
a{color:#7ab8ff;text-decoration:none}
code{background:#232a3a;border-radius:5px;padding:2px 7px;font-family:Consolas,monospace;font-size:13px}
</style></head><body><div class="wrap">
<h1>课程表 · 局域网数据接口</h1>
<p>电脑端服务运行正常。手机和电脑连接同一个 Wi-Fi 后，可直接读取下面的地址。</p>
<div class="card">
<p><a href="/api/snapshot">/api/snapshot</a> · 完整数据（课表、状态、积分、卫生）</p>
<p><a href="/api/state">/api/state</a> · 当前课节与倒计时</p>
<p><a href="/api/schedule">/api/schedule</a> · 本周课表</p>
<p><a href="/api/scores">/api/scores</a> · 小组积分</p>
<p><a href="/api/hygiene">/api/hygiene</a> · 卫生扣分</p>
<p><a href="/api/events">/api/events</a> · SSE 实时推送</p>
<p><a href="/api/approvals/pending">/api/approvals/pending</a> · 待手机确认的重置请求</p>
</div>
<p style="margin-top:18px">提示：手机 App 可先请求 <code>/api/ping</code> 判断电脑是否在线，再订阅 <code>/api/events</code> 接收实时数据。</p>
</div></body></html>"""


class _LanServer(ThreadingHTTPServer):
    """Windows 下 SO_REUSEADDR 会允许重复绑定同一端口，必须显式关闭。"""

    allow_reuse_address = False
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    server_version = "ClassScheduleLAN/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 不刷屏，日志交给调用方
        pass

    # ---- 响应工具 ----
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _is_local_client(self) -> bool:
        """请求是否来自本机（127.0.0.1 / ::1）。"""
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except (ValueError, IndexError):
            return False

    def _send_json(self, obj, status_code: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text: str):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    # ---- 路由 ----
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = (urlsplit(self.path).path or "/").rstrip("/") or "/"
        try:
            if path in ("/", "/index.html"):
                self._send_html(INDEX_HTML)
            elif path == "/api/ping":
                self._send_json({
                    "ok": True,
                    "app": "class-schedule",
                    "version": VERSION,
                    "class_name": _class_name(),
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "snapshot": "/api/snapshot",
                    "events": "/api/events",
                })
            elif path == "/api/snapshot":
                self._send_json(snapshot())
            elif path == "/api/state":
                self._send_json({"type": "state", **_state_view(schedule.find_current_period())})
            elif path == "/api/schedule":
                self._send_json({"type": "schedule", "class_name": _class_name(), **_schedule_view()})
            elif path == "/api/scores":
                cls = _class_name()
                self._send_json({"type": "scores", "class_name": cls, "groups": _group_scores(cls)})
            elif path == "/api/hygiene":
                cls = _class_name()
                self._send_json({"type": "hygiene", "class_name": cls, **_hygiene_view(cls)})
            elif path == "/api/events":
                self._serve_events()
            elif path == "/api/approvals/pending":
                self._send_json({"items": pending_approvals()})
            elif path == "/api/approvals/status":
                rid = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
                self._send_json({"id": rid, "status": approval_status(rid)})
            else:
                self._send_json({"ok": False, "error": "not found", "path": path}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            except Exception:
                pass

    def do_POST(self):
        path = (urlsplit(self.path).path or "/").rstrip("/") or "/"
        if path == "/api/approvals" and not self._is_local_client():
            # 只允许电脑本机发起确认请求，防止同网段他人伪造“重置密钥”弹窗骚扰手机
            self._send_json({"ok": False, "error": "forbidden"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads((raw or b"{}").decode("utf-8")) or {}
        except (ValueError, OSError):
            self._send_json({"ok": False, "error": "bad request"}, 400)
            return
        try:
            if path == "/api/approvals":
                res = submit_approval(str(payload.get("kind") or "reset"),
                                      str(payload.get("title") or "重置密钥"),
                                      str(payload.get("detail") or ""))
                self._send_json({"ok": True, **res})
            elif path == "/api/approvals/decide":
                ok = decide_approval(str(payload.get("id") or ""),
                                     bool(payload.get("approve")))
                self._send_json({"ok": ok}, 200 if ok else 404)
            else:
                self._send_json({"ok": False, "error": "not found", "path": path}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            except Exception:
                pass

    def _serve_events(self):
        """SSE：先发一份全量，之后数据变化 / 状态切换时主动推送。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        client = queue.Queue(maxsize=8)
        with _subscribers_lock:
            _subscribers.add(client)
        try:
            self.wfile.write(_sse_message("snapshot", snapshot()))
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event, payload = client.get(timeout=HEARTBEAT_SECONDS)
                    chunk = _sse_message(event, payload)
                except queue.Empty:
                    chunk = b": ping\n\n"
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with _subscribers_lock:
                _subscribers.discard(client)


# ===================== 启停 =====================
def start(port: int | None = None, host: str = "0.0.0.0") -> tuple[bool, str, str]:
    """启动 HTTP 服务。返回 (本进程是否已成功提供服务, 提示, 访问地址)。

    端口已被其他进程占用时返回 (False, 提示, 地址)，由调用方决定是否稍后重试；
    手机端仍可能通过占用端口的那个实例正常访问。
    """
    global _server, _server_port, _watch_started

    with _server_lock:
        if _server is not None:
            return True, "局域网服务已启动", base_url()

        _server_port = int(port or configured_port())
        try:
            httpd = _LanServer((host, _server_port), _Handler)
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            if winerror == 10048 or getattr(exc, "errno", None) in (48, 98, 10048):
                return False, f"端口 {_server_port} 已被占用（可能后台服务正在提供）", base_url()
            return False, f"启动失败：{exc}", base_url()

        httpd.daemon_threads = True
        _server = httpd

        thread = threading.Thread(target=httpd.serve_forever, name="lan-http", daemon=True)
        thread.start()

        if not _watch_started:
            _watch_started = True
            threading.Thread(target=_watch_loop, name="lan-watch", daemon=True).start()

        return True, "局域网服务已启动", base_url()


def stop():
    """停止服务（主要用于开发调试）。"""
    global _server
    with _server_lock:
        if _server is None:
            return
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass
        _server = None


if __name__ == "__main__":
    ok, message, url = start()
    print(message, url, flush=True)
    print("接口：/api/snapshot  /api/state  /api/events", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()
