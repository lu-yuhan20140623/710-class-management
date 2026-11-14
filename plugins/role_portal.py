"""
角色门户（插件）

- 教师端 / 学生端分开：学生端为独立只读界面，不暴露任何加减分、卫生、调课入口
- 学生端包含：我的积分、我的记录、班级排行、荣誉榜、今日课程与倒计时
- 学生个人自定义页面：昵称、头像、主题色、个性签名、目标积分
- 教师端顶部按钮「学生视图」快速切换；返回教师端需要密钥
"""

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import plugin_api as plug
import schedule
from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
    FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_DANGER, FG_OK,
    AskPasswordDialog, dpi_scale,
)

PLUGIN = {
    "id": "role_portal",
    "name": "教师 / 学生角色门户",
    "version": "1.0.0",
    "api_version": 1,
    "description": "教师端与学生端分离，学生个人自定义主页与今日课程",
    "author": "710",
    "requires": [],
    "priority": 30,
}

FONT = "Microsoft YaHei UI"
AVATARS = ["🐻", "🐱", "🐶", "🐰", "🦊", "🐼", "🐨", "🐯", "🦁", "🐸",
           "🐙", "🦄", "🐧", "🦉", "🌟", "🍀", "🚀", "🎈"]
THEMES = {
    "aurora": ("极光", "#6c8cff", "#b06cff"),
    "ocean": ("海洋", "#3fb6c9", "#2f7fd1"),
    "sakura": ("樱花", "#ff8fb1", "#ff6b9a"),
    "forest": ("森林", "#59b06c", "#3f8f5a"),
    "sunset": ("日落", "#ffb26c", "#ff7a59"),
}

_PORTALS = {}


