"""
Tkinter 主界面
- 触摸屏友好：左键弹出菜单、无右键依赖
- 左侧：课程表网格（左键点单元格 → 弹出菜单：调课 / 取消调课）
- 右侧：实时状态面板 + 倒计时 + 设置按钮
- 底部：开机自启状态
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime, timedelta
from pathlib import Path
import os
import threading

import schedule as sch
import autostart
import auth

# ---------- 颜色主题 ----------
BG_MAIN      = "#1e1e2e"
BG_PANEL     = "#2a2a3a"
BG_CELL      = "#3a3a4a"
BG_CELL_ALT  = "#444458"
BG_IN_CLASS  = "#3b6b3b"
BG_COUNTING  = "#8b5a2b"
BG_PREBELL   = "#b5651d"
BG_DANGER    = "#4a1e1e"
FG_TEXT      = "#e8e8f0"
FG_DIM       = "#9090a0"
FG_ACCENT    = "#7ab8ff"
FG_WARN      = "#ffcc66"
FG_DANGER    = "#ff6b6b"
FG_OK        = "#66cc88"   # 成功/已自定义密码用
FG_SUBJECT   = "#66cc88"   # 课程标题/上课中用（绿色）


class ScheduleUI:
    def __init__(self, root: tk.Tk, backend):
        self.root = root
        self.backend = backend

        root.title("课程表 · 七年级10班")
        root.geometry("1100x680")
        root.configure(bg=BG_MAIN)
        root.minsize(1000, 600)

        self._cell_map = {}
        self._debug_win = None
        self._menu_win = None  # 单元格操作菜单窗口

        self._build_ui()
        self._wire_events()

        # 初始渲染：把科目名字填进单元格
        self.refresh_grid()
        self._apply_current_colors()

        # 开机自启状态检查
        self._refresh_autostart_status()

        # 启动主循环 tick
        self._tick()

    # ========== UI 构建 ==========
    def _build_ui(self):
        # 顶部标题栏
        top = tk.Frame(self.root, bg=BG_MAIN)
        top.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(top, text="课程表", font=("Microsoft YaHei UI", 20, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        tk.Label(top, text="2026–2027 第一学期 · 七年级10班",
                 font=("Microsoft YaHei UI", 10), bg=BG_MAIN, fg=FG_DIM)\
            .pack(side=tk.LEFT, padx=14)
        self.clock_label = tk.Label(top, text="", font=("Consolas", 12),
                                    bg=BG_MAIN, fg=FG_DIM)
        self.clock_label.pack(side=tk.RIGHT)

        # 主体：左课程表 + 右侧面板
        body = tk.Frame(self.root, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        self._build_schedule_panel(body)
        self._build_side_panel(body)

        # 底部状态
        bottom = tk.Frame(self.root, bg=BG_MAIN)
        bottom.pack(fill=tk.X, padx=16, pady=(4, 10))
        self.status_label = tk.Label(bottom, text="就绪",
                                     font=("Microsoft YaHei UI", 9),
                                     bg=BG_MAIN, fg=FG_DIM)
        self.status_label.pack(side=tk.LEFT)

        self.autostart_label = tk.Label(bottom, text="",
                                        font=("Microsoft YaHei UI", 9),
                                        bg=BG_MAIN, fg=FG_DIM, cursor="hand2")
        self.autostart_label.pack(side=tk.RIGHT)
        self.autostart_label.bind("<Button-1>", lambda e: self._open_settings())

    def _build_schedule_panel(self, parent):
        frame = tk.Frame(parent, bg=BG_PANEL, highlightbackground=BG_CELL, highlightthickness=1)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(frame, text="本周课程表（左键点击课程操作）",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor=tk.W, padx=10, pady=(10, 4))

        grid = tk.Frame(frame, bg=BG_PANEL)
        grid.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        days = sch.WEEKDAY_NAMES[:5]
        periods = list(range(1, 8))

        tk.Label(grid, text="", width=9, bg=BG_PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, padx=1, pady=1)
        for col, p in enumerate(periods, start=1):
            s, e = sch.PERIODS[p]
            tk.Label(grid, text=f"第{p}节\n{s.strftime('%H:%M')}",
                     bg=BG_PANEL, fg=FG_DIM,
                     font=("Microsoft YaHei UI", 8, "bold")).grid(row=0, column=col,
                                                                   padx=1, pady=1, sticky="nsew")

        for row, day in enumerate(days, start=1):
            day_idx = row - 1
            tk.Label(grid, text=day, width=9, bg=BG_PANEL, fg=FG_DIM,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(row=row, column=0,
                                                                   padx=1, pady=1, sticky="nsew")
            for col, p in enumerate(periods, start=1):
                cell = tk.Label(grid, text="", bg=BG_CELL, fg=FG_TEXT,
                                font=("Microsoft YaHei UI", 11),
                                width=9, height=2, cursor="hand2")
                cell.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")
                self._cell_map[(day_idx, p)] = cell
                cell.bind("<Button-1>", lambda e, d=day_idx, pr=p, w=cell: self._on_cell_click(e, d, pr, w))

        for c in range(len(periods) + 1):
            grid.columnconfigure(c, weight=1, uniform="col")
        for r in range(len(days) + 1):
            grid.rowconfigure(r, weight=1, uniform="row")

        tk.Label(frame, text="📱 触摸屏：左键点任意课程 → 弹出操作菜单",
                 font=("Microsoft YaHei UI", 8), bg=BG_PANEL, fg=FG_DIM)\
            .pack(anchor=tk.W, padx=10, pady=(2, 8))

    def _build_side_panel(self, parent):
        frame = tk.Frame(parent, bg=BG_PANEL, width=300, highlightbackground=BG_CELL, highlightthickness=1)
        frame.pack(side=tk.RIGHT, fill=tk.Y)
        frame.pack_propagate(False)

        tk.Label(frame, text="实时状态", font=("Microsoft YaHei UI", 12, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor=tk.W, padx=14, pady=(12, 4))

        # 状态卡片
        self.state_card = tk.Frame(frame, bg=BG_CELL)
        self.state_card.pack(fill=tk.X, padx=14, pady=6)
        self.state_title = tk.Label(self.state_card, text="—",
                                    font=("Microsoft YaHei UI", 14, "bold"),
                                    bg=BG_CELL, fg=FG_TEXT)
        self.state_title.pack(pady=(12, 2))
        self.state_subject = tk.Label(self.state_card, text="—",
                                      font=("Microsoft YaHei UI", 22, "bold"),
                                      bg=BG_CELL, fg=FG_ACCENT)
        self.state_subject.pack(pady=4)
        self.state_time = tk.Label(self.state_card, text="",
                                   font=("Consolas", 11),
                                   bg=BG_CELL, fg=FG_DIM)
        self.state_time.pack(pady=(0, 12))

        # 倒计时卡
        self.countdown_card = tk.Frame(frame, bg=BG_CELL)
        self.countdown_card.pack(fill=tk.X, padx=14, pady=6)
        tk.Label(self.countdown_card, text="距离下节课",
                 font=("Microsoft YaHei UI", 10), bg=BG_CELL, fg=FG_DIM)\
            .pack(pady=(10, 2))
        self.countdown_label = tk.Label(self.countdown_card, text="--:--",
                                        font=("Consolas", 44, "bold"),
                                        bg=BG_CELL, fg=FG_ACCENT)
        self.countdown_label.pack(pady=2)
        self.next_subject_label = tk.Label(self.countdown_card, text="",
                                           font=("Microsoft YaHei UI", 12),
                                           bg=BG_CELL, fg=FG_WARN)
        self.next_subject_label.pack(pady=(0, 10))

        # 提示
        self.hint_label = tk.Label(frame, text="", wraplength=270, justify=tk.LEFT,
                                    font=("Microsoft YaHei UI", 9),
                                    bg=BG_PANEL, fg=FG_DIM)
        self.hint_label.pack(anchor=tk.W, padx=14, pady=8, fill=tk.X)

        # 禁用段显示
        self.disabled_card = tk.Frame(frame, bg=BG_CELL)
        self.disabled_card.pack(fill=tk.X, padx=14, pady=4)
        self.disabled_hint_label = tk.Label(self.disabled_card, text="",
                                            font=("Microsoft YaHei UI", 9),
                                            bg=BG_CELL, fg=FG_DANGER,
                                            wraplength=260, justify=tk.LEFT)
        self.disabled_hint_label.pack(padx=10, pady=8, anchor=tk.W)

        # 按钮组
        btn_frame = tk.Frame(frame, bg=BG_PANEL)
        btn_frame.pack(fill=tk.X, padx=14, pady=(12, 6))
        self._big_button(btn_frame, "⚙ 课程设置", self._open_settings).pack(fill=tk.X, pady=3)
        self._more_button = self._big_button(btn_frame, "▾ 更多功能", self._open_more_menu)
        self._more_button.pack(fill=tk.X, pady=3)

    def _big_button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd,
                         bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                         relief=tk.FLAT, font=("Microsoft YaHei UI", 11),
                         padx=10, pady=8, cursor="hand2")

    # ========== 事件绑定 ==========
    def _wire_events(self):
        # backend 是 ScheduleUI 专属，main.py 设置面板不实例化这个类
        if self.backend is None:
            return
        b = self.backend
        try:
            b.subscribe(b.EVT_ENTER_COUNTING, lambda info: None)
        except Exception:
            pass

    # ========== 单元格点击（触摸屏友好） ==========
    def _on_cell_click(self, event, day: int, period: int, cell: tk.Label):
        """左键点单元格 → 弹出菜单（居中贴到单元格附近）。"""
        self._dismiss_menu()

        # 菜单位置：尽量在单元格附近，且在屏幕内
        try:
            cell.update_idletasks()
            x = cell.winfo_rootx() + cell.winfo_width() // 2 - 140
            y = cell.winfo_rooty() + cell.winfo_height()
            # 边界钳制
            sw = self.root.winfo_screenwidth()
            x = max(10, min(x, sw - 290))
        except Exception:
            x = self.root.winfo_rootx() + 100
            y = self.root.winfo_rooty() + 200

        menu = tk.Toplevel(self.root)
        self._menu_win = menu
        menu.title("操作")
        menu.configure(bg=BG_PANEL)
        menu.attributes("-topmost", True)
        menu.overrideredirect(True)
        menu.geometry(f"280x220+{x}+{y}")

        subject = self.backend.get_subject(day, period)

        header = tk.Frame(menu, bg=BG_PANEL)
        header.pack(fill=tk.X, pady=(10, 6))
        tk.Label(header, text=f"{sch.WEEKDAY_NAMES[day]} 第{period}节",
                 font=("Microsoft YaHei UI", 11, "bold"),
                 bg=BG_PANEL, fg=FG_ACCENT).pack(anchor=tk.W, padx=14)
        tk.Label(header, text=f"当前：{subject}",
                 font=("Microsoft YaHei UI", 10),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor=tk.W, padx=14)

        def do_edit():
            self._dismiss_menu()
            if not AskPasswordDialog(self.root, "修改科目需要密钥").result:
                return
            new_val = simpledialog.askstring(
                "临时调课",
                f"{sch.WEEKDAY_NAMES[day]} 第{period}节\n当前：{subject}\n输入新科目（留空=清除）：",
                parent=self.root,
                initialvalue=subject,
            )
            if new_val is None:
                return
            new_val = new_val.strip()
            self.backend.override(day, period, new_val)
            self.refresh_grid()
            self._set_status(f"{sch.WEEKDAY_NAMES[day]} 第{period}节 已更新")

        def do_clear():
            self._dismiss_menu()
            if not AskPasswordDialog(self.root, "清除调课需要密钥").result:
                return
            if not messagebox.askyesno("确认", f"清除 {sch.WEEKDAY_NAMES[day]} 第{period}节的调课？", parent=self.root):
                return
            self.backend.override(day, period, "")
            self.refresh_grid()
            self._set_status("已清除调课")

        def do_close():
            self._dismiss_menu()

        tk.Button(menu, text="✏ 修改本节科目", command=do_edit,
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 11),
                  anchor="w", padx=14, pady=8, cursor="hand2")\
            .pack(fill=tk.X, padx=10, pady=3)

        tk.Button(menu, text="🗑 清除临时调课", command=do_clear,
                  bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 11),
                  anchor="w", padx=14, pady=8, cursor="hand2")\
            .pack(fill=tk.X, padx=10, pady=3)

        tk.Button(menu, text="✕ 关闭", command=do_close,
                  bg=BG_PANEL, fg=FG_DIM, activebackground=BG_CELL,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  anchor="w", padx=14, pady=8, cursor="hand2")\
            .pack(fill=tk.X, padx=10, pady=(4, 8))

        # 点菜单外部自动关闭
        menu.bind("<FocusOut>", lambda e: self._dismiss_menu())
        menu.focus_set()

    def _dismiss_menu(self):
        if self._menu_win and self._menu_win.winfo_exists():
            try:
                self._menu_win.destroy()
            except Exception:
                pass
        self._menu_win = None

    # ========== 刷新 / 状态渲染 ==========
    def refresh_grid(self):
        for (d, p), cell in self._cell_map.items():
            subject = self.backend.get_subject(d, p)
            cell.config(text=subject, fg=FG_TEXT)
        self._apply_current_colors()
        self._render_disabled_hint()

    def _apply_current_colors(self):
        info = self.backend.get_state()
        if info["day"] < 0:
            for cell in self._cell_map.values():
                cell.config(bg=BG_CELL)
            return
        for cell in self._cell_map.values():
            cell.config(bg=BG_CELL)

        if info["state"] == "in_class" and info.get("current_period"):
            cell = self._cell_map.get((info["day"], info["current_period"]))
            if cell:
                cell.config(bg=BG_IN_CLASS)
        elif info.get("next_period") and info["state"] in ("before_class", "between_class"):
            cell = self._cell_map.get((info["day"], info["next_period"]))
            if cell:
                if info.get("is_prebell"):
                    cell.config(bg=BG_PREBELL)
                elif info.get("is_counting"):
                    cell.config(bg=BG_COUNTING)

    def _render_disabled_hint(self):
        disabled = self.backend.get_all_disabled_ranges()
        if not disabled:
            self.disabled_hint_label.config(text="")
            return
        now = datetime.now()
        upcoming = None
        for r in disabled:
            if r["end"] >= now:
                upcoming = r
                break
        if upcoming:
            fmt = "%m-%d %H:%M"
            txt = (f"🚫 禁用期：{upcoming['start'].strftime(fmt)} "
                   f"~ {upcoming['end'].strftime(fmt)}  "
                   f"{upcoming.get('note','')}")
            self.disabled_hint_label.config(text=txt)
        else:
            self.disabled_hint_label.config(text="")

    def _apply_state(self, info: dict):
        now = datetime.now()
        self.clock_label.config(text=now.strftime("%Y-%m-%d %H:%M:%S"))

        day = info["day"]
        disabled = info.get("disabled", False)

        # 禁用期覆盖一切
        if disabled:
            self.state_title.config(text="🚫 程序已禁用")
            self.state_subject.config(text=info.get("disabled_note", ""))
            self.state_time.config(text="")
            self.countdown_label.config(text="禁用中", fg=FG_DANGER)
            self.next_subject_label.config(text="")
            self.hint_label.config(text="根据管理员设置，当前时间段不提醒")
            self.state_card.config(bg="#4a1e1e")
            self.countdown_card.config(bg="#4a1e1e")
            return

        if day < 0:
            self.state_title.config(text="周末 · 无课")
            self.state_subject.config(text="")
            self.state_time.config(text="好好休息！")
            self.countdown_label.config(text="--:--", fg=FG_ACCENT)
            self.next_subject_label.config(text="")
            self.hint_label.config(text="")
            self.state_card.config(bg=BG_CELL)
            self.countdown_card.config(bg=BG_CELL)
            return

        day_name = sch.WEEKDAY_NAMES[day]

        if info["state"] == "in_class":
            p = info["current_period"]
            self.state_title.config(text=f"上课中 · {day_name} 第{p}节")
            self.state_subject.config(text=sch.get_subject(day, p))
            s, e = sch.PERIODS[p]
            self.state_time.config(text=f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}")
            self.countdown_label.config(text="上课中", fg=FG_SUBJECT)
            self.next_subject_label.config(text=f"下一节：{info.get('next_subject', '')}")
            self.hint_label.config(text="正在上课中")
            self.state_card.config(bg=BG_IN_CLASS)
            self.countdown_card.config(bg=BG_IN_CLASS)

        elif info["state"] in ("before_class", "between_class"):
            np_ = info["next_period"]
            self.state_title.config(text=f"课间 · {day_name}")
            self.state_subject.config(text=f"下一节：第{np_}节")
            s, e = sch.PERIODS[np_]
            self.state_time.config(text=f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}")
            self.next_subject_label.config(text=f"科目：{info.get('next_subject', '')}")

            if info.get("is_counting"):
                mm, ss = divmod(max(info.get("seconds_to_prebell", 0), 0), 60)
                self.countdown_label.config(text=f"{mm:02d}:{ss:02d}", fg=FG_WARN)
                self.hint_label.config(text="⏰ 2 分钟倒计时窗口（预备铃前）")
                self.state_card.config(bg=BG_COUNTING)
                self.countdown_card.config(bg=BG_COUNTING)
            elif info.get("is_prebell"):
                self.countdown_label.config(text="预备铃已响", fg=FG_PREBELL)
                self.hint_label.config(text="🔔 预备铃已响 · 请立即回座位")
                self.state_card.config(bg=BG_PREBELL)
                self.countdown_card.config(bg=BG_PREBELL)
            else:
                self.countdown_label.config(text="--:--", fg=FG_ACCENT)
                self.hint_label.config(text="临近上课前 4 分钟进入倒计时")
                self.state_card.config(bg=BG_CELL)
                self.countdown_card.config(bg=BG_CELL)

        elif info["state"] == "after_school":
            self.state_title.config(text=f"已放学 · {day_name}")
            self.state_subject.config(text="今日课程结束")
            self.state_time.config(text="")
            self.countdown_label.config(text="—", fg=FG_ACCENT)
            self.next_subject_label.config(text="")
            self.hint_label.config(text="完成作业 · 早点休息")
            self.state_card.config(bg=BG_CELL)
            self.countdown_card.config(bg=BG_CELL)

        self._apply_current_colors()

    def _tick(self):
        try:
            info = self.backend.get_state()
            self._apply_state(info)
        except Exception as e:
            print(f"[UI tick] error: {e}")
        self.root.after(1000, self._tick)

    # ========== 设置 / 禁用段管理 ==========
    def _open_settings(self):
        SettingsDialog(self.root, self.backend, self)

    def _open_more_menu(self):
        """更多功能下拉菜单（不弹新窗口）"""
        menu = tk.Menu(self.root, tearoff=0, bg=BG_PANEL, fg=FG_TEXT,
                       activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                       bd=0, font=("Microsoft YaHei UI", 10))
        menu.add_command(label="👥  学生积分（需密钥）", command=self._open_student_score)
        menu.add_separator()
        menu.add_command(label="⏱  测试倒计时窗口", command=self._toggle_overlay_manual)
        menu.add_command(label="⚙  调试工具", command=self._open_debug_tool)

        btn = self._more_button
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def _open_student_score(self):
        """学生积分（嵌入模块）：进入需密钥，窗口与主界面同一深色主题。"""
        if not AskPasswordDialog(self.root, "进入学生积分需要密钥").result:
            return
        win = getattr(self, "_score_window", None)
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return
        from student_score import StudentScoreWindow
        self._score_window = StudentScoreWindow(self.root).win

    def _refresh_autostart_status(self):
        registered = autostart.is_registered()
        if registered:
            self.autostart_label.config(text="✓ 已设置开机自启（点击管理）", fg="#66cc88")
        else:
            self.autostart_label.config(text="未设置开机自启（点击设置）", fg=FG_WARN)

    def _toggle_overlay_manual(self):
        """手动打开 overlay_window.py 做测试（backend 常驻也会自动拉起它）。"""
        import subprocess, sys
        try:
            if getattr(sys, "frozen", False):
                exe = Path(sys.executable).parent / "ClassSchedule_Overlay.exe"
                subprocess.Popen([str(exe)])
                self._set_status("已手动打开 overlay")
            else:
                # 用真正的 pythonw.exe（sys.executable 同目录）
                exe_dir = os.path.dirname(sys.executable)
                pyw = os.path.join(exe_dir, "pythonw.exe")
                if not os.path.exists(pyw):
                    pyw = sys.executable
                script = Path(__file__).parent / "overlay_window.py"
                subprocess.Popen([pyw, str(script)])
                self._set_status("已手动打开 overlay_window.py")
        except Exception as e:
            self._set_status(f"打开 overlay 失败：{e}")

    def _set_status(self, text: str):
        self.status_label.config(text=text)

    # ========== 调试工具 ==========
    def _open_debug_tool(self):
        TimeDebugDialog(self.root)


class TimeDebugDialog:
    """
    时间调试工具 —— 设完系统时间后 os._exit(0) 让自己退出，
    方便观察 backend_service.py 是否自动拉起 overlay_window.py。
    另提供"恢复北京时间"按钮（不退出）。
    """

    def __init__(self, parent):
        from datetime import datetime as dt_cls
        import time_debug

        self.win = tk.Toplevel(parent)
        self.win.title("时间调试工具")
        self.win.geometry("460x500")
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
                for p, (s, e) in sch.PERIODS.items():
                    t = dt_cls.combine(today, s) - timedelta(minutes=offset)
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

        self.status_label = tk.Label(self.win, text="", font=("Microsoft YaHei UI", 9),
                                      bg=BG_MAIN, fg=FG_DANGER, wraplength=420, justify=tk.LEFT)
        self.status_label.pack(fill=tk.X, padx=18, pady=6)

        row = tk.Frame(self.win, bg=BG_MAIN)
        row.pack(fill=tk.X, padx=18, pady=(4, 4))

        def apply_and_exit():
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

            self._status("正在设置系统时间…本进程即将退出", FG_WARN)
            self.win.update_idletasks()
            ok, msg = time_debug.set_system_time(target)
            if ok:
                self._status("✓ " + msg + "\n本进程退出后观察 backend 是否拉起 overlay", "#66cc88")
                self.win.after(800, lambda: self._commit_suicide())
            else:
                self._status("✗ " + msg, FG_DANGER)

        def restore_beijing():
            self._status("正在获取北京时间…", FG_DIM)
            self.win.update_idletasks()
            ok, msg = time_debug.restore_beijing_time()
            if ok:
                self._status("✓ " + msg + "\n系统时间已恢复，现在是北京时间", "#66cc88")
            else:
                self._status("✗ " + msg, FG_DANGER)

        tk.Button(row, text="🎯 设置系统时间并退出", command=apply_and_exit,
                  bg="#8b5a2b", fg=FG_TEXT, activebackground=BG_PREBELL,
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 11, "bold"),
                  padx=14, pady=8, cursor="hand2").pack(fill=tk.X, pady=(0, 6))
        tk.Button(row, text="🔄 恢复北京时间（不退出）", command=restore_beijing,
                  bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=14, pady=6, cursor="hand2").pack(fill=tk.X)

        tk.Label(self.win,
                 text="提示：设置时间为系统级操作，普通用户会弹 UAC 确认。\n"
                      "关闭主窗口也会自动恢复北京时间。",
                 font=("Microsoft YaHei UI", 8),
                 bg=BG_MAIN, fg=FG_DIM, justify=tk.LEFT)\
            .pack(anchor=tk.W, padx=18, pady=(10, 14))

        self._tick()

    def _status(self, text: str, color: str = FG_DANGER):
        self.status_label.config(text=text, fg=color)

    def _tick(self):
        try:
            self.now_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        self.win.after(500, self._tick)

    def _commit_suicide(self):
        """让本进程自己结束，好让 backend_service.py 有机会拉 overlay。"""
        try:
            self.win.destroy()
        except Exception:
            pass
        import os
        os._exit(0)


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
        self.win.geometry("560x560")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(root)
        self.win.grab_set()

        notebook = ttk.Notebook(self.win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self._tab_autostart(notebook)
        self._tab_disabled(notebook)
        self._tab_override(notebook)
        self._tab_password(notebook)

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
        tree.column("start", width=140)
        tree.column("end", width=140)
        tree.column("note", width=160)
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
            if not AskPasswordDialog(self.win, "添加禁用时间段需要密钥").result:
                return
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
            if not AskPasswordDialog(self.win, "删除禁用时间段需要密钥").result:
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
        tree.column("key", width=100)
        tree.column("subject", width=200)
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
            if not AskPasswordDialog(self.win, "清除调课需要密钥").result:
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
            if not AskPasswordDialog(self.win, "清除全部调课需要密钥").result:
                return
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

        status_text = "当前密码：默认（1），建议尽快修改" if auth.is_default() else "当前密码：已自定义"
        status_fg = FG_WARN if auth.is_default() else FG_OK
        tk.Label(tab, text=status_text, font=("Microsoft YaHei UI", 9),
                 bg=BG_PANEL, fg=status_fg).pack(anchor=tk.W, padx=14, pady=(0, 12))

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
            ok, reason = auth.change_password(old, new)
            if ok:
                msg.config(text="✓ 密钥已更新", fg=FG_OK)
                e_old.delete(0, tk.END); e_new.delete(0, tk.END); e_cnf.delete(0, tk.END)
                # 更新状态标签
                for child in tab.winfo_children():
                    child.destroy()
                self._tab_password(nb)
            else:
                msg.config(text=f"✗ {reason}", fg=FG_DANGER)

        tk.Button(tab, text="💾 保存新密钥", command=do_change,
                  bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10, "bold"),
                  padx=20, pady=6, cursor="hand2").pack(pady=(10, 4))


class AskPasswordDialog:
    """
    密码验证弹窗。
    用法：if AskPasswordDialog(parent, "请输入密钥").result: ...
    """

    def __init__(self, parent, prompt: str = "请输入密钥"):
        self.result = None
        self.win = tk.Toplevel(parent)
        self.win.title("密钥验证")
        self.win.geometry("360x180")
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


# ttk 主题适配暗色
def _apply_ttk_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TNotebook", background=BG_MAIN, borderwidth=0)
    style.configure("TNotebook.Tab",
                    background=BG_PANEL, foreground=FG_DIM,
                    padding=(14, 6), font=("Microsoft YaHei UI", 10))
    style.map("TNotebook.Tab",
              background=[("selected", BG_CELL)],
              foreground=[("selected", FG_ACCENT)])
    style.configure("Treeview",
                    background=BG_CELL, foreground=FG_TEXT,
                    fieldbackground=BG_CELL, rowheight=26,
                    font=("Microsoft YaHei UI", 10))
    style.configure("Treeview.Heading",
                    background=BG_PANEL, foreground=FG_DIM,
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.map("Treeview", background=[("selected", BG_COUNTING)],
              foreground=[("selected", FG_TEXT)])
    # 下拉框 / 滚动条暗色适配（学生积分模块使用）
    style.configure("TCombobox",
                    fieldbackground=BG_CELL, background=BG_PANEL,
                    foreground=FG_TEXT, arrowcolor=FG_DIM,
                    bordercolor=BG_CELL, lightcolor=BG_CELL, darkcolor=BG_CELL,
                    insertcolor=FG_TEXT)
    style.map("TCombobox",
              fieldbackground=[("readonly", BG_CELL)],
              foreground=[("readonly", FG_TEXT)],
              background=[("readonly", BG_CELL), ("active", BG_CELL_ALT)],
              selectbackground=[("readonly", BG_CELL)],
              selectforeground=[("readonly", FG_TEXT)])
    style.configure("Vertical.TScrollbar",
                    background=BG_CELL, troughcolor=BG_PANEL,
                    bordercolor=BG_PANEL, arrowcolor=FG_DIM)
    root.option_add("*TCombobox*Listbox.background", BG_CELL)
    root.option_add("*TCombobox*Listbox.foreground", FG_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", BG_IN_CLASS)
    root.option_add("*TCombobox*Listbox.selectForeground", FG_TEXT)
