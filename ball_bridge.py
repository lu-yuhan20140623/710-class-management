"""
悬浮球进程 ↔ 主界面进程的轻量协作（共享文件，零 IPC）
- 悬浮球点开「学生积分」时，若主界面在运行，就写一个请求文件交给主界面打开，
  避免两个进程各开一个积分窗口、互相覆盖 group_data.txt
- 主界面不可用时返回 False，由悬浮球进程自己打开
"""

import ctypes
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

REQUEST_FILE = APP_DIR / ".open_score.request"
SHOW_REQUEST_FILE = APP_DIR / ".show_ball.request"
BALL_PID_FILE = APP_DIR / ".ball.pid"
MAIN_TITLE = "课程表 · 七年级10班"


def main_window_handle() -> int:
    """主界面窗口句柄；未运行时为 0。"""
    if os.name != "nt":
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        return int(user32.FindWindowW(None, MAIN_TITLE) or 0)
    except Exception:
        return 0


def request_open_score(readonly: bool = False) -> bool:
    """请主界面打开学生积分；主界面未运行时返回 False。"""
    if not main_window_handle():
        return False
    try:
        REQUEST_FILE.write_text("readonly" if readonly else "edit", encoding="utf-8")
    except OSError:
        return False
    activate_main_window()
    return True


def take_open_score_request() -> str:
    """主界面调用：取走并清除请求，返回 "edit" / "readonly"；没有请求返回空串。"""
    try:
        if not REQUEST_FILE.exists():
            return ""
        mode = REQUEST_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    try:
        REQUEST_FILE.unlink()
    except OSError:
        pass
    return "readonly" if mode == "readonly" else "edit"


def pid_alive(pid: int) -> bool:
    """判断进程是否还活着（不发送信号，不会误杀）。"""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259      # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def ball_pid() -> int:
    try:
        return int(BALL_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def ball_running() -> bool:
    """悬浮球进程是否在跑（隐藏状态也算在跑）。"""
    return pid_alive(ball_pid())


def request_show_ball() -> bool:
    """请已隐藏的悬浮球重新显示；悬浮球进程没在跑时返回 False。"""
    if not ball_running():
        return False
    try:
        SHOW_REQUEST_FILE.write_text("show", encoding="utf-8")
    except OSError:
        return False
    return True


def take_show_ball_request() -> bool:
    """悬浮球调用：取走并清除显示请求。"""
    try:
        if not SHOW_REQUEST_FILE.exists():
            return False
    except OSError:
        return False
    try:
        SHOW_REQUEST_FILE.unlink()
    except OSError:
        pass
    return True


def activate_main_window() -> bool:
    """把主界面从任务栏还原并切到前台。"""
    hwnd = main_window_handle()
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
