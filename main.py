"""
课程表 · 完整客户端入口
- 开机自启检查并修正注册表
- 本地 BackendService 线程（刷新右侧面板 + 网格高亮，不拉 overlay）
- ScheduleUI 主窗口：课程表网格 + 实时倒计时面板 + 时间调试工具
- overlay_window.py 由 backend_service.py（独立常驻）负责拉起
- 关闭时若本次改过系统时间会自动恢复北京时间
"""

import os
import sys

# PyInstaller 打包后 Windows 默认 stdout 是 gbk，emoji print 会炸
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import tkinter as tk
from tkinter import messagebox

import autostart
import time_debug
from backend import BackendService
from ui import ScheduleUI, _apply_ttk_theme


def main():
    # 1. 开机自启注册（若缺失或指向错误脚本则自动修正为 backend_service.py）
    just_registered, msg = autostart.ensure_registered()
    if just_registered:
        print(f"[课程表] 自动注册开机自启：{msg}")
    else:
        print(f"[课程表] 开机自启：{msg}")

    # 2. 本地 backend 线程 —— 仅负责右侧面板和网格高亮刷新
    #    overlay_window.py 的拉起由独立的 backend_service.py 负责
    backend = BackendService(tick_interval=0.5)
    backend.start()

    # 3. Tk 主窗口
    root = tk.Tk()
    _apply_ttk_theme(root)

    ui = ScheduleUI(root, backend)
    ui._system_time_modified = False   # 给关闭时恢复北京时间用

    # 提示 backend_service.py 状态
    if autostart.is_backend_running():
        pid = autostart.backend_pid()
        print(f"[课程表] backend_service.py 运行中  PID={pid}")
    else:
        print("[课程表] backend_service.py 未运行 —— 倒计时全屏不会自动弹出")
        print("[课程表]   点主界面右侧 '▶ 启动后台服务' 或让开机自启来启动它")

    # 4. 关闭钩子
    def on_close():
        # 若调时间工具改过系统时间，关窗时恢复
        if getattr(ui, "_system_time_modified", False):
            try:
                messagebox.showinfo("恢复系统时间",
                                    "检测到系统时间已被临时修改，正在恢复为北京时间…",
                                    parent=root)
            except Exception:
                pass
            ok, m = time_debug.restore_beijing_time()
            if not ok:
                try:
                    messagebox.showwarning("恢复失败",
                                           f"系统时间恢复失败：{m}\n请手动同步时间。",
                                           parent=root)
                except Exception:
                    pass

        backend.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # 5. 设置面板快捷入口（main.py 简化版）作为可选入口
    if len(sys.argv) >= 2 and sys.argv[1] == "--settings-only":
        # 用用户偏好的简化设置面板 —— 暂不实现，主界面已包含完整功能
        pass

    print("[课程表] 已启动 · 七年级10班 · 2026-2027 第一学期")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\n[课程表] 收到中断，正在退出…")
    finally:
        backend.stop()
        print("[课程表] 已退出")


if __name__ == "__main__":
    main()
