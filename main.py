"""
课程表 · 完整客户端入口
- 开机自启检查并修正注册表
- 本地 BackendService 线程（刷新右侧面板 + 网格高亮，不拉 overlay）
- ScheduleUI 主窗口：课程表网格 + 实时倒计时面板 + 时间调试工具
- overlay_window.py / 桌面悬浮球由 backend_service.py（独立常驻）负责拉起并保活
- 关闭时若本次改过系统时间会自动恢复北京时间
"""

import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

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
import instance_guard
import time_debug
import update_checker
from backend import BackendService
from ui import ScheduleUI, _apply_ttk_theme, enable_high_dpi


def _cli_report(text: str, error: bool = False):
    """命令行结果反馈：开发模式打印到控制台，打包后（无控制台）弹窗。"""
    print(text)
    if not getattr(sys, "frozen", False):
        return
    try:
        if error:
            messagebox.showerror("课程表", text)
        else:
            messagebox.showinfo("课程表", text)
    except Exception:
        pass


def _handle_cli() -> bool:
    """命令行模式：查看版本/哈希、应用补丁，不启动界面。"""
    args = sys.argv[1:]
    if "--version" in args:
        import version_manager
        _cli_report(version_manager.describe())
        return True
    if "--apply-patch" in args:
        idx = args.index("--apply-patch")
        if idx + 1 >= len(args):
            _cli_report("用法：ClassSchedule.exe --apply-patch <补丁.zip>", error=True)
            return True
        import updater
        ok, msg = updater.apply_patch(args[idx + 1])
        _cli_report(("✅ " if ok else "❌ ") + msg, error=not ok)
        return True
    return False


