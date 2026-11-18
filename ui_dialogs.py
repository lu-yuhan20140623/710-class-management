"""Tkinter 对话框：时间调试、课程设置、局域网连接、密钥验证。"""
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

import auth
import autostart
import schedule_core as sch
from ui_theme import (
    BG_CELL, BG_CELL_ALT, BG_COUNTING, BG_DANGER, BG_IN_CLASS, BG_MAIN,
    BG_PANEL, BG_PREBELL, FG_ACCENT, FG_DANGER, FG_DIM, FG_OK, FG_TEXT, FG_WARN,
    center_window, dpi_scale,
)


class TimeDebugDialog:
    """
    时间调试工具 —— 临时修改系统时间，用于观察 backend_service.py
    是否按预期拉起 overlay_window.py。修改后不退出进程，
    关闭主窗口时自动恢复北京时间，避免系统时钟被永久改坏。
    """

    def __init__(self, parent):
        from datetime import datetime as dt_cls
        import time_debug

        self.win = tk.Toplevel(parent)
        self.root = parent
        self.win.title("时间调试工具")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(parent)
        self.win.grab_set()

        tk.Label(self.win, text="🕒 临时修改系统时间", font=("Microsoft YaHei UI", 14, "bold"),
                 bg=BG_MAIN, fg=FG_WARN).pack(pady=(16, 4))
        tk.Label(self.win,
                 text="设完后本进程会立刻退出，\n观察 backend_service.py 拉 overlay_window.py 全屏倒计时",
                 font=("Microsoft YaHei UI", 9), bg=BG_MAIN, fg=FG_DIM, justify=tk.CENTER)\
            .pack(pady=(0, 10))

        info = tk.Frame(self.win, bg=BG_PANEL)
        info.pack(fill=tk.X, padx=18, pady=4)
        tk.Label(info, text="当前系统时间", font=("Microsoft YaHei UI", 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(pady=(10, 2))
        self.now_label = tk.Label(info, text="", font=("Consolas", 18, "bold"),
                                  bg=BG_PANEL, fg=FG_ACCENT)
        self.now_label.pack(pady=(0, 10))

        form = tk.Frame(self.win, bg=BG_MAIN)
        form.pack(fill=tk.X, padx=18, pady=6)
        tk.Label(form, text="目标时间（HH:MM:SS  或  YYYY-MM-DD HH:MM:SS）",
                 font=("Microsoft YaHei UI", 9), bg=BG_MAIN, fg=FG_DIM)\
            .pack(anchor=tk.W, pady=(0, 4))
        self.entry = tk.Entry(form, font=("Consolas", 12), bg=BG_PANEL, fg=FG_TEXT,
                              insertbackground=FG_TEXT, relief=tk.FLAT)
        self.entry.pack(fill=tk.X, ipady=4, pady=(0, 4))
        self.entry.insert(0, dt_cls.now().strftime("%H:%M:%S"))

        quick = tk.Frame(self.win, bg=BG_MAIN)
        quick.pack(fill=tk.X, padx=18, pady=(8, 4))

        def fill_quick(offset: int, label: str):
            info = sch.find_current_period()
            target = None
            if info.get("next_start"):
                target = info["next_start"] - timedelta(minutes=offset)
            else:
                today = dt_cls.now().date()
                # 正课 + 午间小练 + 晚辅，全都能快速跳转到倒计时窗口
                for slot in sch.day_slots(dt_cls.now().weekday()):
                    t = dt_cls.combine(today, slot["start"]) - timedelta(minutes=offset)
                    if t > dt_cls.now():
                        target = t
                        break
            if target is None:
                return
            self.entry.delete(0, tk.END)
            self.entry.insert(0, target.strftime("%H:%M:%S"))
            self._status(f"已填入：{target.strftime('%H:%M:%S')}  —— {label}", FG_ACCENT)

        tk.Button(quick, text="课前 4 分（倒计开始）", width=18,
                  command=lambda: fill_quick(4, "backend 应立刻弹 overlay"),
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 9), pady=4, cursor="hand2")\
            .pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(quick, text="课前 2 分（预备铃）", width=16,
                  command=lambda: fill_quick(2, "预备铃，倒计时结束"),
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 9), pady=4, cursor="hand2")\
            .pack(side=tk.LEFT)

        # 卫生日报全屏效果预览（与每天首次开机时的展示完全一致）
        preview = tk.Frame(self.win, bg=BG_MAIN)
        preview.pack(fill=tk.X, padx=18, pady=(8, 0))
        tk.Button(preview, text="🖥 预览昨日卫生扣分（全屏）",
                  command=self._preview_hygiene,
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 9), pady=4,
                  cursor="hand2").pack(fill=tk.X)

        self.status_label = tk.Label(self.win, text="", font=("Microsoft YaHei UI", 9),
                                      bg=BG_MAIN, fg=FG_DANGER, wraplength=420, justify=tk.LEFT)
        self.status_label.pack(fill=tk.X, padx=18, pady=6)

        row = tk.Frame(self.win, bg=BG_MAIN)
        row.pack(fill=tk.X, padx=18, pady=(4, 4))

        def run_async(fn, ok_text, fail_prefix):
            """set/restore 可能弹 UAC，放到后台线程，避免卡死 Tk 主线程。"""
            for b in (btn_set, btn_restore):
                b.config(state=tk.DISABLED)
            self._status("正在处理…若弹出 UAC，请点击「是」", FG_WARN)

            def worker():
                try:
                    ok, msg = fn()
                except Exception as exc:          # pragma: no cover
                    ok, msg = False, str(exc)

                def done():
                    if not self.win.winfo_exists():
                        return
                    for b in (btn_set, btn_restore):
                        b.config(state=tk.NORMAL)
                    if ok:
                        self._status(ok_text(msg), "#66cc88")
                    else:
                        self._status(fail_prefix + msg, FG_DANGER)
                self.win.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        def apply_time():
            text = self.entry.get().strip()
            target = None
            for fmt in ("%H:%M:%S", "%H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    target = dt_cls.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if target is None:
                self._status("时间格式不正确", FG_DANGER)
                return
            if len(text) <= 8:
                target = dt_cls.combine(dt_cls.now().date(), target.time())

            def success(msg):
                # 关闭主窗口时由 main.on_close 恢复北京时间，绝不静默遗留错误时钟
                self.root._system_time_modified = True
                return ("✓ " + msg +
                        "\n后端会按新时间拉起 overlay；关闭主窗口即自动恢复北京时间")

            run_async(lambda: time_debug.set_system_time(target),
                      success, "✗ ")

        def restore_beijing():
            def success(msg):
                self.root._system_time_modified = False
                return "✓ " + msg + "\n系统时间已恢复，现在是北京时间"

            run_async(time_debug.restore_beijing_time, success, "✗ ")

        btn_set = tk.Button(row, text="🎯 设置系统时间", command=apply_time,
                            bg="#8b5a2b", fg=FG_TEXT, activebackground=BG_PREBELL,
                            relief=tk.FLAT, font=("Microsoft YaHei UI", 11, "bold"),
                            padx=14, pady=8, cursor="hand2")
        btn_set.pack(fill=tk.X, pady=(0, 6))
        btn_restore = tk.Button(row, text="🔄 恢复北京时间", command=restore_beijing,
                                bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                                relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                                padx=14, pady=6, cursor="hand2")
        btn_restore.pack(fill=tk.X)

        tk.Label(self.win,
                 text="提示：设置时间为系统级操作，普通用户会弹 UAC 确认。\n"
                      "修改后关闭主窗口会自动恢复北京时间。",
                 font=("Microsoft YaHei UI", 8),
                 bg=BG_MAIN, fg=FG_DIM, justify=tk.LEFT)\
            .pack(anchor=tk.W, padx=18, pady=(10, 14))

        # 内容建完后再按实际尺寸居中
        center_window(self.win, parent, 460, 540)

        self._tick()

    def _preview_hygiene(self):
        """调试用：全屏展示当前卫生扣分（与开机自动展示同一套界面）。"""
        try:
            import hygiene
        except Exception as exc:
            self._status(f"✗ 卫生模块加载失败：{exc}", FG_DANGER)
            return
        # 调试窗口是 grab 状态，先释放，日报关闭后恢复
        self.win.grab_release()
        report = hygiene.show_daily_report(self.root)
        if report is None:
            self._status("当前没有卫生扣分记录，无可展示内容", FG_WARN)
            try:
                self.win.grab_set()
            except tk.TclError:
                pass
            return
        self._status("已全屏展示昨天的卫生扣分（Esc 关闭）", FG_ACCENT)

        def restore(event):
            if event is not None and event.widget is not report:
                return
            try:
                if self.win.winfo_exists():
                    self.win.grab_set()
            except tk.TclError:
                pass

        report.bind("<Destroy>", restore)

    def _status(self, text: str, color: str = FG_DANGER):
        self.status_label.config(text=text, fg=color)

    def _tick(self):
        try:
            self.now_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        self.win.after(500, self._tick)


class SettingsDialog:
    """设置对话框：开机自启 + 禁用时间段管理。"""

    class _NullUI:
        """当 ScheduleUI 不存在时的空对象 fallback。"""
        def refresh_grid(self): pass
        def _set_status(self, msg): pass
        def _refresh_autostart_status(self): pass

    def __init__(self, root, backend, ui):
        self.root = root
        self.backend = backend
        self.ui = ui if ui is not None else self._NullUI()

        self.win = tk.Toplevel(root)
        self.win.title("课程设置")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(root)
        self.win.grab_set()

        notebook = ttk.Notebook(self.win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self._tab_autostart(notebook)
        self._tab_disabled(notebook)
        self._tab_override(notebook)
        self._tab_password(notebook)

        # 选项卡内容建完后再居中并按内容自适应尺寸
        center_window(self.win, root, 560, 560)

    # ---- Tab: 开机自启 ----
    def _tab_autostart(self, nb):
        tab = tk.Frame(nb, bg=BG_PANEL)
        nb.add(tab, text="开机自启")

        tk.Label(tab, text="开机自启动", font=("Microsoft YaHei UI", 14, "bold"),
                 bg=BG_PANEL, fg=FG_ACCENT).pack(pady=(16, 8))

        self.autostart_status = tk.Label(tab, text="", font=("Microsoft YaHei UI", 11),
                                         bg=BG_PANEL, fg=FG_DIM)
        self.autostart_status.pack(pady=6)

        self.autostart_cmd_label = tk.Label(tab, text="", font=("Consolas", 9),
                                            bg=BG_PANEL, fg=FG_DIM, wraplength=500,
                                            justify=tk.LEFT)
        self.autostart_cmd_label.pack(pady=6)

        btn_frame = tk.Frame(tab, bg=BG_PANEL)
        btn_frame.pack(pady=14)
        tk.Button(btn_frame, text="✓ 注册开机自启", command=self._do_register,
                  bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 11, "bold"),
                  padx=14, pady=6, cursor="hand2").pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_frame, text="✗ 卸载开机自启", command=self._do_unregister,
                  bg=BG_DANGER, fg=FG_TEXT, activebackground="#dd4444",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 11, "bold"),
                  padx=14, pady=6, cursor="hand2").pack(side=tk.LEFT)

        tk.Label(tab,
                 text="说明：使用注册表 HKCU\\...\\Run 实现，无需管理员权限。\n"
                      "打包为 exe 后将自动改为 exe 启动。",
                 font=("Microsoft YaHei UI", 9),
                 bg=BG_PANEL, fg=FG_DIM, justify=tk.LEFT).pack(pady=10)

        self._refresh_autostart_tab()

    def _refresh_autostart_tab(self):
        reg = autostart.is_registered()
        cmd = autostart.get_command()
        self.autostart_status.config(
            text="✓ 已注册" if reg else "未注册",
            fg="#66cc88" if reg else FG_WARN
        )
        self.autostart_cmd_label.config(text=f"命令：{cmd}")

    def _do_register(self):
        ok, msg = autostart.register()
        messagebox.showinfo("注册结果", msg, parent=self.win)
        self._refresh_autostart_tab()
        self.ui._refresh_autostart_status()

    def _do_unregister(self):
        ok, msg = autostart.unregister()
        messagebox.showinfo("卸载结果", msg, parent=self.win)
        self._refresh_autostart_tab()
        self.ui._refresh_autostart_status()

    # ---- Tab: 禁用时间段 ----
    def _tab_disabled(self, nb):
        tab = tk.Frame(nb, bg=BG_PANEL)
        nb.add(tab, text="禁用时间段")

        tk.Label(tab, text="禁用时间段（整个程序暂停提醒）",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 bg=BG_PANEL, fg=FG_WARN).pack(anchor=tk.W, padx=14, pady=(14, 6))
        tk.Label(tab, text="例：期中考试 2026-11-15 08:00 ~ 2026-11-17 17:00",
                 font=("Microsoft YaHei UI", 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(anchor=tk.W, padx=14, pady=(0, 8))

        list_frame = tk.Frame(tab, bg=BG_CELL)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=4)

        tree = ttk.Treeview(list_frame, columns=("start", "end", "note"), show="headings", height=8)
        tree.heading("start", text="开始")
        tree.heading("end", text="结束")
        tree.heading("note", text="备注")
        k = dpi_scale(self.win)
        tree.column("start", width=int(140 * k))
        tree.column("end", width=int(140 * k))
        tree.column("note", width=int(160 * k))
        tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=4, pady=4)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=sb.set)

        def refresh():
            for iid in tree.get_children():
                tree.delete(iid)
            for r in self.backend.get_all_disabled_ranges():
                tree.insert("", tk.END, values=(
                    r["start"].strftime("%Y-%m-%d %H:%M"),
                    r["end"].strftime("%Y-%m-%d %H:%M"),
                    r.get("note", ""),
                ))

        refresh()

        # 新增
        add_frame = tk.Frame(tab, bg=BG_PANEL)
        add_frame.pack(fill=tk.X, padx=14, pady=8)

        tk.Label(add_frame, text="开始", bg=BG_PANEL, fg=FG_DIM).grid(row=0, column=0, sticky="w")
        tk.Label(add_frame, text="结束", bg=BG_PANEL, fg=FG_DIM).grid(row=0, column=2, sticky="w", padx=(10, 0))

        e_start = tk.Entry(add_frame, width=18, bg=BG_CELL, fg=FG_TEXT,
                           insertbackground=FG_TEXT, relief=tk.FLAT)
        e_end = tk.Entry(add_frame, width=18, bg=BG_CELL, fg=FG_TEXT,
                         insertbackground=FG_TEXT, relief=tk.FLAT)
        e_note = tk.Entry(add_frame, width=20, bg=BG_CELL, fg=FG_TEXT,
                          insertbackground=FG_TEXT, relief=tk.FLAT)
        e_start.grid(row=1, column=0, padx=(0, 4), pady=4)
        e_end.grid(row=1, column=2, padx=(10, 4), pady=4)
        e_note.grid(row=1, column=4, padx=(10, 0), pady=4)

        # 默认值：今天开始，明天结束
        now = datetime.now()
        e_start.insert(0, now.strftime("%Y-%m-%d %H:%M"))
        e_end.insert(0, (now.replace(hour=17, minute=0) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"))

        tk.Label(add_frame, text="格式 YYYY-MM-DD HH:MM", bg=BG_PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 8)).grid(row=2, column=0, columnspan=3, sticky="w")
        tk.Label(add_frame, text="备注", bg=BG_PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).grid(row=0, column=4, sticky="w")

        def do_add():
            try:
                s = datetime.strptime(e_start.get().strip(), "%Y-%m-%d %H:%M")
                e = datetime.strptime(e_end.get().strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                messagebox.showerror("格式错误", "日期格式应为 YYYY-MM-DD HH:MM", parent=self.win)
                return
            note = e_note.get().strip()
            ok = self.backend.add_disabled_range(s, e, note)
            if ok:
                e_start.delete(0, tk.END); e_end.delete(0, tk.END); e_note.delete(0, tk.END)
                self.ui.refresh_grid()
                refresh()
                self.ui._set_status("已添加禁用时间段")
            else:
                messagebox.showerror("失败", "结束时间必须晚于开始时间", parent=self.win)

        def do_remove():
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            if self.backend.remove_disabled_range(idx):
                refresh()
                self.ui.refresh_grid()
                self.ui._set_status("已删除禁用时间段")

        btn_row = tk.Frame(tab, bg=BG_PANEL)
        btn_row.pack(fill=tk.X, padx=14, pady=(4, 12))
        tk.Button(btn_row, text="➕ 添加", command=do_add,
                  bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="🗑 删除所选", command=do_remove,
                  bg=BG_DANGER, fg=FG_TEXT, activebackground="#dd4444",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT)

    # ---- Tab: 清除临时调课 ----
    def _tab_override(self, nb):
        tab = tk.Frame(nb, bg=BG_PANEL)
        nb.add(tab, text="临时调课")

        tk.Label(tab, text="当前临时调课记录",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 bg=BG_PANEL, fg=FG_ACCENT).pack(anchor=tk.W, padx=14, pady=(14, 6))

        tree = ttk.Treeview(tab, columns=("key", "subject"), show="headings", height=10)
        tree.heading("key", text="节次")
        tree.heading("subject", text="临时科目")
        k = dpi_scale(self.win)
        tree.column("key", width=int(100 * k))
        tree.column("subject", width=int(200 * k))
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        def refresh():
            for iid in tree.get_children():
                tree.delete(iid)
            for k, v in self.backend.get_all_overrides().items():
                d, p = k.split("-")
                tree.insert("", tk.END, values=(f"{sch.WEEKDAY_NAMES[int(d)]} 第{p}节", v))

        refresh()

        def do_clear_one():
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            overrides = self.backend.get_all_overrides()
            k = list(overrides.keys())[idx]
            d, p = k.split("-")
            self.backend.override(int(d), int(p), "")
            refresh()
            self.ui.refresh_grid()
            self.ui._set_status("已清除调课")

        def do_clear_all():
            if not messagebox.askyesno("确认", "清除全部临时调课？", parent=self.win):
                return
            for k in list(self.backend.get_all_overrides().keys()):
                d, p = k.split("-")
                self.backend.override(int(d), int(p), "")
            refresh()
            self.ui.refresh_grid()
            self.ui._set_status("已清除全部临时调课")

        btn_row = tk.Frame(tab, bg=BG_PANEL)
        btn_row.pack(fill=tk.X, padx=14, pady=10)
        tk.Button(btn_row, text="🗑 清除所选", command=do_clear_one,
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="✕ 清除全部", command=do_clear_all,
                  bg=BG_DANGER, fg=FG_TEXT, activebackground="#dd4444",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT)

    # ---- Tab: 修改密钥 ----
    def _tab_password(self, nb):
        tab = tk.Frame(nb, bg=BG_PANEL)
        nb.add(tab, text="密钥管理")

        tk.Label(tab, text="修改密钥",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 bg=BG_PANEL, fg=FG_ACCENT).pack(anchor=tk.W, padx=14, pady=(14, 2))

        status_text = "当前密钥：默认（710），建议尽快修改" if auth.is_default() else "当前密钥：已自定义"
        status_fg = FG_WARN if auth.is_default() else FG_OK
        self._pw_status = tk.Label(tab, text=status_text, font=("Microsoft YaHei UI", 9),
                                   bg=BG_PANEL, fg=status_fg)
        self._pw_status.pack(anchor=tk.W, padx=14, pady=(0, 12))

        form = tk.Frame(tab, bg=BG_PANEL)
        form.pack(padx=14, pady=4, fill=tk.X)

        def row(parent, label):
            c = tk.Frame(parent, bg=BG_PANEL)
            c.pack(fill=tk.X, pady=4)
            tk.Label(c, text=label, width=12, anchor="w", bg=BG_PANEL, fg=FG_TEXT,
                     font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
            e = tk.Entry(c, show="●", width=28, font=("Consolas", 11),
                         bg=BG_CELL, fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)
            e.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
            return e

        e_old = row(form, "旧密钥")
        e_new = row(form, "新密钥")
        e_cnf = row(form, "确认新密钥")

        msg = tk.Label(tab, text="", font=("Microsoft YaHei UI", 10),
                       bg=BG_PANEL, fg=FG_DANGER)
        msg.pack(pady=(8, 4))

        def do_change():
            old = e_old.get().strip()
            new = e_new.get().strip()
            cnf = e_cnf.get().strip()
            if not old:
                msg.config(text="请输入旧密钥"); return
            if not new:
                msg.config(text="请输入新密钥"); return
            if len(new) < 1:
                msg.config(text="新密钥不能为空"); return
            if new != cnf:
                msg.config(text="两次输入的新密钥不一致"); return

            # 改密要等后台响应，放到后台线程做，避免界面卡住
            msg.config(text="正在提交…", fg=FG_DIM)
            save_btn.config(state=tk.DISABLED)
            result = {}

            def worker():
                try:
                    result["r"] = auth.change_password(old, new)
                except Exception as exc:
                    result["r"] = (False, f"提交失败：{exc}")

            def poll():
                if "r" not in result:
                    self.win.after(100, poll)
                    return
                ok, reason = result["r"]
                save_btn.config(state=tk.NORMAL)
                if ok:
                    msg.config(text="✓ 密钥已更新", fg=FG_OK)
                    for e in (e_old, e_new, e_cnf):
                        e.delete(0, tk.END)
                    # 只刷新状态文字：原先销毁整页再 nb.add 会多出一个空的“密钥管理”选项卡
                    if auth.is_default():
                        self._pw_status.config(text="当前密钥：默认（710），建议尽快修改", fg=FG_WARN)
                    else:
                        self._pw_status.config(text="当前密钥：已自定义", fg=FG_OK)
                else:
                    msg.config(text=f"✗ {reason}", fg=FG_DANGER)

            threading.Thread(target=worker, daemon=True).start()
            self.win.after(100, poll)

        save_btn = tk.Button(tab, text="💾 保存新密钥", command=do_change,
                             bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                             relief=tk.FLAT, font=("Microsoft YaHei UI", 10, "bold"),
                             padx=20, pady=6, cursor="hand2")
        save_btn.pack(pady=(10, 4))

        # ---- 手机号绑定：忘记密钥时凭手机号重置（无需验证码） ----
        import roles
        tk.Frame(tab, bg=BG_CELL, height=1).pack(fill=tk.X, padx=14, pady=(14, 10))
        phone_row = tk.Frame(tab, bg=BG_PANEL)
        phone_row.pack(fill=tk.X, padx=14, pady=2)
        tk.Label(phone_row, text="绑定手机号", width=12, anchor="w", bg=BG_PANEL,
                 fg=FG_TEXT, font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        e_phone = tk.Entry(phone_row, width=26, font=("Consolas", 11), bg=BG_CELL,
                           fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)
        e_phone.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        e_phone.insert(0, roles.get_phone())
        phone_msg = tk.Label(tab, text="用于教师端、学生端、值日生端忘记密钥时重置",
                             font=("Microsoft YaHei UI", 9), bg=BG_PANEL, fg=FG_DIM)
        phone_msg.pack(anchor=tk.W, padx=14, pady=(4, 2))

        def save_phone():
            ok, m = roles.set_phone(e_phone.get())
            phone_msg.config(text=("✓ " if ok else "✗ ") + m,
                             fg=FG_OK if ok else FG_DANGER)

        tk.Button(tab, text="📱 保存手机号", command=save_phone,
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=16, pady=5, cursor="hand2").pack(pady=(4, 12))


class LanDialog:
    """局域网直连：显示手机访问地址；服务由常驻后台进程提供。"""

    def __init__(self, root):
        import lan_server
        self.lan = lan_server
        self.root = root

        self.win = tk.Toplevel(root)
        self.win.title("局域网连接 · 课程表")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(root)
        self.win.grab_set()

        tk.Label(self.win, text="手机查看课表与积分",
                 font=("Microsoft YaHei UI", 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(18, 2))
        tk.Label(self.win, text="手机与电脑连接同一个 Wi-Fi，用手机浏览器打开下面的地址",
                 font=("Microsoft YaHei UI", 9), bg=BG_MAIN, fg=FG_DIM).pack()

        self.status_label = tk.Label(self.win, text="", font=("Microsoft YaHei UI", 10),
                                     bg=BG_MAIN, fg=FG_DIM)
        self.status_label.pack(pady=(12, 6))

        box = tk.Frame(self.win, bg=BG_PANEL, highlightbackground=BG_CELL, highlightthickness=1)
        box.pack(fill=tk.X, padx=24)
        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(box, textvariable=self.url_var, font=("Consolas", 13),
                                  bg=BG_CELL, fg=FG_TEXT, readonlybackground=BG_CELL,
                                  relief=tk.FLAT, justify=tk.CENTER)
        self.url_entry.pack(fill=tk.X, padx=12, pady=12, ipady=6)
        self.url_entry.config(state="readonly")

        btns = tk.Frame(self.win, bg=BG_MAIN)
        btns.pack(pady=10)
        self._btn(btns, "复制地址", self._copy).pack(side=tk.LEFT, padx=4)
        self._btn(btns, "在电脑上预览", self._preview).pack(side=tk.LEFT, padx=4)
        self.start_btn = self._btn(btns, "启动后台服务", self._start, primary=True)
        self.start_btn.pack(side=tk.LEFT, padx=4)

        self.detail = tk.Label(self.win, text="", font=("Microsoft YaHei UI", 9),
                               bg=BG_MAIN, fg=FG_DIM, justify=tk.LEFT, wraplength=470)
        self.detail.pack(fill=tk.X, padx=24, pady=(10, 4))

        tk.Label(self.win,
                 text="提示：首次启动时若 Windows 弹出防火墙提示，请选择“允许访问”。\n"
                      "数据接口只读，不需要密钥；请只在可信的教室局域网内使用。",
                 font=("Microsoft YaHei UI", 9), bg=BG_MAIN, fg=FG_WARN,
                 justify=tk.LEFT, wraplength=470).pack(fill=tk.X, padx=24, pady=(4, 8))

        tk.Button(self.win, text="关闭", command=self.win.destroy,
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=22, pady=6, cursor="hand2").pack(pady=(4, 16))

        center_window(self.win, root, 560, 430)
        self._refresh()

    def _btn(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd,
                         bg=BG_IN_CLASS if primary else BG_CELL,
                         fg=FG_TEXT,
                         activebackground="#4b7b4b" if primary else BG_CELL_ALT,
                         relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                         padx=14, pady=5, cursor="hand2")

    def _probe(self):
        """确认本机 8765 端口上是否已有服务在响应。"""
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.lan.configured_port()}/api/ping",
                    timeout=1.5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _refresh(self):
        url = self.lan.base_url()
        self.url_var.set(url)
        info = self._probe()
        if info:
            self.status_label.config(
                text=f"● 服务运行中 · {info.get('class_name', '')} · 版本 {info.get('version', '')}",
                fg=FG_OK)
            self.start_btn.config(state=tk.DISABLED)
            self.detail.config(
                text=f"完整数据：{url}/api/snapshot\n"
                     f"实时推送：{url}/api/events（数据一有变化就下发）")
        else:
            self.status_label.config(text="○ 服务未启动（局域网由后台服务提供，可点“启动后台服务”）",
                                     fg=FG_WARN)
            self.start_btn.config(state=tk.NORMAL)
            self.detail.config(text="启动后，手机即可读取课表、当前课节、小组积分和卫生扣分。\n"
                                    "服务由常驻后台进程提供，关闭本窗口后手机仍可继续访问。")

        if self.lan.lan_ip().startswith("127."):
            self.detail.config(text=self.detail.cget("text") +
                               "\n未检测到局域网地址，请确认电脑已连接 Wi-Fi 或网线。")

    def _copy(self):
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(self.url_var.get())
            self.status_label.config(text="地址已复制到剪贴板", fg=FG_ACCENT)
        except tk.TclError:
            pass

    def _preview(self):
        import webbrowser
        webbrowser.open(self.url_var.get())

    def _start(self):
        # 局域网端口只由常驻后台进程提供，GUI 进程不绑定，避免关闭窗口后手机断连
        if self._probe():
            self._refresh()
            return
        import autostart
        ok, msg = autostart.start_backend()
        if not ok:
            messagebox.showwarning("局域网连接", msg, parent=self.win)
            return
        import time
        deadline = time.time() + 8
        while time.time() < deadline:
            if self._probe():
                self._refresh()
                return
            time.sleep(0.4)
        self._refresh()
        messagebox.showwarning(
            "局域网连接",
            f"后台服务已启动，但 {self.lan.configured_port()} 端口暂未响应。\n"
            "请稍等几秒后重新打开本窗口。",
            parent=self.win)


class AskPasswordDialog:
    """
    密码验证弹窗。
    用法：if AskPasswordDialog(parent, "请输入密钥").result: ...
    """

    def __init__(self, parent, prompt: str = "请输入密钥"):
        self.result = None
        self.win = tk.Toplevel(parent)
        self.win.title("密钥验证")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(parent)
        self.win.grab_set()

        tk.Label(self.win, text="🔐 密钥验证", font=("Microsoft YaHei UI", 13, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(18, 4))
        tk.Label(self.win, text=prompt, font=("Microsoft YaHei UI", 10),
                 bg=BG_MAIN, fg=FG_TEXT).pack(pady=(0, 6))

        self.entry = tk.Entry(self.win, show="●", font=("Consolas", 12),
                              bg=BG_PANEL, fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)
        self.entry.pack(padx=30, pady=6, fill=tk.X, ipady=5)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self._ok())

        self.err = tk.Label(self.win, text="", font=("Microsoft YaHei UI", 9),
                            bg=BG_MAIN, fg=FG_DANGER)
        self.err.pack(pady=(0, 4))

        btn_row = tk.Frame(self.win, bg=BG_MAIN)
        btn_row.pack(pady=6)
        tk.Button(btn_row, text="确认", command=self._ok,
                  bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10, "bold"),
                  padx=20, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_row, text="取消", command=self._cancel,
                  bg=BG_PANEL, fg=FG_TEXT, activebackground=BG_CELL,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=20, pady=4, cursor="hand2").pack(side=tk.LEFT)

        # 控件创建完之后再按内容自适应，避免高 DPI 下按钮被裁掉
        center_window(self.win, parent, 360, 190)

        self.win.wait_window()

    def _ok(self):
        pwd = self.entry.get()
        if auth.verify(pwd):
            self.result = True
            self.win.destroy()
        else:
            self.err.config(text="✗ 密钥不正确")
            self.entry.select_range(0, tk.END)
            self.entry.focus_set()

    def _cancel(self):
        self.result = False
        self.win.destroy()
