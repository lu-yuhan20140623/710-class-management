"""
课程表后台常驻服务（进程独立运行，不靠 GUI 存活）
- 启动方式：pythonw.exe backend_service.py   （无控制台窗口）
- 职责：每秒刷新课节状态，在进入倒计时窗口时唤起 overlay 全屏窗口，离开时关闭
- 与设置面板 (main.py) 通过共享的 json 文件通信，零 IPC
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime

import schedule as sch
import auth

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
    OVERLAY_SCRIPT = APP_DIR / "ClassSchedule_Overlay.exe"
else:
    APP_DIR = Path(__file__).parent.resolve()
    OVERLAY_SCRIPT = APP_DIR / "overlay_window.py"
PID_FILE = APP_DIR / ".backend.pid"    # 自己的 PID 文件（可选）
LOG_FILE = APP_DIR / "backend.log"     # 简易日志


# ---------- 日志 ----------
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------- PID 文件 ----------
def write_pid():
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def clean_pid():
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


def is_already_running() -> bool:
    """PID 文件存在且里面那个 PID 的进程还活着。"""
    try:
        if not PID_FILE.exists():
            return False
        pid = int(PID_FILE.read_text().strip())
        # Windows 下 os.kill(pid, 0) 也能用来探活
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError, PermissionError):
        return False
    except Exception:
        return False


# ---------- Overlay 进程管理 ----------
# 策略：spawn 后相信它活着（记 PID），只有 schedule 状态变化才 kill
# 不做进程探活（tasklist 在时间跳退时可能卡住/返回假阴性）
overlay_pid: int | None = None


def spawn_overlay():
    """拉起 overlay_window.py。"""
    global overlay_pid
    if overlay_pid is not None:
        log(f"已有 overlay_pid={overlay_pid}，跳过 spawn（状态变化后会先 kill 再 spawn）")
        return

    try:
        if getattr(sys, "frozen", False):
            cmd = [str(OVERLAY_SCRIPT)]
            tag = "exe"
        else:
            import shutil
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pyw):
                pyw = shutil.which("pythonw.exe") or shutil.which("pythonw") or sys.executable
            cmd = [pyw, str(OVERLAY_SCRIPT)]
            tag = pyw
        proc = subprocess.Popen(cmd, cwd=str(APP_DIR))
        overlay_pid = proc.pid
        log(f"overlay 已启动  PID={overlay_pid}  {tag}")
    except Exception as e:
        log(f"spawn overlay 失败: {e}")
        overlay_pid = None


def kill_overlay():
    """关掉 overlay 进程。用 taskkill /F（最可靠）。"""
    global overlay_pid
    if overlay_pid is None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(overlay_pid), "/T"],
            capture_output=True, timeout=5,
        )
        log(f"overlay 已终止  PID={overlay_pid}")
    except Exception as e:
        log(f"kill overlay 异常: {e}")
    overlay_pid = None


# ---------- 主循环 ----------
running = True


def handle_sigterm(signum, frame):
    global running
    log("收到退出信号，正在停机…")
    running = False


def main():
    global running

    # 防重复启动
    if is_already_running():
        log("已有 backend 实例在运行，退出。")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)

    write_pid()
    log(f"backend 启动  PID={os.getpid()}")

    # 锁定密码文件：其他进程只能读，写/删/改名全部拒绝
    ok, lock_msg = auth.lock_password_file()
    log(f"密码文件锁定：{lock_msg}")
    if not ok:
        log("警告：密码文件未能锁定，改密请求仍会由本进程处理")

    prev_state_key = None
    prev_counting = False
    prev_prebell = False
    prev_in_class = False
    prev_disabled = False
    prev_should_have = False

    try:
        while running:
            # 每次循环都检查一次改密请求（GUI 不直接写密码文件）
            try:
                auth.process_password_requests()
            except Exception as e:
                log(f"处理改密请求异常: {e}")

            try:
                info = sch.find_current_period()
            except Exception as e:
                log(f"find_current_period 异常: {e}")
                time.sleep(0.5)
                continue

            # 状态 key 变化 → 打条日志
            key = (info["state"], info.get("next_period"), info.get("disabled"))
            if key != prev_state_key:
                log(f"state 变化: {prev_state_key} → {key}")
                prev_state_key = key

            # === overlay 管理：纯状态驱动 ===
            # 只有 schedule 状态变化时才判断要不要 spawn/kill
            # 平时不做进程探活（Windows 上探活容易卡住/误判）
            now_counting = info.get("is_counting", False)
            now_prebell = info.get("is_prebell", False)
            now_disabled = info.get("disabled", False)
            should_have = (now_counting or now_prebell) and not now_disabled

            # 状态没变就不动（避免每 0.5s 做无意义检查）
            if key == prev_state_key and should_have == prev_should_have:
                time.sleep(0.5)
                continue

            log(f"[反应] should_have={should_have}  prev={prev_should_have} "
                f"overlay_pid={overlay_pid}  counting={now_counting} prebell={now_prebell}")

            if now_disabled:
                kill_overlay()
            elif should_have:
                if overlay_pid is None:
                    spawn_overlay()
            else:
                kill_overlay()

            prev_should_have = should_have
            prev_counting = now_counting
            prev_prebell = now_prebell

            time.sleep(0.5)
    finally:
        kill_overlay()
        auth.unlock_password_file()
        clean_pid()
        log("backend 退出")


if __name__ == "__main__":
    main()
