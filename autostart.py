"""
Windows 开机自启动 + backend 常驻进程管理
- 注册表 HKCU\\...\\Run 注册 backend_service.py（pythonw 无窗口）
- 提供 backend 启停函数（给 main.py 设置面板用）
"""

import os
import sys
import subprocess
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ClassSchedule"  # 注册表项名

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
BACKEND_SCRIPT = APP_DIR / "backend_service.py"
BACKEND_EXE = APP_DIR / "ClassSchedule_Backend.exe"
PID_FILE = APP_DIR / ".backend.pid"


# ============================================================
# 自启动命令
# ============================================================
def _pythonw_true() -> str:
    """找真正的 pythonw.exe，不用 Microsoft Store shim。"""
    import shutil
    exe_dir = os.path.dirname(sys.executable)
    for c in [
        os.path.join(exe_dir, "pythonw.exe"),
        shutil.which("pythonw.exe"),
        shutil.which("pythonw"),
        sys.executable,
    ]:
        if c and os.path.exists(c):
            return c
    return sys.executable


def get_command_for_backend() -> str:
    """开机自启 backend（无控制台）。"""
    if getattr(sys, "frozen", False):
        return f'"{BACKEND_EXE}"'
    return f'"{_pythonw_true()}" "{BACKEND_SCRIPT}"'


def get_command_for_ui() -> str:
    """设置面板入口 main.py（有控制台，调试用）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = APP_DIR / "main.py"
    return f'"{sys.executable}" "{main_py}"'


# 兼容旧调用：默认返回 backend 命令
get_command = get_command_for_backend


# ============================================================
# 注册表
# ============================================================
def is_registered() -> bool:
    if winreg is None or os.name != "nt":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def register() -> tuple[bool, str]:
    if winreg is None or os.name != "nt":
        return False, "仅支持 Windows"
    try:
        cmd = get_command_for_backend()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        return True, f"已注册：{cmd}"
    except Exception as e:
        return False, f"注册失败：{e}"


def unregister() -> tuple[bool, str]:
    if winreg is None or os.name != "nt":
        return False, "仅支持 Windows"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_NAME)
        return True, "已卸载"
    except FileNotFoundError:
        return True, "本来就没注册"
    except Exception as e:
        return False, f"卸载失败：{e}"


def _read_current_value() -> str | None:
    """读取注册表 ClassSchedule 当前值。"""
    if winreg is None or os.name != "nt":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, APP_NAME)
            return val
    except (FileNotFoundError, OSError):
        return None


def ensure_registered() -> tuple[bool, str]:
    """
    启动时调用：确保注册表指向 backend_service.py。
    若值缺失或指向错误脚本，会自动修正。
    返回 (是否执行了写入, 消息)。
    """
    desired = get_command_for_backend()
    current = _read_current_value()

    if current == desired:
        return False, "已存在且正确（backend_service.py）"
    if current is None:
        ok, msg = register()
        return ok, msg
    # 有但不对 → 覆盖
    try:
        cmd = get_command_for_backend()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        return True, f"已更新注册表：{current} → {cmd}"
    except Exception as e:
        return False, f"更新注册表失败：{e}"


# ============================================================
# Backend 进程管理
# ============================================================
def is_backend_running() -> bool:
    """根据 PID 文件探活 backend_service.py（Windows 下用 tasklist）。"""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return False

    # Windows 原生探活：用 tasklist /FI "PID eq xxx"
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="mbcs", errors="replace",
                timeout=3,
            )
            # 输出第一列是 "xxx"，有值说明存在；"INFO: ..." 开头说明没有
            out = (r.stdout or "").strip()
            if not out:
                return False
            # CSV: "pythonw.exe","6428","Console","1","20.5M"
            return out.startswith('"')
        except Exception:
            return False

    # Linux/macOS 用 os.kill
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def backend_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def start_backend() -> tuple[bool, str]:
    """拉起 backend（打包后为 ClassSchedule_Backend.exe，隐藏控制台）。"""
    if is_backend_running():
        return True, f"backend 已在运行  PID={backend_pid()}"

    try:
        if getattr(sys, "frozen", False):
            if not BACKEND_EXE.exists():
                return False, f"后台程序不存在：{BACKEND_EXE}"
            subprocess.Popen([str(BACKEND_EXE)], cwd=str(APP_DIR))
        else:
            if not BACKEND_SCRIPT.exists():
                return False, f"backend_service.py 不存在：{BACKEND_SCRIPT}"
            subprocess.Popen(
                [_pythonw_true(), str(BACKEND_SCRIPT)],
                cwd=str(APP_DIR),
            )
        # 等 backend 自己写 PID 文件（最权威）
        import time
        time.sleep(0.8)
        real_pid = backend_pid()
        if real_pid and is_backend_running():
            return True, f"backend 已启动  PID={real_pid}"
        return True, "backend 已拉起（PID 文件写入延迟）"
    except Exception as e:
        return False, f"启动 backend 失败：{e}"


def stop_backend() -> tuple[bool, str]:
    """结束 backend 进程。"""
    pid = backend_pid()
    if pid is None:
        return True, "backend 没在运行"

    try:
        os.kill(pid, 15)  # SIGTERM
        import time
        time.sleep(1.5)
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        return True, f"已停止 backend  PID={pid}"
    except ProcessLookupError:
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception:
            pass
        return True, "PID 已不存在（进程自然退出）"
    except Exception as e:
        return False, f"停止失败：{e}"
