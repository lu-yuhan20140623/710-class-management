"""成长档案窗口：榜单 / 奖励记录 / 成长趋势 / 岗位履职 / 台账导出。

所有数据来自 store（永久 JSONL 档案），不依赖当前周积分是否被重置。
"""

import tkinter as tk
from collections import defaultdict
from tkinter import filedialog, messagebox, ttk

from . import charts, ledger_export
from . import store
import score_records as sr
from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, FG_TEXT, FG_DIM, FG_ACCENT, FG_OK,
    center_window, dpi_scale, fit_geometry,
)

FONT = "Microsoft YaHei UI"


def _style_tree(tree: ttk.Treeview):
    style = ttk.Style(tree)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("GA.Treeview", background=BG_CELL, fieldbackground=BG_CELL,
                    foreground=FG_TEXT, rowheight=26, font=(FONT, 9), borderwidth=0)
    style.configure("GA.Treeview.Heading", background=BG_PANEL, foreground=FG_DIM,
                    font=(FONT, 9, "bold"), relief="flat")
    style.map("GA.Treeview", background=[("selected", "#2f5f8f")])
    tree.configure(style="GA.Treeview")


class GrowthArchiveWindow:
    def __init__(self, parent, host=None, cls: str | None = None):
        self.host = host
        self.cls = cls or ""
        self.win = tk.Toplevel(parent)
        self.win.title("成长档案 · 积分榜单与德育台账")
        fit_geometry(self.win, 1180, 740, 980, 620)
        self.win.configure(bg=BG_MAIN)
        self.win.transient(parent.winfo_toplevel())

        store.seed_from_students()
        self._build()
        self._reload()

    # ---------- 界面 ----------
    def _build(self):
        top = tk.Frame(self.win, bg=BG_MAIN)
        top.pack(fill=tk.X, padx=14, pady=(12, 4))

        tk.Label(top, text="成长档案", bg=BG_MAIN, fg=FG_ACCENT,
                 font=(FONT, 16, "bold")).pack(side=tk.LEFT)
        tk.Label(top, text="  （评价永久留存 · 可按班级 / 学生导出德育台账）",
                 bg=BG_MAIN, fg=FG_DIM, font=(FONT, 9)).pack(side=tk.LEFT, padx=6)

        tk.Label(top, text="班级", bg=BG_MAIN, fg=FG_DIM, font=(FONT, 9)).pack(side=tk.RIGHT)
        classes = list(sr.load_students().keys()) or ["七年级10班"]
        self.cls_var = tk.StringVar(value=self.cls or classes[0])
        combo = ttk.Combobox(top, values=classes, textvariable=self.cls_var,
                             width=12, state="readonly")
        combo.pack(side=tk.RIGHT, padx=6)
        combo.bind("<<ComboboxSelected>>", lambda e: self._reload())
        tk.Button(top, text="刷新", command=self._reload, bg=BG_CELL, fg=FG_TEXT,
                  relief="flat", padx=10).pack(side=tk.RIGHT, padx=4)

        self.nb = ttk.Notebook(self.win)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)
        self._build_ranking()
        self._build_rewards()
        self._build_group_points()
        self._build_trend()
        self._build_duty()
        self._build_export()

    def _tree(self, parent, columns):
        frame = tk.Frame(parent, bg=BG_PANEL)
        frame.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings")
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=int(width * dpi_scale(self.win)), anchor="center")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        _style_tree(tree)
        return tree

    def _build_ranking(self):
        tab = tk.Frame(self.nb, bg=BG_PANEL)
        self.nb.add(tab, text="  积分榜单  ")
        tk.Label(tab, text="双击一行查看该生全部加分 / 扣分记录", bg=BG_PANEL,
                 fg=FG_DIM, font=(FONT, 9)).pack(anchor="w", padx=10, pady=(8, 4))
        self.rank_tree = self._tree(tab, [
            ("rank", "排名", 70), ("sid", "学号", 110), ("name", "姓名", 110),
            ("group", "小组", 110), ("add", "累计加分", 100),
            ("sub", "累计扣分", 100), ("total", "总分", 90),
        ])
        self.rank_tree.bind("<Double-1>", lambda e: self._open_from_tree(self.rank_tree))

        tk.Label(tab, text="分项得分排行（全档案合计）", bg=BG_PANEL, fg=FG_DIM,
                 font=(FONT, 9)).pack(anchor="w", padx=10, pady=(8, 2))
        self.cat_tree = self._tree(tab, [
            ("rank", "名次", 60), ("category", "分项", 160),
            ("total", "累计得分", 100), ("count", "记录数", 90),
        ])
        self.cat_tree.configure(height=6)

    def _build_group_points(self):
        tab = tk.Frame(self.nb, bg=BG_PANEL)
        self.nb.add(tab, text="  小组专项  ")
        tk.Label(tab, text="只统计直接记在小组名下的分，不含组员个人积分（也不计入个人榜单）",
                 bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).pack(anchor="w", padx=10, pady=(8, 4))
        self.group_tree = self._tree(tab, [
            ("rank", "名次", 60), ("group", "小组", 160),
            ("add", "累计加分", 100), ("sub", "累计扣分", 100),
            ("net", "净分", 90), ("count", "记录数", 90),
        ])

    def _build_rewards(self):
        tab = tk.Frame(self.nb, bg=BG_PANEL)
        self.nb.add(tab, text="  奖励记录  ")
        tk.Label(tab, text="仅展示加分记录，按时间倒序（最多 500 条）", bg=BG_PANEL,
                 fg=FG_DIM, font=(FONT, 9)).pack(anchor="w", padx=10, pady=(8, 4))
        self.reward_tree = self._tree(tab, [
            ("ts", "时间", 150), ("name", "姓名", 100), ("group", "小组", 90),
            ("delta", "分值", 70), ("reason", "事由", 220), ("category", "分项", 100),
        ])
        self.reward_tree.bind("<Double-1>", lambda e: self._open_from_tree(self.reward_tree))

    def _build_trend(self):
        tab = tk.Frame(self.nb, bg=BG_PANEL)
        self.nb.add(tab, text="  成长趋势  ")
        self.trend_canvas = tk.Canvas(tab, bg=BG_CELL, highlightthickness=0)
        self.trend_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 4), pady=8)
        self.cat_canvas = tk.Canvas(tab, bg=BG_CELL, highlightthickness=0, width=320)
        self.cat_canvas.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(4, 8), pady=8)
        self.trend_canvas.bind("<Configure>", lambda e: self._draw_trend())
        self.cat_canvas.bind("<Configure>", lambda e: self._draw_trend())

    def _build_duty(self):
        tab = tk.Frame(self.nb, bg=BG_PANEL)
        self.nb.add(tab, text="  岗位履职  ")
        form = tk.Frame(tab, bg=BG_PANEL)
        form.pack(fill=tk.X, padx=10, pady=8)

        tk.Label(form, text="学生", bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).grid(row=0, column=0, sticky="e")
        self.duty_student = ttk.Combobox(form, state="readonly", width=14)
        self.duty_student.grid(row=0, column=1, padx=6, pady=3)

        tk.Label(form, text="岗位", bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).grid(row=0, column=2, sticky="e")
        self.duty_post = ttk.Combobox(form, width=14, values=[
            "值日组长", "卫生委员", "纪律委员", "学习委员", "体育委员",
            "文艺委员", "生活委员", "图书管理员", "电教管理员", "小组长",
        ])
        self.duty_post.grid(row=0, column=3, padx=6, pady=3)

        tk.Label(form, text="类型", bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).grid(row=0, column=4, sticky="e")
        self.duty_kind = ttk.Combobox(form, state="readonly", width=10, values=["自评", "小组互评"])
        self.duty_kind.current(0)
        self.duty_kind.grid(row=0, column=5, padx=6, pady=3)

        tk.Label(form, text="评分", bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).grid(row=0, column=6, sticky="e")
        self.duty_score = ttk.Combobox(form, state="readonly", width=8,
                                       values=["5", "4", "3", "2", "1"])
        self.duty_score.current(0)
        self.duty_score.grid(row=0, column=7, padx=6, pady=3)

        tk.Label(form, text="评语", bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).grid(row=1, column=0, sticky="e")
        self.duty_comment = tk.Entry(form, width=60, bg=BG_CELL, fg=FG_TEXT,
                                     insertbackground=FG_TEXT, relief="flat")
        self.duty_comment.grid(row=1, column=1, columnspan=6, sticky="we", padx=6, pady=3)

        tk.Button(form, text="录入履职", command=self._add_duty, bg="#2f5f8f", fg=FG_TEXT,
                  relief="flat", padx=14).grid(row=1, column=7, padx=6, pady=3)
        form.columnconfigure(1, weight=1)

        self.duty_tree = self._tree(tab, [
            ("ts", "时间", 150), ("name", "姓名", 100), ("duty", "岗位", 110),
            ("kind", "类型", 90), ("score", "评分", 60), ("comment", "评语", 240),
            ("evaluator", "评价人", 90),
        ])

    def _build_export(self):
        tab = tk.Frame(self.nb, bg=BG_PANEL)
        self.nb.add(tab, text="  台账导出  ")
        box = tk.Frame(tab, bg=BG_PANEL)
        box.pack(fill=tk.X, padx=14, pady=14)

        tk.Label(box, text="导出班级台账（总榜 / 明细 / 分项统计 / 岗位履职）",
                 bg=BG_PANEL, fg=FG_TEXT, font=(FONT, 10, "bold")).pack(anchor="w")
        tk.Button(box, text="导出班级台账 XLSX", command=self._export_class,
                  bg="#2f5f8f", fg=FG_TEXT, relief="flat", padx=14, pady=6).pack(anchor="w", pady=8)

        tk.Frame(box, bg=BG_CELL, height=1).pack(fill=tk.X, pady=8)

        tk.Label(box, text="导出个人台账（某位学生的全部明细与分项汇总）",
                 bg=BG_PANEL, fg=FG_TEXT, font=(FONT, 10, "bold")).pack(anchor="w")
        line = tk.Frame(box, bg=BG_PANEL)
        line.pack(anchor="w", pady=8)
        tk.Label(line, text="学生", bg=BG_PANEL, fg=FG_DIM, font=(FONT, 9)).pack(side=tk.LEFT)
        self.export_student = ttk.Combobox(line, state="readonly", width=18)
        self.export_student.pack(side=tk.LEFT, padx=8)
        tk.Button(line, text="导出该生台账 XLSX", command=self._export_student,
                  bg="#2f5f8f", fg=FG_TEXT, relief="flat", padx=14, pady=6).pack(side=tk.LEFT)

        self.export_hint = tk.Label(tab, text="", bg=BG_PANEL, fg=FG_OK, font=(FONT, 9))
        self.export_hint.pack(anchor="w", padx=14, pady=6)

    # ---------- 数据刷新 ----------
    def _rows(self):
        cls = self.cls_var.get()
        return cls, store.points(cls), store.duties(cls)

    def _reload(self):
        store.seed_all()
        cls, rows, duties = self._rows()
        totals = defaultdict(lambda: {"sid": "", "name": "", "group": "", "add": 0, "sub": 0})
        # 先铺全班名单：没有记录的学生也显示 0 分，避免榜单只剩个别人
        for sid, name, group in store.students_brief(cls):
            totals[sid].update({"sid": sid, "name": name, "group": group})
        for r in rows:
            item = totals[r.get("sid", "")]
            item["sid"] = r.get("sid", "")
            item["name"] = r.get("name", item["name"])
            item["group"] = r.get("group", item["group"])
            delta = int(r.get("delta", 0))
            item["add" if delta >= 0 else "sub"] += delta

        ranking = sorted(totals.values(), key=lambda x: x["add"] + x["sub"], reverse=True)
        self.rank_tree.delete(*self.rank_tree.get_children())
        for i, item in enumerate(ranking, start=1):
            self.rank_tree.insert("", "end", values=(
                i, item["sid"], item["name"], item["group"],
                item["add"], item["sub"], item["add"] + item["sub"]))

        cats = defaultdict(lambda: [0, 0])
        for r in rows:
            item = cats[r.get("category", "其他")]
            item[0] += int(r.get("delta", 0))
            item[1] += 1
        self.cat_tree.delete(*self.cat_tree.get_children())
        for i, (cat, (total, count)) in enumerate(
                sorted(cats.items(), key=lambda kv: kv[1][0], reverse=True), start=1):
            self.cat_tree.insert("", "end", values=(i, cat, total, count))

        self.reward_tree.delete(*self.reward_tree.get_children())
        rewards = [r for r in rows if int(r.get("delta", 0)) > 0]
        for r in sorted(rewards, key=lambda x: x.get("ts", ""), reverse=True)[:500]:
            self.reward_tree.insert("", "end", values=(
                r.get("ts", ""), r.get("name", ""), r.get("group", ""),
                f"+{int(r.get('delta', 0))}", r.get("reason", ""), r.get("category", "其他")))

        gagg = defaultdict(lambda: [0, 0, 0])
        for r in store.group_points(cls):
            delta = int(r.get("delta", 0))
            item = gagg[r.get("group", "")]
            item[0 if delta >= 0 else 1] += delta
            item[2] += 1
        self.group_tree.delete(*self.group_tree.get_children())
        for i, (gname, (add, sub, cnt)) in enumerate(
                sorted(gagg.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True),
                start=1):
            self.group_tree.insert("", "end", values=(
                i, gname, add, sub, add + sub, cnt))

        self.duty_tree.delete(*self.duty_tree.get_children())
        for r in sorted(duties, key=lambda x: x.get("ts", ""), reverse=True):
            self.duty_tree.insert("", "end", values=(
                r.get("ts", ""), r.get("name", ""), r.get("duty", ""), r.get("kind", ""),
                r.get("score", ""), r.get("comment", ""), r.get("evaluator", "")))

        students = store.students_brief(cls)
        self._students = students
        names = [f"{name}（{sid}）" for sid, name, _ in students]
        self.duty_student.configure(values=names)
        if names:
            self.duty_student.current(0)
        self.export_student.configure(values=names)
        if names:
            self.export_student.current(0)

        self._draw_trend()

    def _draw_trend(self):
        cls, rows, _ = self._rows()
        by_day = defaultdict(lambda: defaultdict(int))
        for r in rows:
            day = (r.get("ts") or "")[:10]
            if day:
                by_day[r.get("name", "")][day] += int(r.get("delta", 0))
        total = defaultdict(int)
        for name, days in by_day.items():
            total[name] = sum(days.values())
        top = sorted(total.items(), key=lambda kv: kv[1], reverse=True)[:8]

        series = {}
        for name, _ in top:
            running, points = 0, []
            for day in sorted(by_day[name]):
                running += by_day[name][day]
                points.append((day, running))
            if points:
                series[name] = points
        charts.line_chart(self.trend_canvas, series, title=f"{cls} 学生积分成长曲线（前 8 名）")

        cats = defaultdict(int)
        for r in rows:
            cats[r.get("category", "其他")] += int(r.get("delta", 0))
        charts.bar_chart(self.cat_canvas, sorted(cats.items(), key=lambda kv: kv[1],
                                                 reverse=True), title="班级分项得分分布")

    # ---------- 交互 ----------
    def _open_from_tree(self, tree):
        sel = tree.selection()
        if not sel:
            return
        values = tree.item(sel[0], "values")
        sid = values[1] if tree is self.rank_tree else ""
        name = values[2] if tree is self.rank_tree else values[1]
        if not sid:
            for s, n, _ in getattr(self, "_students", []):
                if n == name:
                    sid = s
                    break
        self.open_student_archive(sid, name)

    def open_student_archive(self, sid: str, name: str = ""):
        cls = self.cls_var.get()
        rows = [r for r in store.points(cls) if r.get("sid") == sid]
        duties = [r for r in store.duties(cls) if r.get("sid") == sid]
        name = name or (rows[0].get("name", sid) if rows else sid)

        win = tk.Toplevel(self.win)
        win.title(f"成长档案 · {name}")
        center_window(win, self.win, 860, 620)
        win.configure(bg=BG_MAIN)

        head = tk.Frame(win, bg=BG_MAIN)
        head.pack(fill=tk.X, padx=14, pady=10)
        tk.Label(head, text=name, bg=BG_MAIN, fg=FG_ACCENT,
                 font=(FONT, 16, "bold")).pack(side=tk.LEFT)
        total = sum(int(r.get("delta", 0)) for r in rows)
        tk.Label(head, text=f"  学号 {sid}    累计积分 {total}    记录 {len(rows)} 条",
                 bg=BG_MAIN, fg=FG_DIM, font=(FONT, 10)).pack(side=tk.LEFT)

        tree = ttk.Treeview(win, columns=("ts", "delta", "reason", "category", "week"),
                            show="headings")
        for key, title, width in (("ts", "时间", 150), ("delta", "分值", 70),
                                  ("reason", "事由", 240), ("category", "分项", 110),
                                  ("week", "周次", 100)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="center")
        for r in sorted(rows, key=lambda x: x.get("ts", ""), reverse=True):
            tree.insert("", "end", values=(r.get("ts", ""), int(r.get("delta", 0)),
                                           r.get("reason", ""), r.get("category", "其他"),
                                           r.get("week", "")))
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        _style_tree(tree)

        if duties:
            tk.Label(win, text="岗位履职：" + "；".join(
                f"{d.get('ts','')[:10]} {d.get('duty','')} {d.get('kind','')} {d.get('score','')}分"
                for d in duties[-5:]), bg=BG_MAIN, fg=FG_DIM, font=(FONT, 9),
                wraplength=800, justify=tk.LEFT).pack(anchor="w", padx=14, pady=(0, 10))

    def _add_duty(self):
        cls = self.cls_var.get()
        idx = self.duty_student.current()
        if idx < 0 or idx >= len(getattr(self, "_students", [])):
            messagebox.showinfo("岗位履职", "请先选择学生", parent=self.win)
            return
        sid, name, _group = self._students[idx]
        post = self.duty_post.get().strip() or "值日组长"
        kind = self.duty_kind.get() or "自评"
        score = int(self.duty_score.get() or 5)
        comment = self.duty_comment.get().strip()
        store.add_duty(cls, sid, name, post, kind, score, comment,
                       evaluator=name if kind == "自评" else "小组")
        self.duty_comment.delete(0, tk.END)
        self._reload()
        self.nb.select(3)
        if self.host is not None:
            try:
                self.host._set_status(f"已录入 {name} 的岗位履职（{kind} {score} 分）")
            except Exception:
                pass

    def _export_class(self):
        cls = self.cls_var.get()
        path = filedialog.asksaveasfilename(
            parent=self.win, title="导出班级积分台账",
            defaultextension=".xlsx", initialfile=ledger_export.default_name(cls, "班级积分台账"),
            filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            ledger_export.export_class(cls, path)
            self.export_hint.configure(text=f"已导出：{path}", fg=FG_OK)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.win)

    def _export_student(self):
        cls = self.cls_var.get()
        idx = self.export_student.current()
        if idx < 0 or idx >= len(getattr(self, "_students", [])):
            messagebox.showinfo("导出个人台账", "请先选择学生", parent=self.win)
            return
        sid, name, _group = self._students[idx]
        path = filedialog.asksaveasfilename(
            parent=self.win, title="导出个人积分台账",
            defaultextension=".xlsx",
            initialfile=ledger_export.default_name(cls, f"{name}_个人积分台账"),
            filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            ledger_export.export_student(cls, sid, path)
            self.export_hint.configure(text=f"已导出：{path}", fg=FG_OK)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.win)
