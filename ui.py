"""
Tkinter 主界面（ScheduleUI）
- 触摸屏友好：左键弹出菜单、无右键依赖
- 左侧：课程表网格（左键点单元格 → 弹出菜单：调课 / 取消调课）
- 右侧：实时状态面板 + 倒计时 + 设置按钮
- 底部：开机自启状态

2.1.0 起主题/DPI 工具拆到 ui_theme.py，各对话框拆到 ui_dialogs.py；
本模块继续导出同名符号，外部 `from ui import ...` 无需修改。
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime, timedelta
from pathlib import Path
import os
import threading

import schedule_core as sch
import autostart
import auth
from ui_theme import (  # noqa: F401  —— 保持原有导入路径可用
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS, BG_COUNTING,
    BG_PREBELL, BG_DANGER, FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_PREBELL,
    FG_DANGER, FG_OK, FG_SUBJECT, enable_high_dpi, work_area, dpi_scale,
    fit_geometry, center_window, _apply_ttk_theme,
)
from ui_dialogs import (  # noqa: F401  —— 保持原有导入路径可用
    TimeDebugDialog, SettingsDialog, LanDialog, AskPasswordDialog,
)


class ScheduleUI:
    def __init__(self, root: tk.Tk, backend):
        self.root = root
        self.backend = backend

        root.title("课程表 · 七年级10班")
        # 按 DPI 放大窗口，避免高分屏下界面又小又模糊
        fit_geometry(root, 1100, 680, 1000, 600)
        root.configure(bg=BG_MAIN)

        self._cell_map = {}
        self._debug_win = None
        self._menu_win = None  # 单元格操作菜单窗口
        self._plugin_vars = {}  # 插件菜单勾选状态（避免变量被回收）

        self._build_ui()

        # 初始渲染：把科目名字填进单元格
        self.refresh_grid()
        self._apply_current_colors()

        # 开机自启状态检查
        self._refresh_autostart_status()

        # 插件：自动扫描 plugins/ 目录，单个插件出错不影响主程序
        self.plugins = None
        try:
            import plugin_api
            self.root._schedule_ui = self          # 供插件框架定位宿主界面
            self.plugins = plugin_api.init(app=self.root)
            self.plugins.load_all()
            summary = plugin_api.plugin_summary()
            print("[插件]" + summary.replace("\n", "\n[插件]"))
        except Exception:
            import traceback
            traceback.print_exc()

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
        # 插件注册的顶部按钮放在时钟左侧
        self._plugin_btn_bar = tk.Frame(top, bg=BG_MAIN)
        self._plugin_btn_bar.pack(side=tk.RIGHT, padx=(10, 6))

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

        tk.Label(frame,
                 text=(f"🕛 午间小练 {sch.PRACTICE_START:%H:%M}–{sch.PRACTICE_END:%H:%M}"
                       f"　🌙 晚辅 {sch.EVENING_START:%H:%M}–{sch.EVENING_END:%H:%M}"
                       f"　🏫 放学 {sch.SCHOOL_END:%H:%M}"),
                 font=("Microsoft YaHei UI", 8), bg=BG_PANEL, fg=FG_WARN)\
            .pack(anchor=tk.W, padx=10, pady=(2, 0))
        tk.Label(frame, text="📱 触摸屏：左键点任意课程 → 弹出操作菜单",
                 font=("Microsoft YaHei UI", 8), bg=BG_PANEL, fg=FG_DIM)\
            .pack(anchor=tk.W, padx=10, pady=(2, 8))

    def _build_side_panel(self, parent):
        # 侧栏宽度按 DPI 放大，否则高分屏上字号变大后文字会被裁掉
        k = dpi_scale(self.root)
        panel_w = int(300 * k)
        frame = tk.Frame(parent, bg=BG_PANEL, width=panel_w, highlightbackground=BG_CELL, highlightthickness=1)
        frame.pack(side=tk.RIGHT, fill=tk.Y)
        frame.pack_propagate(False)

        tk.Label(frame, text="实时状态", font=("Microsoft YaHei UI", 12, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor=tk.W, padx=14, pady=(12, 4))

        # 状态卡片
        self.state_card = tk.Frame(frame, bg=BG_CELL)
        self.state_card.pack(fill=tk.X, padx=14, pady=6)
        self.state_title = tk.Label(self.state_card, text="—",
                                    font=("Microsoft YaHei UI", 14, "bold"),
                                    bg=BG_CELL, fg=FG_TEXT,
                                    wraplength=panel_w - 40, justify=tk.CENTER)
        self.state_title.pack(pady=(12, 2))
        self.state_subject = tk.Label(self.state_card, text="—",
                                      font=("Microsoft YaHei UI", 22, "bold"),
                                      bg=BG_CELL, fg=FG_ACCENT,
                                      wraplength=panel_w - 40, justify=tk.CENTER)
        self.state_subject.pack(pady=4)
        self.state_time = tk.Label(self.state_card, text="",
                                   font=("Consolas", 11),
                                   bg=BG_CELL, fg=FG_DIM)
        self.state_time.pack(pady=(0, 12))

        # 侧栏实际宽度变化时同步换行宽度，避免大字被裁切
        def _rewrap(event):
            wrap = max(120, event.width - 12)
            self.state_title.config(wraplength=wrap)
            self.state_subject.config(wraplength=wrap)
        self.state_card.bind("<Configure>", _rewrap)

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

        # 按钮组（放在提示/禁用段之前，窗口最小时也不会被裁掉）
        btn_frame = tk.Frame(frame, bg=BG_PANEL)
        btn_frame.pack(fill=tk.X, padx=14, pady=(10, 6))
        row1 = tk.Frame(btn_frame, bg=BG_PANEL)
        row1.pack(fill=tk.X, pady=2)
        self._big_button(row1, "👥 学生积分", self._open_student_score)\
            .pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._big_button(row1, "🧹 卫生管理", self._open_hygiene)\
            .pack(side=tk.LEFT, fill=tk.X, expand=True)
        row2 = tk.Frame(btn_frame, bg=BG_PANEL)
        row2.pack(fill=tk.X, pady=2)
        self._big_button(row2, "⚙ 设置", self._open_settings)\
            .pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._big_button(row2, "📋 值日生任命", self._open_duty_admin)\
            .pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._plugin_button = self._big_button(btn_frame, "🧩 插件",
                                                self._open_plugin_menu)
        self._plugin_button.pack(fill=tk.X, pady=2)
        self._more_button = self._big_button(btn_frame, "▾ 更多功能", self._open_more_menu)
        self._more_button.pack(fill=tk.X, pady=2)

        # 提示
        self.hint_label = tk.Label(frame, text="", wraplength=panel_w - 30, justify=tk.LEFT,
                                    font=("Microsoft YaHei UI", 9),
                                    bg=BG_PANEL, fg=FG_DIM)
        self.hint_label.pack(anchor=tk.W, padx=14, pady=8, fill=tk.X)

        # 禁用段显示
        self.disabled_card = tk.Frame(frame, bg=BG_CELL)
        self.disabled_card.pack(fill=tk.X, padx=14, pady=4)
        self.disabled_hint_label = tk.Label(self.disabled_card, text="",
                                            font=("Microsoft YaHei UI", 9),
                                            bg=BG_CELL, fg=FG_DANGER,
                                            wraplength=panel_w - 44, justify=tk.LEFT)
        self.disabled_hint_label.pack(padx=10, pady=8, anchor=tk.W)

    def _big_button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd,
                         bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                         relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                         padx=6, pady=6, cursor="hand2")

    # ========== 单元格点击（触摸屏友好） ==========
    def _on_cell_click(self, event, day: int, period: int, cell: tk.Label):
        """左键点单元格 → 弹出菜单（居中贴到单元格附近）。"""
        self._dismiss_menu()

        menu = tk.Toplevel(self.root)
        self._menu_win = menu
        menu.title("操作")
        menu.configure(bg=BG_PANEL)
        menu.attributes("-topmost", True)
        menu.overrideredirect(True)
        menu.withdraw()   # 内容排完再显示，避免先闪到屏幕左上角

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

        # 按内容自适应尺寸（高 DPI 下 220px 装不下三个按钮）
        menu.update_idletasks()
        mw = max(int(280 * dpi_scale(self.root)), menu.winfo_reqwidth())
        mh = menu.winfo_reqheight()
        wl, wt, wr, wb = work_area(self.root)
        try:
            cell.update_idletasks()
            cx = cell.winfo_rootx() + cell.winfo_width() // 2
            cy = cell.winfo_rooty()
            ch = cell.winfo_height()
        except Exception:
            cx = self.root.winfo_rootx() + self.root.winfo_width() // 2
            cy = self.root.winfo_rooty() + self.root.winfo_height() // 3
            ch = 0
        x = cx - mw // 2
        y = cy + ch + 2
        if y + mh > wb:              # 下方放不下就翻到单元格上方
            y = cy - mh - 2
        # 双向钳制到可用区域内
        x = max(wl + 4, min(x, wr - mw - 4))
        y = max(wt + 4, min(y, wb - mh - 4))
        menu.geometry(f"{mw}x{mh}+{x}+{y}")
        menu.deiconify()

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

        # 只有正课才有对应单元格；午间小练 / 晚辅不参与网格高亮
        cur = info.get("current_period")
        if info["state"] == "in_class" and isinstance(cur, int):
            cell = self._cell_map.get((info["day"], cur))
            if cell:
                cell.config(bg=BG_IN_CLASS)
        else:
            nxt = info.get("next_period")
            if isinstance(nxt, int) and info["state"] in ("before_class", "between_class"):
                cell = self._cell_map.get((info["day"], nxt))
                if cell:
                    if info.get("is_prebell"):
                        cell.config(bg=BG_PREBELL)
                    elif info.get("is_counting"):
                        cell.config(bg=BG_COUNTING)

    def _render_disabled_hint(self):
        disabled = self.backend.get_all_disabled_ranges()
        if not disabled:
            self.disabled_hint_label.config(text="")
            # 没有禁用段时收起整块，给按钮留出空间
            if self.disabled_card.winfo_ismapped():
                self.disabled_card.pack_forget()
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
            if not self.disabled_card.winfo_ismapped():
                self.disabled_card.pack(fill=tk.X, padx=14, pady=4)
        else:
            self.disabled_hint_label.config(text="")
            if self.disabled_card.winfo_ismapped():
                self.disabled_card.pack_forget()

    def _set_card_bg(self, color: str):
        """状态卡/倒计时卡换色时同步文字背景，避免文字周围残留深色方块。"""
        for card in (self.state_card, self.countdown_card):
            card.config(bg=color)
            for child in card.winfo_children():
                try:
                    child.config(bg=color)
                except tk.TclError:
                    pass

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
            self._set_card_bg("#4a1e1e")
            return

        if day < 0:
            self.state_title.config(text="周末 · 无课")
            self.state_subject.config(text="")
            self.state_time.config(text="好好休息！")
            self.countdown_label.config(text="--:--", fg=FG_ACCENT)
            self.next_subject_label.config(text="")
            self.hint_label.config(text="")
            self._set_card_bg(BG_CELL)
            return

        day_name = sch.WEEKDAY_NAMES[day]

        if info["state"] == "in_class":
            # 正课 / 午间小练 / 晚辅 统一用 current_name 显示
            name = info.get("current_name") or f"第{info.get('current_period')}节"
            self.state_title.config(text=f"上课中 · {day_name} {name}")
            self.state_subject.config(text=info.get("current_subject", ""))
            s, e = info.get("current_start"), info.get("current_end")
            self.state_time.config(
                text=f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}" if s and e else "")
            self.countdown_label.config(text="上课中", fg=FG_SUBJECT)
            self.next_subject_label.config(
                text=f"下一节：{info.get('next_name', '')} {info.get('next_subject', '')}".strip())
            self.hint_label.config(text="正在上课中")
            self._set_card_bg(BG_IN_CLASS)

        elif info["state"] in ("before_class", "between_class"):
            name = info.get("next_name") or f"第{info.get('next_period')}节"
            self.state_title.config(text=f"课间 · {day_name}")
            self.state_subject.config(text=f"下一节：{name}")
            s, e = info.get("next_start"), info.get("next_end")
            self.state_time.config(
                text=f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}" if s and e else "")
            self.next_subject_label.config(text=f"科目：{info.get('next_subject', '')}")

            if info.get("is_counting"):
                mm, ss = divmod(max(info.get("seconds_to_prebell", 0), 0), 60)
                self.countdown_label.config(text=f"{mm:02d}:{ss:02d}", fg=FG_WARN)
                self.hint_label.config(text="⏰ 2 分钟倒计时窗口（预备铃前）")
                self._set_card_bg(BG_COUNTING)
            elif info.get("is_prebell"):
                self.countdown_label.config(text="预备铃已响", fg=FG_PREBELL)
                self.hint_label.config(text="🔔 预备铃已响 · 请立即回座位")
                self._set_card_bg(BG_PREBELL)
            else:
                self.countdown_label.config(text="--:--", fg=FG_ACCENT)
                self.hint_label.config(text="临近上课前 4 分钟进入倒计时")
                self._set_card_bg(BG_CELL)

        elif info["state"] == "after_school":
            self.state_title.config(text=f"已放学 · {day_name}")
            self.state_subject.config(text="今日课程结束")
            end = info.get("school_end")
            self.state_time.config(text=f"放学时间 {end.strftime('%H:%M')}" if end else "")
            self.countdown_label.config(text="—", fg=FG_ACCENT)
            self.next_subject_label.config(text="")
            self.hint_label.config(text="完成作业 · 早点休息")
            self._set_card_bg(BG_CELL)

        self._apply_current_colors()

    def _tick(self):
        self._poll_ball_request()
        try:
            info = self.backend.get_state()
            self._apply_state(info)
        except Exception as e:
            print(f"[UI tick] error: {e}")
        self.root.after(1000, self._tick)

    def _poll_ball_request(self):
        """悬浮球进程托办：由主界面打开学生积分，避免两个进程同时改同一份数据。"""
        try:
            import ball_bridge
            mode = ball_bridge.take_open_score_request()
            if not mode:
                return
            if mode == "readonly":
                self._show_student_score(readonly=True)
            else:
                self._open_student_score()
        except Exception as e:
            print(f"[UI] 悬浮球请求处理失败: {e}")

    # ========== 设置 / 禁用段管理 ==========
    def _open_settings(self):
        SettingsDialog(self.root, self.backend, self)

    def _open_duty_admin(self):
        from entry import DutyAdminWindow
        DutyAdminWindow(self.root)

    def _open_more_menu(self):
        """更多功能下拉菜单（不弹新窗口）"""
        menu = tk.Menu(self.root, tearoff=0, bg=BG_PANEL, fg=FG_TEXT,
                       activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                       bd=0, font=("Microsoft YaHei UI", 10))
        menu.add_command(label="⏱  测试倒计时窗口", command=self._toggle_overlay_manual)
        menu.add_command(label="⇄  局域网连接（手机）", command=self._open_lan)
        menu.add_command(label="⚙  调试工具", command=self._open_debug_tool)
        menu.add_separator()
        menu.add_command(label="ℹ  版本信息", command=self._show_version_info)

        btn = self._more_button
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def _open_plugin_menu(self):
        """插件菜单：悬浮球入口、插件开关与插件功能入口。"""
        menu = tk.Menu(self.root, tearoff=0, bg=BG_PANEL, fg=FG_TEXT,
                       activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                       bd=0, font=("Microsoft YaHei UI", 10))
        menu.add_command(label="◉  显示悬浮球", command=self._show_floating_ball)
        menu.add_separator()

        infos, entries = [], []
        try:
            import plugin_api
            infos = plugin_api.plugin_infos()
            entries = plugin_api.main_menu_items()
        except Exception as exc:
            print(f"[UI] 读取插件列表失败：{exc}")

        if not infos:
            menu.add_command(label="（未发现插件）", state="disabled")
        for info in infos:
            pid = info["id"]
            var = self._plugin_vars.get(pid)
            if var is None:
                var = tk.BooleanVar(value=info["enabled"])
                self._plugin_vars[pid] = var
            else:
                var.set(info["enabled"])
            if not info["enabled"]:
                state = "已禁用"
            elif not info["ok"]:
                state = "加载失败"
            else:
                state = "已启用"
            menu.add_checkbutton(
                label=f"{info['name']}  v{info['version']}  ·  {state}",
                variable=var,
                command=lambda i=pid, v=var, n=info["name"]: self._toggle_plugin(i, v, n))
        if entries:
            menu.add_separator()
            for label, callback in entries:
                menu.add_command(label=label,
                                 command=lambda cb=callback: self._run_plugin_entry(cb))

        btn = self._plugin_button
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def _toggle_plugin(self, plugin_id: str, var: tk.BooleanVar, name: str):
        """即时启停插件，开关状态写入共享配置供悬浮球进程同步。"""
        try:
            import plugin_api
            plugin_api.set_plugin_enabled(plugin_id, var.get())
            action = "启用" if var.get() else "禁用"
            self._set_status(f"插件「{name}」已{action}")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            messagebox.showerror("插件出错", str(exc), parent=self.root)

    def _run_plugin_entry(self, callback):
        """执行插件注册的菜单项，异常只提示不中断主程序。"""
        try:
            callback()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            messagebox.showerror("插件出错", str(exc), parent=self.root)

    def refresh_plugin_top_buttons(self, items):
        """插件注册的顶部按钮：重建按钮区，保持与主界面同一套配色。"""
        bar = getattr(self, "_plugin_btn_bar", None)
        if bar is None:
            return
        for child in bar.winfo_children():
            child.destroy()
        for text, callback in items:
            btn = tk.Button(
                bar, text=text, command=callback,
                font=("Microsoft YaHei UI", 9), bg=BG_CELL, fg=FG_TEXT,
                activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                relief=tk.FLAT, padx=10, pady=2, cursor="hand2", bd=0)
            btn.pack(side=tk.LEFT, padx=4, pady=2)

    def _open_student_score(self):
        """学生积分（嵌入模块）：已通过教师端登录，不再重复要密钥。"""
        self._show_student_score(readonly=False)

    def _open_hygiene(self):
        """卫生管理：只记卫生扣分、不计入积分。"""
        win = getattr(self.root, "_hygiene_window", None)
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            return
        from hygiene import HygieneWindow
        self.root._hygiene_window = HygieneWindow(
            self.root, operator={"name": "教师", "role": "教师"}).win

    def _show_student_score(self, readonly=False):
        # 悬浮球与主界面共用同一个窗口实例，存到 root 上避免开出两个窗口
        win = getattr(self.root, "_score_window", None)
        if win is not None and win.winfo_exists():
            if readonly or getattr(win, "_readonly", False) == readonly:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
            win.destroy()          # 只读 → 编辑：重建窗口，重新走密钥校验
            self.root._score_window = None
        from student_score import StudentScoreWindow
        ctrl = StudentScoreWindow(self.root, readonly=readonly)
        ctrl.win._controller = ctrl          # 供插件框架通过 ScoreWindowAPI 访问
        self.root._score_window = ctrl.win

    def _show_version_info(self):
        """显示版本号、整包哈希与代码校验结果，用于判断本机安装版本。"""
        try:
            import version_manager
            text = version_manager.describe()
        except Exception as exc:
            text = f"无法读取版本信息：{exc}"
        text += ("\n\n开发者名单：陆瑜瀚、杨皓文、刘骁、Trae-Solo-Agent、DeepSeek-V4.1-Flash\n"
                 "项目地址：https://gitee.com/lu-yuhan20140623/710")
        messagebox.showinfo("版本信息", text, parent=self.root)

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

    def _show_floating_ball(self):
        """显示桌面悬浮球：已在运行（含被隐藏）就通知它重新出现，否则拉起进程。"""
        import subprocess, sys
        try:
            import ball_bridge
            if ball_bridge.request_show_ball():
                self._set_status("已通知悬浮球显示")
                return
            # 进程没在跑时先留一个显示请求，新进程启动后不会被上次的隐藏状态挡住
            try:
                ball_bridge.SHOW_REQUEST_FILE.write_text("show", encoding="utf-8")
            except OSError:
                pass
            if getattr(sys, "frozen", False):
                exe = Path(sys.executable).parent / "ClassSchedule_Ball.exe"
                if not exe.exists():
                    self._set_status(f"未找到 {exe.name}")
                    return
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
                self._set_status("已请求显示悬浮球（后台服务会持续保活）")
            else:
                exe_dir = os.path.dirname(sys.executable)
                pyw = os.path.join(exe_dir, "pythonw.exe")
                if not os.path.exists(pyw):
                    pyw = sys.executable
                script = Path(__file__).parent / "floating_ball_service.py"
                subprocess.Popen([pyw, str(script)], cwd=str(script.parent))
                self._set_status("已启动悬浮球进程")
        except Exception as e:
            self._set_status(f"显示悬浮球失败：{e}")

    def _set_status(self, text: str):
        self.status_label.config(text=text)

    # ========== 调试工具 ==========
    def _open_debug_tool(self):
        TimeDebugDialog(self.root)

    def _open_lan(self):
        """局域网直连：把本机地址提供给手机端读取实时数据。"""
        LanDialog(self.root)
