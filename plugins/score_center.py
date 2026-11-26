"""
积分分析中心（插件）

功能：
- 学生积分趋势图：按天/累计，可切换 7 / 14 / 30 天
- 分项占比饼图：按理由的分值权重统计，可切换 全部 / 加分 / 扣分
- 班级排名：学生榜、小组榜
- 荣誉榜：总积分榜、小组榜、本周之星、进步之星
- 加减分历史：筛选、批量撤销、一键撤销最近一次操作

入口：
- 主界面「更多功能 → 插件」中只读打开
- 学生积分窗口「更多功能 → 积分分析中心」中可撤销（需已通过密钥进入）
"""

import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime, timedelta
from tkinter import ttk, messagebox

import charts
from score_records import fmt_delta
from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
    FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_DANGER, FG_OK,
    center_window, dpi_scale,
)

PLUGIN = {
    "id": "score_center",
    "name": "积分分析中心",
    "version": "1.0.0",
    "api_version": 1,
    "description": "趋势图 / 分项占比 / 班级排名 / 荣誉榜 / 历史与撤销",
    "author": "710",
    "requires": [],
    "priority": 20,
}

FONT = "Microsoft YaHei UI"
GOLD = "#ffd166"
SILVER = "#d7dde8"
BRONZE = "#e2a06a"

_OPEN_WINDOWS = {}


