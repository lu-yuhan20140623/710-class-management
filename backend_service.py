"""
课程表后台常驻服务（进程独立运行，不靠 GUI 存活）
- 启动方式：pythonw.exe backend_service.py   （无控制台窗口）
- 职责：每秒刷新课节状态，在进入倒计时窗口时唤起 overlay 全屏窗口，离开时关闭
- 同时负责拉起桌面悬浮球进程并保活（悬浮球由此进程常驻，不随主界面退出）
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
import score_records

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
    OVERLAY_SCRIPT = APP_DIR / "ClassSchedule_Overlay.exe"
    BALL_SCRIPT = APP_DIR / "ClassSchedule_Ball.exe"
else:
    APP_DIR = Path(__file__).parent.resolve()
    OVERLAY_SCRIPT = APP_DIR / "overlay_window.py"
    BALL_SCRIPT = APP_DIR / "floating_ball_service.py"
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
        from ball_bridge import pid_alive
        return pid_alive(int(PID_FILE.read_text().strip()))
    except (ValueError, OSError):
        return False
    except Exception:
        return False


# ---------- Overlay 进程管理 ----------
# 策略：上课/预备铃期间常驻，每轮 poll 一次；窗口被误关后 5 秒内自动重新拉起
overlay_proc: subprocess.Popen | None = None
OVERLAY_RESTART_GAP = 5.0
_overlay_last_try = 0.0


def _child_cmd(script: Path) -> list:
    """子进程启动命令：打包后直接跑 exe，开发模式用 pythonw 跑脚本。"""
    if getattr(sys, "frozen", False):
        return [str(script)]
    import shutil
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = shutil.which("pythonw.exe") or shutil.which("pythonw") or sys.executable
    return [pyw, str(script)]


def ensure_overlay():
    """倒计时窗口探活：进程不在就重新拉起（最短间隔 5 秒，避免反复闪窗）。"""
    global overlay_proc, _overlay_last_try
    if overlay_proc is not None and overlay_proc.poll() is None:
        return
    if overlay_proc is not None:
        log(f"overlay 进程已退出（code={overlay_proc.returncode}），准备重启")
        overlay_proc = None
    if time.time() - _overlay_last_try < OVERLAY_RESTART_GAP:
        return
    _overlay_last_try = time.time()
    try:
        overlay_proc = subprocess.Popen(_child_cmd(OVERLAY_SCRIPT), cwd=str(APP_DIR))
        log(f"overlay 已启动  PID={overlay_proc.pid}")
    except Exception as e:
        log(f"spawn overlay 失败: {e}")
        overlay_proc = None


def kill_overlay():
    """关掉 overlay 进程。用 taskkill /F（最可靠）。"""
    global overlay_proc
    if overlay_proc is None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(overlay_proc.pid), "/T"],
            capture_output=True, timeout=5,
        )
        log(f"overlay 已终止  PID={overlay_proc.pid}")
    except Exception as e:
        log(f"kill overlay 异常: {e}")
    overlay_proc = None


# ---------- 悬浮球进程管理 ----------
# 与 overlay 不同：悬浮球要「保持常驻」，所以每轮 poll 一次，窗口被关掉几秒后自动拉起
ball_proc: subprocess.Popen | None = None
BALL_RESTART_GAP = 5.0
_ball_last_try = 0.0


def ensure_ball():
    """悬浮球进程不在就拉起（最短间隔 5 秒，避免反复闪窗）。"""
    global ball_proc, _ball_last_try
    if ball_proc is not None and ball_proc.poll() is None:
        return
    if ball_proc is not None:
        log(f"ball 进程已退出（code={ball_proc.returncode}），准备重启")
        ball_proc = None
    if time.time() - _ball_last_try < BALL_RESTART_GAP:
        return
    _ball_last_try = time.time()
    try:
        ball_proc = subprocess.Popen(_child_cmd(BALL_SCRIPT), cwd=str(APP_DIR))
        log(f"ball 已启动  PID={ball_proc.pid}")
    except Exception as e:
        log(f"spawn ball 失败: {e}")


def kill_ball():
    """backend 退出时一并关掉悬浮球（没人保活就没有存在的意义）。"""
    global ball_proc
    if ball_proc is None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(ball_proc.pid), "/T"],
            capture_output=True, timeout=5,
        )
        log(f"ball 已终止  PID={ball_proc.pid}")
    except Exception as e:
        log(f"kill ball 异常: {e}")
    ball_proc = None


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
    prev_should_have = False
    reset_check_gap = 20.0       # 每 20 秒检查一次是否到了卫生/积分重置时间
    last_reset_check = 0.0

    try:
        while running:
            # 每次循环都检查一次改密请求（GUI 不直接写密码文件）
            try:
                auth.process_password_requests()
            except Exception as e:
                log(f"处理改密请求异常: {e}")

            # 悬浮球常驻：不依赖上课状态，进程不在了就重新拉起
            ensure_ball()

            # 定时重置：卫生每天中午 12:00，积分每周一中午 12:00（重置前归档 XLSX）
            if time.time() - last_reset_check >= reset_check_gap:
                last_reset_check = time.time()
                try:
                    for msg in score_records.run_scheduled_resets():
                        log(msg)
                except Exception as e:
                    log(f"定时重置异常: {e}")

            try:
                info = sch.find_current_period()
            except Exception as e:
                log(f"find_current_period 异常: {e}")
                time.sleep(0.5)
                continue

            # 状态 key 变化 → 打条日志（prev_state_key 只在本轮处理完后再更新）
            key = (info["state"], info.get("next_period"), info.get("disabled"))
            state_changed = key != prev_state_key
            if state_changed:
                log(f"state 变化: {prev_state_key} → {key}")

            # === overlay 管理：状态驱动 + 探活 ===
            # 进入上课/预备铃时拉起，离开时关闭；运行期间每轮 poll 一次，
            # 被误关（进程退出）后 5 秒内自动重新拉起
            now_counting = info.get("is_counting", False)
            now_prebell = info.get("is_prebell", False)
            now_disabled = info.get("disabled", False)
            should_have = (now_counting or now_prebell) and not now_disabled

            if state_changed:
                log(f"[反应] should_have={should_have}  prev={prev_should_have} "
                    f"counting={now_counting} prebell={now_prebell}")
                if should_have:
                    ensure_overlay()
                else:
                    kill_overlay()
                prev_state_key = key
                prev_should_have = should_have
            elif should_have:
                ensure_overlay()      # 窗口被误关时自动拉起

            time.sleep(0.5)
    finally:
        kill_overlay()
        kill_ball()
        auth.unlock_password_file()
        clean_pid()
        log("backend 退出")


if __name__ == "__main__":
    main()