# ---------- 自动更新 ----------
def _relaunch_main(delay: int = 3):
    """退出后重新启动主程序（先等本进程释放单实例互斥体）。"""
    exe = Path(sys.executable)
    cmd = f'cmd /c ping -n {delay} 127.0.0.1 >nul & start "" "{exe}"'
    try:
        subprocess.Popen(cmd, shell=True, cwd=str(exe.parent),
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except Exception as e:
        print(f"[课程表] 重启失败：{e}")


def _restart_after_update(pending: dict):
    """setup 由安装程序装完后自行拉起；renew 直接替换代码，需要这里重启主界面。"""
    if (pending or {}).get("kind") != "setup":
        _relaunch_main()


def _apply_pending_update(pending: dict) -> tuple:
    """应用后台下载好的 renew 补丁或 setup 安装包。

    返回 (ok, 提示信息)；ok 时调用方应立即退出，更新流程会自动重启程序。
    """
    if not getattr(sys, "frozen", False):
        return False, "开发模式下不应用更新"
    path = Path(str(pending.get("path", "")))
    version = pending.get("version", "")
    if not path.exists():
        update_checker.clear_pending()
        return False, "更新文件不存在，请重新下载"

    if pending.get("kind") == "setup":
        # 交给安装程序静默覆盖；等本进程退出后再安装，完成后拉起后台服务和主界面
        exe = Path(sys.executable)
        backend_exe = exe.parent / "ClassSchedule_Backend.exe"
        cmd = (f'cmd /c ping -n 4 127.0.0.1 >nul & '
               f'start /wait "" "{path}" /SILENT /CLOSEAPPLICATIONS /NORESTART & '
               f'start "" "{backend_exe}" & start "" "{exe}"')
        try:
            subprocess.Popen(cmd, shell=True, cwd=str(exe.parent),
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except Exception as e:
            return False, f"启动安装程序失败：{e}"
        update_checker.clear_pending()
        return True, f"正在安装 {version}，完成后会自动重启"

    # 增量补丁：先停后台服务，替换代码后再拉起
    import updater
    try:
        autostart.stop_backend()
    except Exception:
        pass
    ok, msg = updater.apply_patch(path)
    if ok:
        update_checker.clear_pending()
        try:
            autostart.start_backend()
        except Exception:
            pass
    return ok, msg


def _show_update_error(root, msg: str, release_url: str):
    """更新失败：可重试下载，或打开发布页手动安装。"""
    retry = messagebox.askretrycancel(
        "自动更新失败",
        f"{msg}\n\n点「重试」重新下载；点「取消」打开发布页手动下载安装包。",
        parent=root)
    if not retry:
        webbrowser.open(release_url or update_checker.manual_download_hint())
        return

    def worker():
        try:
            manifest = update_checker.check(force=True)
            ok, text = (False, "暂时没有可用的新版本") if not manifest else update_checker.prepare(manifest)
        except Exception as exc:
            ok, text = False, f"重新下载失败：{exc}"

        def done():
            if not ok:
                messagebox.showerror("重试失败", text, parent=root)
                return
            pending = update_checker.load_pending()
            ok2, msg2 = _apply_pending_update(pending) if pending else (False, "下载结果丢失")
            if ok2:
                print(f"[课程表] {msg2}")
                root.destroy()
                _restart_after_update(pending)
            else:
                _show_update_error(root, msg2, update_checker.manual_download_hint(pending))

        root.after(0, done)

    threading.Thread(target=worker, daemon=True).start()


def main():
    try:
        import touch_keyboard
        touch_keyboard.install_global()
    except Exception:
        pass
    if _handle_cli():
        return
    # 0. 单实例：已有主界面在运行时，把它带到前台后退出
    if not instance_guard.acquire("Main"):
        if not instance_guard.activate_window("课程表 · 七年级10班"):
            _cli_report("课程表已经在运行，请勿重复打开。")
        return
    # 1. 开机自启注册（若缺失或指向错误脚本则自动修正为 backend_service.py）
    just_registered, msg = autostart.ensure_registered()
    if just_registered:
        print(f"[课程表] 自动注册开机自启：{msg}")
    else:
        print(f"[课程表] 开机自启：{msg}")

    # 1.5 上次改过系统时间但没恢复（崩溃/断电/强杀）→ 启动时自动校正
    if time_debug.time_was_modified():
        print("[课程表] 上次修改的系统时间未恢复，正在后台尝试校正…")
        threading.Thread(target=time_debug.auto_restore_if_needed, daemon=True).start()

    # 2. 本地 backend 线程 —— 仅负责右侧面板和网格高亮刷新
    #    overlay_window.py 的拉起由独立的 backend_service.py 负责
    backend = BackendService(tick_interval=0.5)
    backend.start()

    # 3. Tk 主窗口
    #    DPI 感知必须在创建窗口前设置，否则高分辨率屏上整体发虚
    enable_high_dpi()
    root = tk.Tk()
    enable_high_dpi(root)          # 按实际 DPI 调整字体缩放
    _apply_ttk_theme(root)

    # 2.5 自动更新：后台已下载好的更新，在进入身份选择前静默应用
    update_error = None
    if getattr(sys, "frozen", False):
        pending = update_checker.load_pending()
        if pending:
            ok, msg = _apply_pending_update(pending)
            if ok:
                print(f"[课程表] {msg}")
                backend.stop()
                root.destroy()
                _restart_after_update(pending)
                return
            update_checker.clear_pending()
            update_error = msg

    # 3. 身份选择（教师端 / 学生端 / 值日生端 / 查看信息）
    root.withdraw()
    import entry
    try:
        mode, payload = entry.choose(root)
    except Exception as e:
        messagebox.showerror("启动失败", f"身份选择界面加载失败：{e}", parent=root)
        backend.stop()
        root.destroy()
        return
    if mode is None:
        backend.stop()
        root.destroy()
        return
    if mode != "teacher":
        try:
            entry.open_target(root, mode, payload)
        except Exception as e:
            messagebox.showerror("启动失败", f"{e}", parent=root)
            backend.stop()
            root.destroy()
            return
        print(f"[课程表] 已以「{mode}」身份进入")
        try:
            root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            backend.stop()
        return

    ui = ScheduleUI(root, backend)
    root.deiconify()
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
        if (getattr(ui, "_system_time_modified", False)
                or getattr(root, "_system_time_modified", False)):
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

    # 6. 当天第一次启动：全屏展示卫生（周一上午同时展示上周积分）；并补做错过的定时重置
    def _show_hygiene_report():
        try:
            import score_records
            for msg in score_records.run_scheduled_resets():
                print(f"[课程表] {msg}")
        except Exception as e:
            print(f"[课程表] 定时重置检查失败：{e}")
        try:
            from hygiene import maybe_show_first_boot_report
            maybe_show_first_boot_report(root)
        except Exception as e:
            print(f"[课程表] 卫生扣分日报展示失败：{e}")

    root.after(600, _show_hygiene_report)

    # 6b. 每天首次启动：自动弹出小组积分统计图
    def _show_boot_chart():
        try:
            import charts
            import score_records as store
            students = store.load_students()
            groups = store.load_groups()
            rows = []
            for cls in sorted(set(students) | set(groups)):
                for gname, _count, total in store.points_group_rows(students, groups, cls):
                    rows.append((f"{cls}-{gname}", max(0, total), max(0, -total)))
            if not any(a or b for _, a, b in rows):
                return
            win = tk.Toplevel(root)
            win.title(f"小组积分统计 · {datetime.now().strftime('%m-%d')}")
            win.configure(bg="#2a2a3a")
            win.geometry("780x520")
            win.transient(root)
            charts.bar_chart(win, rows, width=740).pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            print(f"[课程表] 开机统计图展示失败：{e}")

    root.after(1200, _show_boot_chart)

    # 7. 自动更新：后台下载完成后静默应用并重启；失败则提示重试或手动下载
    if update_error:
        root.after(2000, lambda: _show_update_error(
            root, update_error, update_checker.manual_download_hint()))

    def _update_tick():
        if not getattr(sys, "frozen", False):
            return
        p = update_checker.load_pending()
        if p:
            ok, msg = _apply_pending_update(p)
            if ok:
                print(f"[课程表] {msg}")
                backend.stop()
                root.destroy()
                _restart_after_update(p)
                return
            update_checker.clear_pending()
            _show_update_error(root, msg, update_checker.manual_download_hint(p))
            return
        root.after(60_000, _update_tick)

    root.after(60_000, _update_tick)

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