# ===================== 数据源 =====================
class StandaloneSource:
    """没有打开学生积分窗口时，直接从数据文件读取（只读分析）。"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.data = ctx.data
        self.current_class = ctx.data.default_class()
        self.switchable = True
        self.readonly = True
        self.selected_ids = set()
        self.all_students = {}
        self.group_data = {}
        self.reload()

    def reload(self):
        self.all_students = self.data.load_students()
        self.group_data = self.data.load_groups()
        for cls in self.data.class_names() or [self.current_class]:
            self.all_students.setdefault(cls, {})
            self.group_data.setdefault(cls, {})
        if self.current_class not in self.all_students:
            self.current_class = self.data.default_class()
            self.all_students.setdefault(self.current_class, {})
            self.group_data.setdefault(self.current_class, {})

    @property
    def students(self):
        return self.all_students.setdefault(self.current_class, {})

    @property
    def groups(self):
        return self.group_data.setdefault(self.current_class, {})

    def save(self):
        self.data.save_all(self.all_students, self.group_data)

    def refresh(self):
        pass

    def status(self, text, color=FG_DIM):
        pass

    def log(self, lines):
        self.data.log_ops(lines)


# ===================== 主窗口 =====================
class ScoreCenterWindow:
    def __init__(self, ctx, source):
        self.ctx = ctx
        self.source = source
        self.data = ctx.data
        parent = getattr(source, "window", None) or ctx.app
        self.win = tk.Toplevel(parent)
        self.win.title("积分分析中心 · 课程表")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(ctx.app)
        self._trend_range = 7
        self._trend_mode = "net"
        self._pie_mode = "all"
        self._rank_mode = "student"
        self._pages = {}
        self._current = ""

        self._build()
        self._show_page("trend")
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        k = dpi_scale(self.win)
        self.win.after_idle(
            lambda: center_window(self.win, ctx.app, int(1140 * k), int(730 * k))
            if self.win.winfo_exists() else None)

    # ---------- 布局 ----------
    def _build(self):
        header = tk.Frame(self.win, bg=BG_MAIN)
        header.pack(fill=tk.X, padx=18, pady=(14, 6))
        tk.Label(header, text="📊 积分分析中心", font=(FONT, 19, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)

        self.class_value = tk.StringVar(value=self.source.current_class)
        if getattr(self.source, "switchable", False):
            tk.Label(header, text="班级", font=(FONT, 10), bg=BG_MAIN,
                     fg=FG_DIM).pack(side=tk.LEFT, padx=(18, 6))
            self.class_box = ttk.Combobox(
                header, textvariable=self.class_value, state="readonly",
                values=self.data.class_names(), width=16, font=(FONT, 10))
            self.class_box.pack(side=tk.LEFT)
            self.class_box.bind("<<ComboboxSelected>>", self._on_class_change)
        else:
            self.class_value.set(self.source.current_class)
            tk.Label(header, text=self.source.current_class, font=(FONT, 12, "bold"),
                     bg=BG_MAIN, fg=FG_TEXT).pack(side=tk.LEFT, padx=18)

        tk.Label(header, text=f"本周 {self.data.week_key()}",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack(side=tk.LEFT, padx=8)

        self._btn(header, "刷新", self._reload).pack(side=tk.RIGHT, padx=4)
        self._btn(header, "关闭", self.win.destroy).pack(side=tk.RIGHT)

        body = tk.Frame(self.win, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=6)

        nav = tk.Frame(body, bg=BG_PANEL, width=150)
        nav.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        nav.pack_propagate(False)
        for key, label in (("trend", "📈 积分趋势"), ("pie", "🥧 分项占比"),
                           ("rank", "🏅 班级排名"), ("honor", "🏆 荣誉榜"),
                           ("history", "🧾 加减分历史")):
            btn = tk.Button(nav, text=label, font=(FONT, 11), bg=BG_PANEL, fg=FG_TEXT,
                            activebackground=BG_CELL, activeforeground=FG_TEXT,
                            relief=tk.FLAT, anchor="w", padx=16, pady=12,
                            cursor="hand2", command=lambda k=key: self._show_page(k))
            btn.pack(fill=tk.X, pady=1)
            self._pages[key] = btn

        self.content = tk.Frame(body, bg=BG_PANEL,
                                highlightbackground=BG_CELL, highlightthickness=1)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(
            self.win, text=("只读分析模式：要撤销记录，请在「学生积分」窗口内打开本插件"
                            if self.source.readonly else
                            "可撤销：勾选历史记录后点击「撤销选中」"),
            font=(FONT, 9), bg=BG_MAIN, fg=FG_WARN if self.source.readonly else FG_DIM,
            anchor="w")
        self.status_label.pack(fill=tk.X, padx=20, pady=(0, 10))

    def _btn(self, parent, text, command, primary=False):
        bg = BG_IN_CLASS if primary else BG_CELL
        active = "#4b7b4b" if primary else BG_CELL_ALT
        return tk.Button(parent, text=text, command=command, bg=bg, fg=FG_TEXT,
                         activebackground=active, activeforeground=FG_TEXT,
                         relief=tk.FLAT, font=(FONT, 10, "bold" if primary else "normal"),
                         padx=14, pady=6, cursor="hand2")

    def _on_class_change(self, _event=None):
        name = self.class_value.get()
        if not name:
            return
        self.source.current_class = name
        if hasattr(self.source, "reload"):
            self.source.reload()
            self.source.current_class = name
        self._show_page(self._current or "trend")

    def _reload(self):
        if hasattr(self.source, "reload"):
            self.source.reload()
        self._show_page(self._current or "trend")
        self._set_status("数据已刷新", FG_OK)

    def _set_status(self, text, color=FG_DIM):
        self.status_label.config(text=text, fg=color)

    def _show_page(self, key):
        self._current = key
        for k, btn in self._pages.items():
            btn.config(bg=BG_CELL if k == key else BG_PANEL,
                       fg=FG_ACCENT if k == key else FG_TEXT)
        for child in self.content.winfo_children():
            child.destroy()
        builders = {
            "trend": self._page_trend, "pie": self._page_pie,
            "rank": self._page_rank, "honor": self._page_honor,
            "history": self._page_history,
        }
        try:
            builders[key](self.content)
        except Exception as exc:
            tk.Label(self.content, text=f"页面加载失败：{exc}", font=(FONT, 11),
                     bg=BG_PANEL, fg=FG_DANGER).pack(pady=40)

    def _toolbar(self, parent):
        bar = tk.Frame(parent, bg=BG_PANEL)
        bar.pack(fill=tk.X, padx=14, pady=(12, 4))
        return bar

    # ===================== 趋势 =====================
    def _trend_data(self):
        days = self._trend_range
        today = datetime.now().date()
        start = today - timedelta(days=days - 1)
        daily = defaultdict(int)
        cumulative = defaultdict(int)
        for _g, _sid, _name, rec in self.data.iter_records(
                self.source.all_students, self.source.group_data,
                self.source.current_class):
            if not isinstance(rec, dict):
                continue
            date = self._date_of(rec)
            if date is None:
                continue
            daily[date] += self.data.delta(rec)
        dates = [start + timedelta(days=i) for i in range(days)]
        running = 0
        points = []
        for date in sorted(daily):
            if date < start:
                running += daily[date]
        for date in dates:
            running += daily.get(date, 0)
            points.append((date, daily.get(date, 0), running))
        return points

    @staticmethod
    def _date_of(rec):
        text = str(rec.get("time", ""))[:10]
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _page_trend(self, parent):
        bar = self._toolbar(parent)
        tk.Label(bar, text="范围", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT)
        for days in (7, 14, 30):
            tk.Button(bar, text=f"{days} 天", font=(FONT, 9),
                      bg=BG_CELL if self._trend_range == days else BG_PANEL,
                      fg=FG_ACCENT if self._trend_range == days else FG_TEXT,
                      relief=tk.FLAT, padx=10, pady=4, cursor="hand2",
                      command=lambda d=days: self._set_trend_range(d))\
                .pack(side=tk.LEFT, padx=3)
        tk.Label(bar, text="　视图", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT)
        for mode, label in (("net", "每日净得分"), ("cum", "累计积分")):
            tk.Button(bar, text=label, font=(FONT, 9),
                      bg=BG_CELL if self._trend_mode == mode else BG_PANEL,
                      fg=FG_ACCENT if self._trend_mode == mode else FG_TEXT,
                      relief=tk.FLAT, padx=10, pady=4, cursor="hand2",
                      command=lambda m=mode: self._set_trend_mode(m))\
                .pack(side=tk.LEFT, padx=3)

        points = self._trend_data()
        total = sum(p[1] for p in points)
        positive = sum(1 for p in points if p[1] > 0)
        summary = tk.Frame(parent, bg=BG_PANEL)
        summary.pack(fill=tk.X, padx=18, pady=(6, 0))
        for label, value, color in (
                ("区间净得分", fmt_delta(total), FG_OK if total >= 0 else FG_DANGER),
                ("有记录天数", f"{positive} 天", FG_ACCENT),
                ("日均", f"{total / max(1, len(points)):+.1f}", FG_WARN)):
            cell = tk.Frame(summary, bg=BG_CELL)
            cell.pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(cell, text=label, font=(FONT, 9), bg=BG_CELL, fg=FG_DIM)\
                .pack(padx=16, pady=(8, 0))
            tk.Label(cell, text=value, font=(FONT, 16, "bold"), bg=BG_CELL,
                     fg=color).pack(padx=16, pady=(0, 8))

        holder = tk.Frame(parent, bg=BG_PANEL)
        holder.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        canvas = tk.Canvas(holder, bg=BG_PANEL, highlightthickness=0, bd=0,
                           height=380)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.bind("<Configure>", lambda e: self._draw_trend(canvas, points))
        canvas.after_idle(lambda: self._draw_trend(canvas, points))

    def _set_trend_range(self, days):
        self._trend_range = days
        self._show_page("trend")

    def _set_trend_mode(self, mode):
        self._trend_mode = mode
        self._show_page("trend")

    def _draw_trend(self, canvas, points):
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        w = max(300, canvas.winfo_width())
        h = max(220, canvas.winfo_height())
        k = dpi_scale(canvas)
        pad_l, pad_r, pad_t, pad_b = int(62 * k), int(26 * k), int(34 * k), int(46 * k)
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        if plot_w <= 10 or plot_h <= 10:
            return

        values = [p[2] if self._trend_mode == "cum" else p[1] for p in points]
        vmax = max(values + [0])
        vmin = min(values + [0])
        if vmax == vmin:
            vmax, vmin = vmax + 1, vmin - 1
        span = vmax - vmin
        vmax += span * 0.12
        vmin -= span * 0.12
        span = vmax - vmin

        def y_of(v):
            return pad_t + (vmax - v) / span * plot_h

        def x_of(i):
            if len(points) == 1:
                return pad_l + plot_w / 2
            return pad_l + i / (len(points) - 1) * plot_w

        # 网格 + Y 轴刻度
        for i in range(5):
            val = vmax - span * i / 4
            y = y_of(val)
            canvas.create_line(pad_l, y, w - pad_r, y, fill="#3a3a4a", width=1)
            canvas.create_text(pad_l - int(8 * k), y, text=f"{val:+.0f}",
                               anchor="e", font=(FONT, 8), fill=FG_DIM)
        zero_y = y_of(0)
        canvas.create_line(pad_l, zero_y, w - pad_r, zero_y,
                           fill="#6a6a80", width=1, dash=(4, 4))

        # 面积
        coords = [pad_l, zero_y]
        for i, val in enumerate(values):
            coords.extend((x_of(i), y_of(val)))
        coords.extend((x_of(len(values) - 1), zero_y))
        if len(values) > 1:
            canvas.create_polygon(coords, fill="#27405c", outline="")

        # 折线
        line = []
        for i, val in enumerate(values):
            line.extend((x_of(i), y_of(val)))
        if len(values) > 1:
            canvas.create_line(line, fill=FG_ACCENT, width=max(2, int(2 * k)),
                               smooth=True)
        for i, val in enumerate(values):
            x, y = x_of(i), y_of(val)
            color = FG_OK if val >= 0 else FG_DANGER
            canvas.create_oval(x - 3 * k, y - 3 * k, x + 3 * k, y + 3 * k,
                               fill=color, outline=BG_PANEL)
            if len(values) <= 14:
                canvas.create_text(x, y - int(12 * k),
                                   text=fmt_delta(val), font=(FONT, 8), fill=color)

        # X 轴日期
        step = max(1, len(points) // 8)
        for i in range(0, len(points), step):
            canvas.create_text(x_of(i), h - pad_b + int(16 * k),
                               text=points[i][0].strftime("%m-%d"),
                               font=(FONT, 8), fill=FG_DIM)
        canvas.create_text(pad_l, int(12 * k),
                           text=("累计积分" if self._trend_mode == "cum" else
                                 "每日净得分（加分 - 扣分）"),
                           anchor="w", font=(FONT, 9), fill=FG_DIM)

        if not any(v for v in values):
            canvas.create_text(w / 2, h / 2, text="该区间暂无积分记录",
                               font=(FONT, 12), fill=FG_DIM)

    # ===================== 分项占比 =====================
    def _page_pie(self, parent):
        bar = self._toolbar(parent)
        tk.Label(bar, text="统计", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT)
        for mode, label in (("all", "全部"), ("add", "加分"), ("sub", "扣分")):
            tk.Button(bar, text=label, font=(FONT, 9),
                      bg=BG_CELL if self._pie_mode == mode else BG_PANEL,
                      fg=FG_ACCENT if self._pie_mode == mode else FG_TEXT,
                      relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
                      command=lambda m=mode: self._set_pie_mode(m))\
                .pack(side=tk.LEFT, padx=3)
        tk.Label(bar, text="占比按分值权重统计", font=(FONT, 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(side=tk.RIGHT, padx=6)

        counter = defaultdict(int)
        count = 0
        for _g, _sid, _name, rec in self.data.iter_records(
                self.source.all_students, self.source.group_data,
                self.source.current_class):
            if not isinstance(rec, dict):
                continue
            delta = self.data.delta(rec)
            if self._pie_mode == "add" and delta <= 0:
                continue
            if self._pie_mode == "sub" and delta >= 0:
                continue
            counter[str(rec.get("reason") or "未填写")] += abs(delta)
            count += 1
        rows = sorted(counter.items(), key=lambda kv: -kv[1])

        if not rows:
            tk.Label(parent, text="暂无符合条件的数据", font=(FONT, 12),
                     bg=BG_PANEL, fg=FG_DIM).pack(pady=60)
            return
        tk.Label(parent, text=f"共 {count} 条记录 · {len(rows)} 种理由",
                 font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM)\
            .pack(anchor="w", padx=20, pady=(8, 0))
        charts.pie_chart(parent, rows, size=330, max_items=10)\
            .pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

    def _set_pie_mode(self, mode):
        self._pie_mode = mode
        self._show_page("pie")

    # ===================== 排名 =====================
    def _page_rank(self, parent):
        bar = self._toolbar(parent)
        tk.Label(bar, text="榜单", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT)
        for mode, label in (("student", "学生榜"), ("group", "小组榜")):
            tk.Button(bar, text=label, font=(FONT, 10),
                      bg=BG_CELL if self._rank_mode == mode else BG_PANEL,
                      fg=FG_ACCENT if self._rank_mode == mode else FG_TEXT,
                      relief=tk.FLAT, padx=14, pady=4, cursor="hand2",
                      command=lambda m=mode: self._set_rank_mode(m))\
                .pack(side=tk.LEFT, padx=3)

        if self._rank_mode == "student":
            rows = [(r[1], r[2], r[3], r[4]) for r in self.data.rank_students(
                self.source.all_students, self.source.group_data,
                self.source.current_class)]
            header = ("名次", "学生", "小组", "积分")
        else:
            rows = [(rank, gname, f"{count} 人", total)
                    for rank, gname, count, total in self.data.rank_groups(
                        self.source.all_students, self.source.group_data,
                        self.source.current_class)]
            header = ("名次", "小组", "人数", "积分")

        self._ranking_rows(parent, rows, header)

    def _set_rank_mode(self, mode):
        self._rank_mode = mode
        self._show_page("rank")

    def _ranking_rows(self, parent, rows, header):
        if not rows:
            tk.Label(parent, text="暂无排名数据", font=(FONT, 12),
                     bg=BG_PANEL, fg=FG_DIM).pack(pady=60)
            return
        max_val = max(1, max(abs(r[3]) for r in rows))
        head = tk.Frame(parent, bg=BG_PANEL)
        head.pack(fill=tk.X, padx=22, pady=(10, 4))
        for text, width, anchor in ((header[0], 6, "center"), (header[1], 18, "w"),
                                    (header[2], 10, "center"), (header[3], 8, "e")):
            tk.Label(head, text=text, font=(FONT, 9, "bold"), bg=BG_PANEL,
                     fg=FG_DIM, width=width, anchor=anchor).pack(side=tk.LEFT)

        outer = tk.Frame(parent, bg=BG_PANEL)
        outer.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))
        cv = tk.Canvas(outer, bg=BG_PANEL, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(cv, bg=BG_PANEL)
        cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))

        for idx, (rank, name, extra, value) in enumerate(rows):
            color = GOLD if rank == 1 else SILVER if rank == 2 else BRONZE if rank == 3 else None
            row = tk.Frame(inner, bg=BG_CELL)
            row.pack(fill=tk.X, pady=2)
            rank_text = f"🥇{rank}" if rank == 1 else f"🥈{rank}" if rank == 2 else \
                f"🥉{rank}" if rank == 3 else str(rank)
            tk.Label(row, text=rank_text, font=(FONT, 11, "bold"),
                     bg=BG_CELL, fg=color or FG_DIM, width=6)\
                .pack(side=tk.LEFT, pady=8)
            tk.Label(row, text=str(name), font=(FONT, 11, "bold" if rank <= 3 else "normal"),
                     bg=BG_CELL, fg=FG_TEXT, width=18, anchor="w")\
                .pack(side=tk.LEFT)
            tk.Label(row, text=str(extra), font=(FONT, 9), bg=BG_CELL,
                     fg=FG_DIM, width=10).pack(side=tk.LEFT)
            bar_w = int(220 * max(0.02, abs(value) / max_val))
            track = tk.Frame(row, bg="#2f2f3f", height=12)
            track.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
            fill = tk.Frame(track, bg=FG_ACCENT if value >= 0 else FG_DANGER,
                            height=12, width=max(2, bar_w))
            fill.pack(side=tk.LEFT)
            fill.pack_propagate(False)
            tk.Label(row, text=f"{value}", font=(FONT, 12, "bold"), bg=BG_CELL,
                     fg=FG_OK if value >= 0 else FG_DANGER, width=8, anchor="e")\
                .pack(side=tk.LEFT, padx=(0, 10))

    # ===================== 荣誉榜 =====================
    def _page_honor(self, parent):
        honors = self.data.honors(self.source.all_students, self.source.group_data,
                                  self.source.current_class)
        tk.Label(parent, text=f"🏆 荣誉榜 · {honors['week']}",
                 font=(FONT, 17, "bold"), bg=BG_PANEL, fg=GOLD)\
            .pack(anchor="w", padx=22, pady=(14, 2))
        tk.Label(parent, text="每周自动按“本周净得分”更新；进步之星对比上一周",
                 font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM)\
            .pack(anchor="w", padx=22, pady=(0, 8))

        grid = tk.Frame(parent, bg=BG_PANEL)
        grid.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        grid.columnconfigure(0, weight=1, uniform="honor")
        grid.columnconfigure(1, weight=1, uniform="honor")

        total_rows = [(r[0], r[2], r[4]) for r in honors["top_students"]]
        group_rows = [(r[0], r[1], r[3]) for r in honors["top_groups"]]
        week_rows = [(i + 1, r[1], r[3]) for i, r in enumerate(honors["week_stars"])]
        imp_rows = [(i + 1, r[1], r[3]) for i, r in enumerate(honors["improvers"])]

        cards = [
            ("🥇 总积分榜", "累计加减分", total_rows, FG_ACCENT),
            ("👥 小组积分榜", "小组成员积分之和", group_rows, FG_OK),
            ("🌟 本周之星", f"{honors['week']} 净得分", week_rows, GOLD),
            ("🚀 进步之星", f"对比 {honors['previous_week']}", imp_rows, FG_WARN),
        ]
        for idx, (title, subtitle, rows, color) in enumerate(cards):
            card = tk.Frame(grid, bg=BG_CELL,
                            highlightbackground=color, highlightthickness=1)
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=8, pady=7)
            tk.Label(card, text=title, font=(FONT, 13, "bold"), bg=BG_CELL,
                     fg=color).pack(anchor="w", padx=14, pady=(10, 0))
            tk.Label(card, text=subtitle, font=(FONT, 8), bg=BG_CELL,
                     fg=FG_DIM).pack(anchor="w", padx=14)
            if not rows:
                tk.Label(card, text="本周暂无数据", font=(FONT, 10),
                         bg=BG_CELL, fg=FG_DIM).pack(anchor="w", padx=14, pady=12)
                continue
            for rank, name, value in rows:
                line = tk.Frame(card, bg=BG_CELL)
                line.pack(fill=tk.X, padx=14, pady=3)
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉"
                tk.Label(line, text=medal, font=(FONT, 12), bg=BG_CELL,
                         fg=color).pack(side=tk.LEFT)
                tk.Label(line, text=str(name), font=(FONT, 11, "bold"), bg=BG_CELL,
                         fg=FG_TEXT).pack(side=tk.LEFT, padx=6)
                tk.Label(line, text=f"{fmt_delta(value)} 分",
                         font=(FONT, 10, "bold"), bg=BG_CELL,
                         fg=FG_OK if value >= 0 else FG_DANGER)\
                    .pack(side=tk.RIGHT)
            tk.Frame(card, bg=BG_CELL, height=6).pack()

    # ===================== 历史 / 撤销 =====================
    def _page_history(self, parent):
        bar = self._toolbar(parent)
        tk.Label(bar, text="学生", font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT)
        stu = self.source.students
        names = ["全部学生"] + [f"{sid} {info.get('name', '')}"
                                for sid, info in sorted(stu.items())]
        self._hist_student = ttk.Combobox(bar, values=names, state="readonly",
                                          width=15, font=(FONT, 9))
        self._hist_student.current(0)
        self._hist_student.pack(side=tk.LEFT, padx=4)
        self._hist_student.bind("<<ComboboxSelected>>", lambda e: self._fill_history())

        tk.Label(bar, text="类型", font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT, padx=(8, 2))
        self._hist_type = ttk.Combobox(bar, values=["全部", "加分", "扣分"],
                                       state="readonly", width=6, font=(FONT, 9))
        self._hist_type.current(0)
        self._hist_type.pack(side=tk.LEFT)
        self._hist_type.bind("<<ComboboxSelected>>", lambda e: self._fill_history())

        self._hist_keyword = tk.Entry(bar, width=14, font=(FONT, 9), bg=BG_CELL,
                                      fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)
        self._hist_keyword.pack(side=tk.LEFT, padx=6)
        self._hist_keyword.bind("<Return>", lambda e: self._fill_history())
        tk.Button(bar, text="筛选", font=(FONT, 9), bg=BG_CELL, fg=FG_TEXT,
                  relief=tk.FLAT, padx=8, pady=3, cursor="hand2",
                  command=self._fill_history).pack(side=tk.LEFT)

        if not self.source.readonly:
            tk.Button(bar, text="撤销最近一次", font=(FONT, 9), bg=BG_CELL,
                      fg=FG_WARN, relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
                      command=self._undo_recent).pack(side=tk.RIGHT)
            tk.Button(bar, text="撤销选中", font=(FONT, 9), bg=BG_IN_CLASS,
                      fg=FG_TEXT, relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
                      command=self._undo_selected).pack(side=tk.RIGHT, padx=6)

        body = tk.Frame(parent, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(6, 10))
        style = ttk.Style()
        style.configure("Center.Treeview", background=BG_CELL,
                        fieldbackground=BG_CELL, foreground=FG_TEXT,
                        rowheight=max(24, int(28 * dpi_scale(parent))),
                        borderwidth=0, font=(FONT, 9))
        style.configure("Center.Treeview.Heading", background=BG_PANEL,
                        foreground=FG_ACCENT, relief=tk.FLAT,
                        font=(FONT, 9, "bold"))
        style.map("Center.Treeview", background=[("selected", "#2f5f8f")])
        self._hist_tree = ttk.Treeview(
            body, columns=("time", "student", "group", "delta", "reason", "week"),
            show="headings", style="Center.Treeview",
            selectmode="extended" if not self.source.readonly else "browse")
        specs = (("time", "时间", 145), ("student", "学生", 120),
                 ("group", "小组", 90), ("delta", "分值", 65),
                 ("reason", "理由", 230), ("week", "周次", 80))
        for col, text, width in specs:
            self._hist_tree.heading(col, text=text)
            self._hist_tree.column(
                col, width=width, anchor="w" if col in ("student", "group", "reason")
                else "center")
        sb = ttk.Scrollbar(body, orient="vertical", command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=sb.set)
        self._hist_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._hist_tree.bind("<Double-1>", lambda e: None)
        self._fill_history()

    def _fill_history(self):
        tree = getattr(self, "_hist_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        tree.delete(*tree.get_children())
        stu = self.source.students
        gmap = self.data.group_map(self.source.groups, stu)
        pick = self._hist_student.get() if hasattr(self, "_hist_student") else "全部学生"
        want_sid = pick.split(" ", 1)[0] if pick != "全部学生" else ""
        typ = self._hist_type.get() if hasattr(self, "_hist_type") else "全部"
        keyword = self._hist_keyword.get().strip() if hasattr(self, "_hist_keyword") else ""

        rows = []
        for sid, info in stu.items():
            if want_sid and sid != want_sid:
                continue
            for idx, rec in enumerate(self.data.records(info)):
                if not isinstance(rec, dict):
                    continue
                delta = self.data.delta(rec)
                if typ == "加分" and delta <= 0:
                    continue
                if typ == "扣分" and delta >= 0:
                    continue
                reason = str(rec.get("reason", ""))
                if keyword and keyword not in reason and keyword not in \
                        str(info.get("name", "")) and keyword not in sid:
                    continue
                rows.append((sid, idx, info, rec))
        rows.sort(key=lambda x: str(x[3].get("time", "")), reverse=True)
        for sid, idx, info, rec in rows:
            delta = self.data.delta(rec)
            tree.insert("", tk.END, iid=f"{sid}|{idx}", values=(
                rec.get("time", ""), f"{sid} {info.get('name', '')}",
                gmap.get(sid, "未分组"), fmt_delta(delta),
                rec.get("reason", ""), self.data.record_week(rec)))

    def _selected_records(self):
        tree = self._hist_tree
        stu = self.source.students
        items, labels = [], []
        for iid in tree.selection():
            try:
                sid, idx_text = iid.rsplit("|", 1)
                idx = int(idx_text)
                rec = self.data.records(stu.get(sid, {}))[idx]
            except (ValueError, IndexError, KeyError):
                continue
            items.append((sid, rec))
            labels.append(f"{sid} {stu.get(sid, {}).get('name', '')}  "
                          f"{fmt_delta(self.data.delta(rec))} 分 · {rec.get('reason', '')}")
        return items, labels

    def _undo_selected(self):
        if self.source.readonly:
            return
        items, labels = self._selected_records()
        if not items:
            messagebox.showinfo("提示", "请先在下方表格中选择记录", parent=self.win)
            return
        if not messagebox.askyesno(
                "确认撤销",
                f"撤销以下 {len(items)} 条记录？学生积分会立即回退。\n\n" +
                "\n".join(labels[:12]) +
                ("\n…" if len(labels) > 12 else ""), parent=self.win):
            return
        self._apply_undo(items)

    def _undo_recent(self):
        if self.source.readonly:
            return
        stu = self.source.students
        newest = ""
        for info in stu.values():
            for rec in self.data.records(info):
                if isinstance(rec, dict):
                    newest = max(newest, str(rec.get("time", "")))
        if not newest:
            messagebox.showinfo("提示", "当前班级暂无积分记录", parent=self.win)
            return
        items = []
        for sid, info in stu.items():
            for rec in self.data.records(info):
                if isinstance(rec, dict) and str(rec.get("time", "")) == newest:
                    items.append((sid, rec))
        if not items:
            return
        reasons = sorted({str(rec.get("reason", "")) for _, rec in items})
        if not messagebox.askyesno(
                "确认撤销最近一次操作",
                f"时间：{newest}\n涉及 {len(items)} 名学生\n理由：{'、'.join(reasons[:6])}\n\n"
                "确定撤销这批记录？", parent=self.win):
            return
        self._apply_undo(items)

    def _apply_undo(self, items):
        cls = self.source.current_class
        stu = self.source.students
        removed = self.data.remove_records(self.source.all_students,
                                           self.source.group_data, cls, items)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = []
        for sid, rec in items:
            lines.append(f"{now} | {cls} | {sid} {stu.get(sid, {}).get('name', '')} | "
                         f"撤销 {rec.get('reason', '')} | 原记录 {rec.get('time', '')}")
        self.data.log_ops(lines)
        try:
            self.source.refresh()
        except Exception:
            pass
        self._set_status(f"已撤销 {removed} 条记录", FG_OK)
        self._show_page("history")
        if not self.win.winfo_exists():
            return
        self.status_label.config(text=f"已撤销 {removed} 条记录，积分立即生效", fg=FG_OK)


def _open(ctx, api=None):
    source = api
    if source is None:
        source = ctx.ui.get_score_window_api()
    if source is None:
        source = StandaloneSource(ctx)
    key = ("live|" if hasattr(source, "window") else "readonly|") + \
        getattr(source, "current_class", "")
    win = _OPEN_WINDOWS.get(key)
    try:
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            return
    except tk.TclError:
        pass
    window = ScoreCenterWindow(ctx, source)
    _OPEN_WINDOWS[key] = window.win

    def _forget(_event=None):
        _OPEN_WINDOWS.pop(key, None)
    window.win.bind("<Destroy>", _forget)


def register(ctx):
    ctx.ui.add_main_menu("📊 积分分析中心", lambda: _open(ctx), order=10)
    ctx.ui.add_score_menu("📊 积分分析中心（趋势 / 排行 / 荣誉 / 撤销）",
                          lambda api: _open(ctx, api), order=10)
