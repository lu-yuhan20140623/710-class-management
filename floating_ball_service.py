"""
桌面悬浮球常驻服务（独立进程）
- 由 backend_service.py 拉起并保活，关闭窗口后几秒会自动重新出现
- 自身用 .ball.pid 防止重复启动
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import instance_guard

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
PID_FILE = APP_DIR / ".ball.pid"
LOG_FILE = APP_DIR / "ball.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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
    except Exception:
        return False


def main():
    if not instance_guard.acquire("Ball"):
        log("已有悬浮球实例在运行，退出。")
        return
    if is_already_running():
        log("已有悬浮球实例在运行，退出。")
        return

    write_pid()

    import tkinter as tk
    from ui import enable_high_dpi, _apply_ttk_theme

    # DPI 感知必须在创建窗口前设置，否则高分屏上整体发虚
    enable_high_dpi()
    root = tk.Tk()
    enable_high_dpi(root)
    _apply_ttk_theme(root)
    root.withdraw()                 # 主窗口隐藏，只显示悬浮球

    from floating_ball import FloatingBall
    ball = FloatingBall(root)
    root._ball = ball

    # 插件：悬浮球进程也加载一遍，插件注册的球菜单/图片皮肤/单击动作在这里生效
    try:
        import plugin_api
        plugin_api.init(app=root, ball=ball)
        plugin_api.load_all()
        log("插件加载完成：" + plugin_api.plugin_summary().replace("\n", " | "))
    except Exception:
        import traceback
        log("插件加载失败：" + traceback.format_exc())

    def _sync_plugin_states():
        """主界面随时启停插件，悬浮球这边定时跟进（开关写在共享配置文件里）。"""
        try:
            if "plugin_api" not in globals():
                return
            plugin_api.refresh_enabled_states()
        except Exception:
            import traceback
            log("插件开关同步失败：" + traceback.format_exc())
        root.after(2000, _sync_plugin_states)

    root.after(2000, _sync_plugin_states)

    def on_close():
        log("悬浮球窗口被关闭，进程退出（后台服务会自动重新拉起）")
        try:
            ball.destroy()
        finally:
            clean_pid()
            try:
                root.destroy()
            except tk.TclError:
                pass

    ball.win.protocol("WM_DELETE_WINDOW", on_close)
    log(f"悬浮球启动  PID={os.getpid()}")

    try:
        root.mainloop()
    finally:
        clean_pid()
        log("悬浮球退出")


if __name__ == "__main__":
    main()
