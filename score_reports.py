"""学生积分：积分明细、统计图表、操作日志与低积分预警。"""
import tkinter as tk
from collections import defaultdict
from tkinter import messagebox, ttk

import charts
import score_records as store
from score_data import FONT, OP_LOG, low_score_limit
from ui import (
    BG_MAIN, BG_PANEL, FG_ACCENT, FG_DIM, FG_TEXT, FG_WARN,
    center_window, dpi_scale,
)


class ScoreReportsMixin:
    def _query_detail(self):
        groups = self._groups()
        if not groups:
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return
        stu = self.all_students.get(self.current_class, {})
        parts = []
        for gname, group in groups.items():
            leader = group.get("leader", "")
            leader_text = f"{leader} {stu[leader]['name']}" if leader in stu else "未指定"
            members = [s for s in group.get("members", []) if s in stu]
            total = store.group_total(group, stu)
            parts.append(f"小组：{gname}    组长：{leader_text}    "
                         f"人数：{len(members)}    小组积分：{total}")
            for sid in members:
                info = stu[sid]
                records = store.student_records(info)
                parts.append(f"  {sid} {info['name']}    {store.student_total(info)} 分")
                if not records:
                    parts.append("      （暂无记录）")
                for r in reversed(records):
                    delta = store.record_delta(r)
                    parts.append(f"      {r.get('time', '')}    {delta:+d}    "
                                 f"{r.get('reason', '')}")
            parts.append("-" * 56)
        self._text_window("积分明细（按小组 → 组员）", "\n".join(parts))

    def _text_window(self, title, content):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        tk.Label(win, text=title, font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(12, 6))
        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        txt = tk.Text(body, font=("Consolas", 11), bg=BG_PANEL, fg=FG_TEXT,
                      relief=tk.FLAT, padx=12, pady=10, wrap=tk.WORD)
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        txt.insert(tk.END, content)
        txt.config(state=tk.DISABLED)
        # 按 DPI 放大并居中，和其余弹窗保持一致
        k = dpi_scale(self.win)
        center_window(win, self.win, int(720 * k), int(480 * k))
        return win, txt

    def _chart_window(self, title, width=780, height=500, draw=None):
        """统一的图表窗口；内容放进可滚动区域，行数多或屏幕小时不会被裁掉。"""
        win = tk.Toplevel(self.win)
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        tk.Label(win, text=title, font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(12, 4))

        outer = tk.Frame(win, bg=BG_PANEL)
        outer.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        cv = tk.Canvas(outer, bg=BG_PANEL, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=cv.xview)
        cv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        cv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        body = tk.Frame(cv, bg=BG_PANEL)
        cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: cv.configure(scrollregion=cv.bbox("all")))

        self._btn(win, "关闭", win.destroy).pack(pady=(0, 12))
        if draw is not None:
            draw(body)
            self._charts.append((win, body, draw))
            win.bind("<Destroy>",
                     lambda e, w=win: self._charts.__setitem__(
                         slice(None), [c for c in self._charts if c[0] is not w]))
        # 图表内容已绘制，等布局完成后再按 DPI 缩放并居中
        k = dpi_scale(self.win)
        win.after_idle(
            lambda: center_window(win, self.win, int(width * k), int(height * k))
            if win.winfo_exists() else None)
        return body

    def _refresh_charts(self):
        """积分变化后重绘所有仍打开的统计图表。"""
        for win, body, draw in list(self._charts):
            if not win.winfo_exists():
                continue
            for child in body.winfo_children():
                child.destroy()
            try:
                draw(body)
            except tk.TclError:
                pass

    def _week_chart(self):
        """周度统计：按周次画双向条形图（加分向右，扣分向左）。"""
        if not self._groups():
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return

        def collect():
            week_data = defaultdict(lambda: {"add": 0, "sub": 0})

            def add_record(r):
                d = week_data[r.get("week", "未知")]
                if store.record_delta(r) >= 0:
                    d["add"] += abs(int(r.get("score", 0)))
                else:
                    d["sub"] += abs(int(r.get("score", 0)))

            for _gname, _sid, _name, r in self._iter_records():
                add_record(r)
            for _gname, group in self._groups().items():
                for r in store.group_own_records(group):
                    add_record(r)
            return [(w, d["add"], d["sub"]) for w, d in sorted(week_data.items())]

        rows = collect()
        if not rows:
            messagebox.showinfo("提示", "暂无周度数据", parent=self.win)
            return

        def draw(body):
            charts.bar_chart(body, collect(), width=720).pack(fill=tk.BOTH, expand=True)

        self._chart_window(f"周度积分统计 · {self.current_class}", 760,
                           120 + 34 * len(rows), draw)

    def _group_bar(self):
        """小组双向条形图：加分向右（绿），扣分向左（红）。"""
        if not self._groups():
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return

        def collect():
            rows = []
            for gname, group in self._groups().items():
                add = sub = 0
                stu = self.all_students.get(self.current_class, {})
                for sid in group.get("members", []):
                    info = stu.get(sid)
                    if not info:
                        continue
                    for r in store.student_records(info):
                        if store.record_delta(r) >= 0:
                            add += abs(int(r.get("score", 0)))
                        else:
                            sub += abs(int(r.get("score", 0)))
                for r in store.group_own_records(group):
                    if store.record_delta(r) >= 0:
                        add += abs(int(r.get("score", 0)))
                    else:
                        sub += abs(int(r.get("score", 0)))
                rows.append((gname, add, sub))
            # 净得分高的排在上面，更直观
            rows.sort(key=lambda x: -(x[1] - x[2]))
            return rows

        rows = collect()
        if not any(a or b for _, a, b in rows):
            messagebox.showinfo("提示", "暂无加减分记录", parent=self.win)
            return

        def draw(body):
            charts.bar_chart(body, collect(), width=740).pack(fill=tk.BOTH, expand=True)

        self._chart_window(f"小组加减分对比 · {self.current_class}", 780,
                           140 + 34 * len(rows), draw)

    def _reason_pie(self):
        """理由分布饼图：统计每个理由出现的次数与占比。"""
        def collect():
            counter = defaultdict(int)
            for _gname, _sid, _name, r in self._iter_records():
                counter[r.get("reason", "未填写")] += 1
            for _gname, group in self._groups().items():
                for r in store.group_own_records(group):
                    counter[r.get("reason", "未填写")] += 1
            return sorted(counter.items(), key=lambda kv: -kv[1])

        if not collect():
            messagebox.showinfo("提示", "暂无加减分记录", parent=self.win)
            return

        def draw(body):
            charts.pie_chart(body, collect()).pack(fill=tk.BOTH, expand=True)

        self._chart_window(f"理由分布 · {self.current_class}", 780, 480, draw)

    def _view_op_log(self):
        if not OP_LOG.exists():
            messagebox.showinfo("操作日志", "暂无操作日志", parent=self.win)
            return
        try:
            lines = OP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            messagebox.showerror("操作日志", f"读取失败：{exc}", parent=self.win)
            return
        tail = lines[-800:]
        self._text_window(f"操作日志（最近 {len(tail)} 条）", "\n".join(tail))

    def _low_score_warn(self):
        groups = self._groups()
        if not groups:
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return
        limit = low_score_limit()          # settings.json 可配置，默认 60
        stu = self.all_students.get(self.current_class, {})
        warn = []
        for gname, group in groups.items():
            total = store.group_total(group, stu)
            if total >= limit:
                continue
            leader = group.get("leader", "")
            leader_text = f"组长 {leader} {stu[leader]['name']}" if leader in stu else "未指定组长"
            warn.append(f"{gname}（{leader_text}）：{total} 分")
        if warn:
            self._text_window(f"低积分预警（低于 {limit} 分）", "\n".join(warn))
            self._set_status(f"{len(warn)} 个小组积分偏低", FG_WARN)
        else:
            messagebox.showinfo("低积分预警", "所有小组积分正常", parent=self.win)
