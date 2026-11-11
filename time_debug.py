"""
系统时间调试工具（临时使用）
- 检测管理员权限
- 修改 Windows 系统时间（Google 需管理员权限，自动 UAC 提权）
- 从网络获取北京时间
- 恢复北京时间
"""

import base64
import ctypes
import json
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


def is_admin() -> bool:
    """当前进程是否拥有管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_ps(command: str, elevate: bool = False, timeout: int = 20):
    """通过 PowerShell 执行命令；elevate=True 时以管理员身份提权运行。"""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode()

    if not elevate:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=timeout,
        )

    # 提权：由普通 powershell 启动一个 RunAs 的子进程
    inner = (
        "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{encoded}'"
    )
    inner_encoded = base64.b64encode(inner.encode("utf-16-le")).decode()
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", inner_encoded],
        capture_output=True, text=True, timeout=timeout,
    )


def set_system_time(target: datetime) -> tuple[bool, str]:
    """把 Windows 系统时间设置为 target，返回 (成功, 消息)。"""
    dt_str = target.strftime("%Y/%m/%d %H:%M:%S")
    command = f"Set-Date -Date '{dt_str}'"

    try:
        if is_admin():
            r = _run_ps(command)
            if r.returncode == 0:
                return True, f"系统时间已设为 {dt_str}"
            msg = (r.stderr or r.stdout or "").strip() or "设置失败（未知错误）"
            return False, msg

        # 非管理员：尝试 UAC 提权
        r = _run_ps(command, elevate=True, timeout=90)
        if r.returncode == 0:
            # 提权进程结束后校验实际时间
            now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
            tgt_str = target.strftime("%Y/%m/%d %H:%M")
            if now_str == tgt_str:
                return True, f"系统时间已设为 {dt_str}"
            return True, f"已请求提权修改为 {dt_str}，请确认 UAC 弹窗"
        msg = (r.stderr or r.stdout or "").strip() or "提权执行失败"
        return False, msg
    except subprocess.TimeoutExpired:
        return False, "执行超时（可能 UAC 弹窗未确认）"
    except Exception as e:
        return False, f"异常：{e}"


def get_network_time() -> datetime | None:
    """从网络获取北京时间（UTC+8），失败返回 None。"""
    # 源 1：淘宝时间戳接口（毫秒 epoch）
    try:
        req = urllib.request.Request(
            "http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ts = int(data["data"]["t"]) / 1000.0
            return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
    except Exception:
        pass

    # 源 2：HTTP Date 响应头
    for url in ("https://www.baidu.com", "https://www.aliyun.com"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                date_str = resp.headers.get("Date")
                if date_str:
                    dt = parsedate_to_datetime(date_str).astimezone()
                    return dt.replace(tzinfo=None)
        except Exception:
            continue

    return None


def restore_beijing_time() -> tuple[bool, str]:
    """恢复系统时间为北京时间（优先网络时间，失败则用本机时间）。"""
    net = get_network_time()
    if net is not None:
        ok, msg = set_system_time(net)
        return ok, msg if ok else f"网络时间获取成功但设置失败：{msg}"

    # 网络不可用时，用本机当前时间（此时本机时区通常已是东八区）
    local = datetime.now()
    ok, msg = set_system_time(local)
    return ok, msg if ok else f"网络时间不可用且本机设置失败：{msg}"