def _place(win, width, height):
    k = dpi_scale(win)
    w, h = int(width * k), int(height * k)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = max(8, (sw - w) // 2)
    y = max(16, (sh - h) // 3)
    win.geometry(f"{w}x{h}+{x}+{y}")


def _btn(parent, text, command, primary=False):
    return tk.Button(
        parent, text=text, command=command, font=(FONT, 10, "bold" if primary else "normal"),
        bg=BG_IN_CLASS if primary else BG_CELL, fg=FG_TEXT,
        activebackground="#4b7b4b" if primary else BG_CELL_ALT,
        activeforeground=FG_TEXT, relief=tk.FLAT, padx=12, pady=5, cursor="hand2")


def _mix(c1, c2, t):
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class StudentPortalWindow:
    def __init__(self, ctx, class_name=None, sid=None, page="home"):
        self.ctx = ctx
        self.data = ctx.data
        self.win = tk.Toplevel(ctx.app)
        self.win.title("学生端 · 课堂助手")
        self.win.configure(bg=BG_MAIN)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._clock_job = None
        self._current_page = page

        self.all_students = self.data.load_students()
        self.all_groups = self.data.load_groups()
        names = self.data.class_names() or list(self.all_students.keys())
        self.classes = [n for n in names if n in self.all_students] or \
            list(self.all_students.keys())
        saved_class = self.ctx.settings.get("last_class")
        self.cls = class_name or (saved_class if saved_class in self.classes else
                                  (self.classes[0] if self.classes else ""))
        if self.cls not in self.classes and self.classes:
            self.cls = self.classes[0]
        self.students = self.all_students.get(self.cls, {})

        last_map = self.ctx.settings.get("last_student", {})
        pick = sid or last_map.get(self.cls)
        if pick not in self.students:
            pick = next(iter(self.students), "")
        self.sid = pick

        self._build_header()
        body = tk.Frame(self.win, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(4, 0))
        nav = tk.Frame(body, bg=BG_PANEL, width=138)
        nav.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        nav.pack_propagate(False)
        self.nav_buttons = {}
        for key, label in (("home", "🏠 我的积分"), ("records", "🧾 我的记录"),
                           ("ranking", "🏅 班级排行"), ("honor", "🏆 荣誉榜"),
                           ("schedule", "📅 今日课程"), ("profile", "🪪 我的主页")):
            btn = tk.Button(nav, text=label, font=(FONT, 11), bg=BG_PANEL,
                            fg=FG_TEXT, activebackground=BG_CELL,
                            activeforeground=FG_TEXT, relief=tk.FLAT, anchor="w",
                            padx=14, pady=12, cursor="hand2",
                            command=lambda k=key: self.show_page(k))
            btn.pack(fill=tk.X, pady=1)
            self.nav_buttons[key] = btn

        self.content = tk.Frame(body, bg=BG_PANEL,
                                highlightbackground=BG_CELL, highlightthickness=1)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.footer = tk.Label(
            self.win, text="学生端为只读界面 · 加减分与数据修改请在教师端完成",
            font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM, anchor="w")
        self.footer.pack(fill=tk.X, padx=20, pady=(4, 8))

        self.win.bind("<Escape>", lambda e: self.close())
        _place(self.win, 1160, 720)
        self.show_page(page)

    # ---------- 头部 ----------
    def _build_header(self):
        header = tk.Frame(self.win, bg=BG_MAIN)
        header.pack(fill=tk.X, padx=18, pady=(12, 4))
        tk.Label(header, text="🎓 学生端", font=(FONT, 19, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        tk.Label(header, text=self.cls, font=(FONT, 11), bg=BG_MAIN,
                 fg=FG_TEXT).pack(side=tk.LEFT, padx=(14, 6))

        self.student_box = ttk.Combobox(header, state="readonly", width=16,
                                        font=(FONT, 10))
        self.student_box.pack(side=tk.LEFT)
        self.student_box.bind("<<ComboboxSelected>>", self._on_student_change)
        self._refresh_student_box()

        _btn(header, "返回教师端（需密钥）", self._back_to_teacher).pack(
            side=tk.RIGHT, padx=4)
        _btn(header, "关闭", self.close).pack(side=tk.RIGHT, padx=4)

    def _refresh_student_box(self):
        options = [f"{sid} {info.get('name', '')}"
                   for sid, info in sorted(self.students.items())
                   if isinstance(info, dict)]
        self.student_options = options
        self.student_box["values"] = options
        for text in options:
            if text.startswith(self.sid + " "):
                self.student_box.set(text)
                break
        if options and not self.student_box.get():
            self.student_box.set(options[0])
            self.sid = options[0].split(" ", 1)[0]

    def _on_student_change(self, _event=None):
        text = self.student_box.get()
        self.sid = text.split(" ", 1)[0] if text else ""
        last = self.ctx.settings.get("last_student", {})
        last[self.cls] = self.sid
        self.ctx.settings.update({"last_student": last, "last_class": self.cls})
        self.show_page(self._current_page)

    def _back_to_teacher(self):
        if not AskPasswordDialog(self.win, "返回教师端需要密钥").result:
            return
        self.close()
        try:
            self.ctx.app.deiconify()
            self.ctx.app.lift()
            self.ctx.app.focus_force()
        except tk.TclError:
            pass

    # ---------- 页面 ----------
    def show_page(self, key):
        self._current_page = key
        if self._clock_job is not None:
            try:
                self.win.after_cancel(self._clock_job)
            except tk.TclError:
                pass
            self._clock_job = None
        for k, btn in self.nav_buttons.items():
            btn.config(bg=BG_CELL if k == key else BG_PANEL,
                       fg=FG_ACCENT if k == key else FG_TEXT)
        for child in self.content.winfo_children():
            child.destroy()

        self.all_students = self.data.load_students()
        self.all_groups = self.data.load_groups()
        self.students = self.all_students.get(self.cls, {})
        if self.sid not in self.students:
            self.sid = next(iter(self.students), "")

        builders = {
            "home": self._page_home, "records": self._page_records,
            "ranking": self._page_ranking, "honor": self._page_honor,
            "schedule": self._page_schedule, "profile": self._page_profile,
        }
        try:
            builders.get(key, self._page_home)(self.content)
        except Exception as exc:
            tk.Label(self.content, text=f"页面加载失败：{exc}", font=(FONT, 11),
                     bg=BG_PANEL, fg=FG_DANGER).pack(pady=40)

    def _info(self):
        return self.students.get(self.sid, {})

    def _group_name(self):
        gmap = self.data.group_map(self.all_groups.get(self.cls, {}), self.students)
        return gmap.get(self.sid, "未分组")

    def _rank(self):
        for rank, sid, _name, _group, _total in self.data.rank_students(
                self.all_students, self.all_groups, self.cls):
            if sid == self.sid:
                return rank
        return 0

    def profile(self):
        profiles = self.ctx.settings.get("profiles", {})
        data = profiles.get(self.cls, {}).get(self.sid, {})
        info = self._info()
        default_avatar = AVATARS[sum(ord(c) for c in str(self.sid)) % len(AVATARS)]
        return {
            "nickname": data.get("nickname") or info.get("name", "同学"),
            "avatar": data.get("avatar") or default_avatar,
            "theme": data.get("theme") if data.get("theme") in THEMES else "aurora",
            "motto": data.get("motto", "每天进步一点点"),
            "goal": int(data.get("goal", 100) or 100),
        }

    def save_profile(self, patch):
        profiles = self.ctx.settings.get("profiles", {})
        profiles.setdefault(self.cls, {}).setdefault(self.sid, {}).update(patch)
        self.ctx.settings.set("profiles", profiles)

    # ---------- 我的积分 ----------
    def _page_home(self, parent):
        info = self._info()
        if not info:
            tk.Label(parent, text="该班级暂时没有学生数据", font=(FONT, 12),
                     bg=BG_PANEL, fg=FG_DIM).pack(pady=60)
            return
        profile = self.profile()
        total = self.data.total(info)
        weekly = self.data.weekly_net(info, self.data.week_key())
        rank = self._rank()
        count = len(self.data.records(info))
        self._hero(parent, profile, total, rank)

        cards = tk.Frame(parent, bg=BG_PANEL)
        cards.pack(fill=tk.X, padx=18, pady=(12, 6))
        for label, value, color in (
                ("当前积分", str(total), FG_ACCENT),
                ("本周净得分", f"{weekly:+d}", FG_OK if weekly >= 0 else FG_DANGER),
                ("班级排名", f"第 {rank} 名" if rank else "—", FG_WARN),
                ("积分记录", f"{count} 条", FG_TEXT)):
            card = tk.Frame(cards, bg=BG_CELL)
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            tk.Label(card, text=label, font=(FONT, 9), bg=BG_CELL, fg=FG_DIM)\
                .pack(anchor="w", padx=14, pady=(9, 0))
            tk.Label(card, text=value, font=(FONT, 18, "bold"), bg=BG_CELL,
                     fg=color).pack(anchor="w", padx=14, pady=(0, 9))

        # 目标进度
        goal = max(1, profile["goal"])
        progress = max(0.0, min(1.0, total / goal))
        goal_box = tk.Frame(parent, bg=BG_PANEL)
        goal_box.pack(fill=tk.X, padx=22, pady=(2, 8))
        tk.Label(goal_box, text=f"我的目标：{goal} 分　当前 {total} / {goal}",
                 font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM).pack(anchor="w")
        track = tk.Frame(goal_box, bg="#2f2f3f", height=12)
        track.pack(fill=tk.X, pady=4)
        fill = tk.Frame(track, bg=FG_OK, height=12)
        fill.place(x=0, y=0, relwidth=progress, relheight=1)

        tk.Label(parent, text="最近积分记录", font=(FONT, 11, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", padx=22, pady=(6, 2))
        records = [r for r in self.data.records(info) if isinstance(r, dict)]
        if not records:
            tk.Label(parent, text="还没有积分记录，加油鸭！", font=(FONT, 10),
                     bg=BG_PANEL, fg=FG_DIM).pack(anchor="w", padx=22, pady=10)
            return
        for rec in list(reversed(records))[:6]:
            delta = self.data.delta(rec)
            row = tk.Frame(parent, bg=BG_CELL)
            row.pack(fill=tk.X, padx=22, pady=2)
            tk.Label(row, text=f"{delta:+d}", font=(FONT, 13, "bold"), bg=BG_CELL,
                     fg=FG_OK if delta >= 0 else FG_DANGER, width=5)\
                .pack(side=tk.LEFT, padx=6, pady=6)
            tk.Label(row, text=rec.get("reason", ""), font=(FONT, 10), bg=BG_CELL,
                     fg=FG_TEXT, anchor="w").pack(side=tk.LEFT, fill=tk.X,
                                                  expand=True)
            tk.Label(row, text=rec.get("time", ""), font=(FONT, 8), bg=BG_CELL,
                     fg=FG_DIM).pack(side=tk.RIGHT, padx=8)

    def _hero(self, parent, profile, total, rank):
        name, c1, c2 = THEMES[profile["theme"]]
        holder = tk.Frame(parent, bg=BG_PANEL)
        holder.pack(fill=tk.X, padx=14, pady=(14, 0))
        canvas = tk.Canvas(holder, height=int(170 * dpi_scale(parent)),
                           bg=BG_PANEL, highlightthickness=0, bd=0)
        canvas.pack(fill=tk.X)

        def draw(_event=None):
            canvas.delete("all")
            w = canvas.winfo_width() or 800
            h = int(170 * dpi_scale(canvas))
            steps = 36
            for i in range(steps):
                canvas.create_rectangle(
                    0, h * i / steps, w, h * (i + 1) / steps + 1,
                    fill=_mix(c1, c2, i / steps), outline="")
            canvas.create_oval(w - 190, -60, w + 40, h + 40, fill=_mix(c2, "#ffffff", 0.18),
                               outline="")
            canvas.create_oval(w - 340, 90, w - 230, h + 60,
                               fill=_mix(c1, "#ffffff", 0.25), outline="")
            canvas.create_oval(28, 34, 128, 134, fill="#ffffff", outline="")
            canvas.create_text(78, 84, text=profile["avatar"], font=(FONT, 40))
            canvas.create_text(148, 62, text=profile["nickname"], anchor="w",
                               font=(FONT, 23, "bold"), fill="#ffffff")
            canvas.create_text(150, 96, text=f"{self.cls} · {self._group_name()}",
                               anchor="w", font=(FONT, 10), fill="#e8ecff")
            canvas.create_text(150, 121, text=f"“{profile['motto']}”", anchor="w",
                               font=(FONT, 10), fill="#dfe6ff")
            canvas.create_text(w - 40, 50, text=str(total), anchor="e",
                               font=(FONT, 40, "bold"), fill="#ffffff")
            canvas.create_text(w - 40, 94, text="总积分", anchor="e",
                               font=(FONT, 10), fill="#e8ecff")
            if rank:
                canvas.create_text(w - 40, 124, text=f"班级第 {rank} 名", anchor="e",
                                   font=(FONT, 11, "bold"), fill="#fff4c2")

        canvas.bind("<Configure>", draw)
        canvas.after_idle(draw)

    # ---------- 我的记录 ----------
    def _page_records(self, parent):
        info = self._info()
        records = [r for r in self.data.records(info) if isinstance(r, dict)]
        add_sum = sum(self.data.delta(r) for r in records if self.data.delta(r) > 0)
        sub_sum = sum(self.data.delta(r) for r in records if self.data.delta(r) < 0)
        head = tk.Frame(parent, bg=BG_PANEL)
        head.pack(fill=tk.X, padx=20, pady=12)
        tk.Label(head, text=f"🧾 我的积分记录 · 共 {len(records)} 条",
                 font=(FONT, 15, "bold"), bg=BG_PANEL, fg=FG_TEXT).pack(side=tk.LEFT)
        tk.Label(head, text=f"累计加分 +{add_sum}　累计扣分 {sub_sum}",
                 font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM).pack(side=tk.RIGHT)

        style = ttk.Style()
        style.configure("Portal.Treeview", background=BG_CELL,
                        fieldbackground=BG_CELL, foreground=FG_TEXT,
                        rowheight=max(24, int(28 * dpi_scale(parent))),
                        borderwidth=0, font=(FONT, 9))
        style.configure("Portal.Treeview.Heading", background=BG_PANEL,
                        foreground=FG_ACCENT, relief=tk.FLAT,
                        font=(FONT, 9, "bold"))
        style.map("Portal.Treeview", background=[("selected", "#2f5f8f")])
        body = tk.Frame(parent, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))
        tree = ttk.Treeview(body, columns=("time", "delta", "reason", "week"),
                            show="headings", style="Portal.Treeview")
        for col, text, width, anchor in (
                ("time", "时间", 160, "center"), ("delta", "分值", 70, "center"),
                ("reason", "理由", 320, "w"), ("week", "周次", 90, "center")):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor=anchor)
        sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for rec in reversed(records):
            delta = self.data.delta(rec)
            tree.insert("", tk.END, values=(
                rec.get("time", ""), f"{delta:+d}", rec.get("reason", ""),
                self.data.record_week(rec)))

    # ---------- 班级排行 ----------
    def _page_ranking(self, parent):
        tk.Label(parent, text="🏅 班级排行", font=(FONT, 17, "bold"),
                 bg=BG_PANEL, fg=FG_ACCENT).pack(anchor="w", padx=22, pady=(14, 2))
        tk.Label(parent, text="学生积分榜前 10 名 / 我的位置", font=(FONT, 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(anchor="w", padx=22)

        rows = self.data.rank_students(self.all_students, self.all_groups, self.cls)
        top = [(r[0], r[1], r[3], r[4]) for r in rows[:10]]
        mine = next((r for r in rows if r[1] == self.sid), None)
        if mine and mine not in rows[:10]:
            top = top + [(mine[0], mine[1], mine[3], mine[4])]
        self._rank_rows(parent, top, "student")

        tk.Label(parent, text="小组积分榜", font=(FONT, 13, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", padx=22, pady=(14, 2))
        grows = self.data.rank_groups(self.all_students, self.all_groups, self.cls)[:8]
        my_group = self._group_name()
        grows = [(rank, name, f"{count} 人", total)
                 for rank, name, count, total in grows]
        self._rank_rows(parent, grows, "group", highlight=my_group)

    def _rank_rows(self, parent, rows, kind, highlight=""):
        if not rows:
            tk.Label(parent, text="暂无排行数据", font=(FONT, 10),
                     bg=BG_PANEL, fg=FG_DIM).pack(anchor="w", padx=22, pady=8)
            return
        max_val = max(1, max(abs(r[-1]) for r in rows))
        for rank, name, extra, value in rows:
            is_me = (name == self.sid) if kind == "student" else (name == highlight)
            bg = "#2b4a3a" if is_me else BG_CELL
            row = tk.Frame(parent, bg=bg)
            row.pack(fill=tk.X, padx=22, pady=2)
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else ""
            tk.Label(row, text=f"{medal}{rank}", font=(FONT, 10, "bold"), bg=bg,
                     fg=FG_ACCENT if is_me else FG_DIM, width=6)\
                .pack(side=tk.LEFT, pady=6)
            display = name
            if kind == "student":
                info = self.students.get(name, {})
                display = f"{name} {info.get('name', '')}"
                if is_me:
                    display += "（我）"
            elif is_me:
                display += "（我的小组）"
            tk.Label(row, text=display, font=(FONT, 10, "bold" if is_me else "normal"),
                     bg=bg, fg=FG_TEXT if not is_me else "#bff0c8",
                     width=18, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=extra, font=(FONT, 9), bg=bg, fg=FG_DIM,
                     width=8).pack(side=tk.LEFT)
            track = tk.Frame(row, bg="#2f2f3f", height=10)
            track.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
            tk.Frame(track, bg=FG_ACCENT if value >= 0 else FG_DANGER,
                     height=10, width=max(2, int(200 * abs(value) / max_val)))\
                .pack(side=tk.LEFT)
            tk.Label(row, text=f"{value}", font=(FONT, 11, "bold"), bg=bg,
                     fg=FG_OK if value >= 0 else FG_DANGER, width=6,
                     anchor="e").pack(side=tk.LEFT, padx=(0, 8))

    # ---------- 荣誉榜 ----------
    def _page_honor(self, parent):
        honors = self.data.honors(self.all_students, self.all_groups, self.cls)
        tk.Label(parent, text=f"🏆 荣誉榜 · {honors['week']}",
                 font=(FONT, 17, "bold"), bg=BG_PANEL, fg="#ffd166")\
            .pack(anchor="w", padx=22, pady=(14, 2))
        tk.Label(parent, text="总积分 / 小组积分 / 本周之星 / 进步之星",
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
            ("🥇 总积分榜", total_rows, FG_ACCENT),
            ("👥 小组榜", group_rows, FG_OK),
            ("🌟 本周之星", week_rows, "#ffd166"),
            ("🚀 进步之星", imp_rows, FG_WARN),
        ]
        for idx, (title, rows, color) in enumerate(cards):
            card = tk.Frame(grid, bg=BG_CELL, highlightbackground=color,
                            highlightthickness=1)
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=8, pady=6)
            tk.Label(card, text=title, font=(FONT, 12, "bold"), bg=BG_CELL,
                     fg=color).pack(anchor="w", padx=14, pady=(9, 4))
            if not rows:
                tk.Label(card, text="暂无数据", font=(FONT, 9), bg=BG_CELL,
                         fg=FG_DIM).pack(anchor="w", padx=14, pady=8)
                continue
            for rank, name, value in rows:
                line = tk.Frame(card, bg=BG_CELL)
                line.pack(fill=tk.X, padx=14, pady=3)
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉"
                tk.Label(line, text=medal, font=(FONT, 11), bg=BG_CELL,
                         fg=color).pack(side=tk.LEFT)
                tk.Label(line, text=str(name), font=(FONT, 10, "bold"), bg=BG_CELL,
                         fg=FG_TEXT).pack(side=tk.LEFT, padx=6)
                tk.Label(line, text=f"{value:+d} 分", font=(FONT, 10, "bold"),
                         bg=BG_CELL, fg=FG_OK if value >= 0 else FG_DANGER)\
                    .pack(side=tk.RIGHT)

    # ---------- 今日课程 ----------
    def _page_schedule(self, parent):
        head = tk.Frame(parent, bg=BG_PANEL)
        head.pack(fill=tk.X, padx=22, pady=(14, 4))
        tk.Label(head, text="📅 今日课程", font=(FONT, 17, "bold"), bg=BG_PANEL,
                 fg=FG_ACCENT).pack(side=tk.LEFT)
        self.clock_label = tk.Label(head, text="", font=(FONT, 13, "bold"),
                                    bg=BG_PANEL, fg=FG_WARN)
        self.clock_label.pack(side=tk.RIGHT)
        self.schedule_state = tk.Label(parent, text="", font=(FONT, 10),
                                       bg=BG_PANEL, fg=FG_DIM, anchor="w")
        self.schedule_state.pack(fill=tk.X, padx=22, pady=(0, 6))

        day = schedule.get_day_index()
        if day < 0:
            tk.Label(parent, text="今天是周末，没有课程安排～", font=(FONT, 13),
                     bg=BG_PANEL, fg=FG_ACCENT).pack(pady=50)
            return
        info = schedule.find_current_period()
        active_key = info.get("current_period") if info.get("state") == "in_class" else None
        slots = schedule.day_slots(day)
        tk.Label(parent, text=schedule.WEEKDAY_NAMES[day], font=(FONT, 11, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", padx=22, pady=(2, 4))
        for slot in slots:
            active = slot["key"] == active_key
            bg = BG_IN_CLASS if active else BG_CELL
            row = tk.Frame(parent, bg=bg)
            row.pack(fill=tk.X, padx=22, pady=2)
            tk.Label(row, text=slot["name"], font=(FONT, 10, "bold"), bg=bg,
                     fg=FG_TEXT if active else FG_DIM, width=9, anchor="w")\
                .pack(side=tk.LEFT, padx=6, pady=7)
            tk.Label(row, text=f"{slot['start'].strftime('%H:%M')} - "
                               f"{slot['end'].strftime('%H:%M')}",
                     font=(FONT, 9), bg=bg, fg=FG_DIM, width=14)\
                .pack(side=tk.LEFT)
            tk.Label(row, text=slot["subject"], font=(FONT, 11, "bold"), bg=bg,
                     fg=FG_OK if active else FG_TEXT, anchor="w")\
                .pack(side=tk.LEFT, padx=10)
            if active:
                tk.Label(row, text="● 当前", font=(FONT, 9, "bold"), bg=bg,
                         fg=FG_OK).pack(side=tk.RIGHT, padx=10)

        self._tick_clock()

    def _tick_clock(self):
        if self._current_page != "schedule" or not self.win.winfo_exists():
            return
        info = schedule.find_current_period()
        state = info.get("state")
        now = datetime.now()
        if state == "in_class":
            end = info.get("current_end")
            target = datetime.combine(now.date(), end) if end else now
            left = max(0, int((target - now).total_seconds()))
            self.clock_label.config(text=f"距下课 {self._fmt(left)}", fg=FG_OK)
            self.schedule_state.config(
                text=f"正在上 {info.get('current_name', '')} · "
                     f"{info.get('current_subject', '')}，"
                     f"{end.strftime('%H:%M') if end else ''} 下课")
        elif state in ("before_class", "between_class"):
            left = max(0, int(info.get("seconds_to_next", 0)))
            self.clock_label.config(text=f"距上课 {self._fmt(left)}", fg=FG_WARN)
            start = info.get("next_start")
            self.schedule_state.config(
                text=f"下一节 {info.get('next_name', '')} · "
                     f"{info.get('next_subject', '')}"
                     + (f"，{start.strftime('%H:%M')} 上课" if start else ""))
        elif state == "disabled":
            self.clock_label.config(text="已禁用", fg=FG_DANGER)
            self.schedule_state.config(text=info.get("disabled_note", ""))
        elif state == "weekend":
            self.clock_label.config(text="周末", fg=FG_ACCENT)
            self.schedule_state.config(text="今天没有课程安排")
        else:
            self.clock_label.config(text="已放学", fg=FG_ACCENT)
            self.schedule_state.config(text="今日课程已结束")
        self._clock_job = self.win.after(1000, self._tick_clock)

    @staticmethod
    def _fmt(seconds):
        hours, rem = divmod(max(0, seconds), 3600)
        minutes, secs = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else \
            f"{minutes:02d}:{secs:02d}"

    # ---------- 我的主页 ----------
    def _page_profile(self, parent):
        profile = self.profile()
        info = self._info()
        total = self.data.total(info) if info else 0
        rank = self._rank()
        self._hero(parent, profile, total, rank)

        body = tk.Frame(parent, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=22, pady=10)
        tk.Label(body, text="我的主页设置", font=(FONT, 13, "bold"), bg=BG_PANEL,
                 fg=FG_TEXT).pack(anchor="w")
        tk.Label(body, text="这里的内容只有你能改，展示在首页和班级大屏上。",
                 font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM).pack(anchor="w", pady=(0, 8))

        grid = tk.Frame(body, bg=BG_PANEL)
        grid.pack(fill=tk.X)
        fields = [
            ("昵称", profile["nickname"]),
            ("头像", profile["avatar"]),
            ("主题", THEMES[profile["theme"]][0]),
            ("个性签名", profile["motto"]),
            ("目标积分", f"{profile['goal']} 分"),
            ("学号 / 小组", f"{self.sid} · {self._group_name()}"),
        ]
        for idx, (label, value) in enumerate(fields):
            tk.Label(grid, text=label, font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM,
                     width=10, anchor="w")\
                .grid(row=idx // 2, column=(idx % 2) * 2, sticky="w", padx=(0, 6), pady=5)
            tk.Label(grid, text=value, font=(FONT, 11), bg=BG_CELL, fg=FG_TEXT,
                     width=22, anchor="w")\
                .grid(row=idx // 2, column=(idx % 2) * 2 + 1, sticky="w",
                      padx=(0, 20), pady=5, ipadx=8, ipady=3)

        holder = tk.Frame(body, bg=BG_PANEL)
        holder.pack(anchor="w", pady=(14, 0))
        _btn(holder, "✏️ 编辑我的主页", self._open_editor, primary=True).pack()

    def _open_editor(self):
        ProfileEditor(self)

    # ---------- 关闭 ----------
    def close(self):
        if self._clock_job is not None:
            try:
                self.win.after_cancel(self._clock_job)
            except tk.TclError:
                pass
            self._clock_job = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ===================== 个人主页编辑 =====================
class ProfileEditor:
    def __init__(self, portal):
        self.portal = portal
        self.sid = portal.sid
        self.profile = portal.profile()
        self.win = tk.Toplevel(portal.win)
        self.win.title("编辑我的主页")
        self.win.configure(bg=BG_MAIN)
        self.win.transient(portal.win)

        tk.Label(self.win, text="✏️ 编辑我的主页", font=(FONT, 16, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(anchor="w", padx=22, pady=(16, 8))
        form = tk.Frame(self.win, bg=BG_MAIN)
        form.pack(fill=tk.BOTH, expand=True, padx=22)

        tk.Label(form, text="昵称", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        self.nickname = tk.Entry(form, font=(FONT, 11), bg=BG_CELL, fg=FG_TEXT,
                                 insertbackground=FG_TEXT, relief=tk.FLAT, width=24)
        self.nickname.insert(0, self.profile["nickname"])
        self.nickname.grid(row=0, column=1, sticky="w", ipady=4)

        tk.Label(form, text="个性签名", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=6)
        self.motto = tk.Entry(form, font=(FONT, 11), bg=BG_CELL, fg=FG_TEXT,
                              insertbackground=FG_TEXT, relief=tk.FLAT, width=34)
        self.motto.insert(0, self.profile["motto"])
        self.motto.grid(row=1, column=1, columnspan=2, sticky="w", ipady=4)

        tk.Label(form, text="目标积分", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=2, column=0, sticky="w", pady=6)
        self.goal = tk.Spinbox(form, from_=0, to=10000, increment=10,
                               font=(FONT, 11), bg=BG_CELL, fg=FG_TEXT,
                               relief=tk.FLAT, width=8,
                               buttonbackground=BG_CELL, insertbackground=FG_TEXT)
        self.goal.delete(0, tk.END)
        self.goal.insert(0, str(self.profile["goal"]))
        self.goal.grid(row=2, column=1, sticky="w", pady=6)

        tk.Label(form, text="头像", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=3, column=0, sticky="nw", pady=6)
        self.avatar_var = tk.StringVar(value=self.profile["avatar"])
        avatar_box = tk.Frame(form, bg=BG_MAIN)
        avatar_box.grid(row=3, column=1, columnspan=2, sticky="w", pady=6)
        for idx, emoji in enumerate(AVATARS):
            rb = tk.Radiobutton(avatar_box, text=emoji, variable=self.avatar_var,
                                value=emoji, font=(FONT, 14), bg=BG_MAIN,
                                fg=FG_TEXT, selectcolor=BG_CELL,
                                activebackground=BG_MAIN, activeforeground=FG_ACCENT,
                                relief=tk.FLAT, cursor="hand2", indicatoron=False,
                                padx=4, pady=2)
            rb.grid(row=idx // 9, column=idx % 9, padx=1, pady=1)

        tk.Label(form, text="主题", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=4, column=0, sticky="nw", pady=6)
        self.theme_var = tk.StringVar(value=self.profile["theme"])
        theme_box = tk.Frame(form, bg=BG_MAIN)
        theme_box.grid(row=4, column=1, columnspan=2, sticky="w", pady=6)
        for idx, (key, (_label, c1, c2)) in enumerate(THEMES.items()):
            swatch = tk.Frame(theme_box, bg=c1, width=26, height=26)
            swatch.pack(side=tk.LEFT, padx=4)
            swatch.pack_propagate(False)
            tk.Radiobutton(theme_box, text=_label, variable=self.theme_var,
                           value=key, font=(FONT, 9), bg=BG_MAIN, fg=FG_TEXT,
                           selectcolor=BG_CELL, activebackground=BG_MAIN,
                           relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=2)

        footer = tk.Frame(self.win, bg=BG_MAIN)
        footer.pack(fill=tk.X, padx=22, pady=16)
        _btn(footer, "保存", self.save, primary=True).pack(side=tk.RIGHT)
        _btn(footer, "取消", self.win.destroy).pack(side=tk.RIGHT, padx=8)

        self.win.bind("<Escape>", lambda e: self.win.destroy())
        _place(self.win, 580, 470)

    def save(self):
        nickname = self.nickname.get().strip()[:12] or self.profile["nickname"]
        motto = self.motto.get().strip()[:40] or "每天进步一点点"
        try:
            goal = max(0, int(float(self.goal.get())))
        except ValueError:
            goal = self.profile["goal"]
        self.portal.save_profile({
            "nickname": nickname, "motto": motto, "goal": goal,
            "avatar": self.avatar_var.get(), "theme": self.theme_var.get(),
        })
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.portal.show_page("profile")


# ===================== 入口 =====================
def _open_portal(ctx, class_name=None, sid=None, page="home"):
    existing = _PORTALS.get(class_name or "")
    try:
        if existing is not None and existing.win.winfo_exists():
            if sid and sid in existing.students:
                existing.sid = sid
                existing._refresh_student_box()
            existing.show_page(page)
            existing.win.deiconify()
            existing.win.lift()
            existing.win.focus_force()
            return existing
    except tk.TclError:
        pass
    portal = StudentPortalWindow(ctx, class_name=class_name, sid=sid, page=page)
    _PORTALS[class_name or ""] = portal
    portal.win.bind("<Destroy>",
                    lambda e: _PORTALS.pop(class_name or "", None), add="+")
    return portal


def _on_score_changed(_payload=None):
    for portal in list(_PORTALS.values()):
        try:
            if portal.win.winfo_exists():
                portal.show_page(portal._current_page)
        except tk.TclError:
            pass


def register(ctx):
    ctx.ui.add_main_menu("👤 学生视图（学生端）", lambda: _open_portal(ctx), order=40)
    ctx.ui.add_main_menu("🪪 学生个人主页",
                         lambda: _open_portal(ctx, page="profile"), order=41)
    ctx.ui.add_top_button("👤 学生视图", lambda: _open_portal(ctx), order=10)

    def open_profile_from_score(api):
        sid = next(iter(api.selected_ids), None)
        _open_portal(ctx, class_name=api.current_class, sid=sid, page="profile")

    ctx.ui.add_score_menu("🪪 学生个人主页（自定义）", open_profile_from_score, order=20)
    ctx.events.on("score_changed", _on_score_changed)
