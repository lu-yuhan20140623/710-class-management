"""学生积分：窗口构建、卡片渲染、自适应布局、选择与随机点名。"""
import random
import tkinter as tk
from tkinter import messagebox, ttk

import score_records as store
from score_data import CARD_BG, CARD_FLASH, CARD_SELECT, CARD_W, FONT
from ui import (
    BG_CELL, BG_CELL_ALT, BG_IN_CLASS, BG_MAIN, BG_PANEL,
    FG_ACCENT, FG_DANGER, FG_DIM, FG_OK, FG_TEXT, FG_WARN,
    center_window, dpi_scale,
)


SORT_MODES = ("sid_asc", "sid_desc", "score_desc", "score_asc")
SORT_LABELS = {
    "sid_asc": "学号 ↑", "sid_desc": "学号 ↓",
    "score_desc": "积分 ↓", "score_asc": "积分 ↑",
}


class ScoreCardsMixin:
    # 主界面排序：默认学号升序，可切积分
    SORT_MODES = SORT_MODES

    def _on_sort_change(self, _event=None):
        label = self.sort_box.get()
        for mode, text in SORT_LABELS.items():
            if text == label:
                self.sort_mode = mode
                break
        self._render_cards()

    def _sid_key(self, sid):
        return store.sid_key(sid)

    def _sorted_sids(self, stu):
        if self.sort_mode.startswith("score"):
            rows = sorted(stu.items(),
                          key=lambda kv: (store.student_total(kv[1]), self._sid_key(kv[0])),
                          reverse=self.sort_mode.endswith("desc"))
            return [sid for sid, _ in rows]
        return sorted(stu, key=self._sid_key, reverse=self.sort_mode.endswith("desc"))

    def _build(self):
        # 顶部：标题 + 班级切换 + 人数
        top = tk.Frame(self.win, bg=BG_MAIN)
        top.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(top, text="学生积分", font=(FONT, 20, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        tk.Label(top, text="班级", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .pack(side=tk.LEFT, padx=(18, 6))
        self.class_box = ttk.Combobox(top, values=self.class_list, state="readonly",
                                      width=16, font=(FONT, 10))
        self.class_box.set(self.current_class)
        self.class_box.pack(side=tk.LEFT)
        self.class_box.bind("<<ComboboxSelected>>", self._on_class_change)

        self.count_label = tk.Label(top, text="", font=(FONT, 10),
                                    bg=BG_MAIN, fg=FG_DIM)
        self.count_label.pack(side=tk.LEFT, padx=10)

        tk.Label(top, text="排序", font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM)\
            .pack(side=tk.LEFT, padx=(0, 4))
        self.sort_box = ttk.Combobox(top, state="readonly", width=10,
                                     font=(FONT, 9),
                                     values=[SORT_LABELS[m] for m in SORT_MODES])
        self.sort_box.set(SORT_LABELS[self.sort_mode])
        self.sort_box.pack(side=tk.LEFT)
        self.sort_box.bind("<<ComboboxSelected>>", self._on_sort_change)

        self._new_class_btn = self._btn(top, "+ 新建班级", self._create_class)
        self._new_class_btn.pack(side=tk.RIGHT)
        self.view_student_btn = self._btn(top, "按学生", lambda: self._switch_view("student"))
        self.view_student_btn.pack(side=tk.RIGHT, padx=(4, 8))
        self.view_group_btn = self._btn(top, "按小组", lambda: self._switch_view("group"))
        self.view_group_btn.pack(side=tk.RIGHT)
        if self.readonly:
            self._new_class_btn.config(state=tk.DISABLED)

        # 中部：可滚动卡片区
        body = tk.Frame(self.win, bg=BG_PANEL,
                        highlightbackground=BG_CELL, highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        self.canvas = tk.Canvas(body, bg=BG_PANEL, highlightthickness=0, bd=0,
                                yscrollincrement=40)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner = tk.Frame(self.canvas, bg=BG_PANEL)
        self._inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        # 状态栏
        status_bar = tk.Frame(self.win, bg=BG_MAIN)
        status_bar.pack(fill=tk.X, padx=16)
        self.status_label = tk.Label(status_bar, text="就绪", font=(FONT, 9),
                                     bg=BG_MAIN, fg=FG_DIM, anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.sel_label = tk.Label(status_bar, text="", font=(FONT, 9),
                                  bg=BG_MAIN, fg=FG_ACCENT)
        self.sel_label.pack(side=tk.RIGHT)

        # 底部操作栏（pack 布局，窗口缩放不会丢按钮）
        bar = tk.Frame(self.win, bg=BG_MAIN)
        bar.pack(fill=tk.X, padx=16, pady=(6, 14))
        self._more_btn = self._btn(bar, "更多功能 ▾", self._open_more_menu)
        self._more_btn.pack(side=tk.LEFT)
        self._select_all_btn = self._btn(bar, "全选", self._select_all)
        self._invert_btn = self._btn(bar, "反选", self._invert_select)
        self.score_btn = self._btn(bar, "评价打分", self._open_score, primary=True)
        self.score_btn.pack(side=tk.RIGHT)
        self._btn(bar, "随机点名", self._random_call).pack(side=tk.RIGHT, padx=8)

    def _btn(self, parent, text, cmd, primary=False):
        bg = BG_IN_CLASS if primary else BG_CELL
        active = "#4b7b4b" if primary else BG_CELL_ALT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=FG_TEXT,
                         activebackground=active, activeforeground=FG_TEXT,
                         relief=tk.FLAT, font=(FONT, 10, "bold" if primary else "normal"),
                         padx=14, pady=6, cursor="hand2")

    def _card_text(self, sid, info, group=None):
        # 分成 4 行，避免「组名 + 积分」太长被卡片宽度裁掉
        if group:
            gname, is_leader, total = group
            return f"{sid}\n{info['name']}\n{'★' if is_leader else ''}{gname}\n{total}分"
        return f"{sid}\n{info['name']}\n未分组\n—"

    def _groups(self):
        return self.group_data.setdefault(self.current_class, {})

    def _group_map(self):
        """当前班级：学号 → (小组名, 是否组长, 个人积分)。"""
        stu = self.all_students.get(self.current_class, {})
        result = {}
        for gname, group in self._groups().items():
            for sid in group.get("members", []):
                if sid in stu and sid not in result:
                    result[sid] = (gname, group.get("leader") == sid,
                                   store.student_total(stu[sid]))
        return result

    def _selected_groups(self):
        """选中学生对应的小组（按小组顺序去重）。"""
        stu = self.all_students.get(self.current_class, {})
        chosen = {sid for sid in self.selected_ids if sid in stu}
        return [gname for gname, group in self._groups().items()
                if chosen & set(group.get("members", []))]

    def _iter_records(self):
        """遍历当前班级所有个人积分记录：(小组, 学号, 姓名, 记录)。"""
        return store.iter_point_records(self.all_students, self.group_data,
                                        self.current_class)

    def _switch_view(self, mode):
        if mode == self.view_mode:
            return
        self.view_mode = mode
        self.selected_ids.clear()
        self._sync_view_ui()
        self._render_cards()

    def _sync_view_ui(self):
        active, normal = BG_IN_CLASS, BG_CELL
        self.view_group_btn.config(
            bg=active if self.view_mode == "group" else normal)
        self.view_student_btn.config(
            bg=active if self.view_mode == "student" else normal)
        if self.view_mode == "group":
            self._select_all_btn.pack_forget()
            self._invert_btn.pack_forget()
            self.score_btn.config(state=tk.DISABLED if self.readonly else tk.NORMAL)
        else:
            self._select_all_btn.pack(side=tk.LEFT, padx=8)
            self._invert_btn.pack(side=tk.LEFT)
            self.score_btn.config(state=tk.DISABLED if self.readonly else tk.NORMAL)

    def _can_write(self) -> bool:
        if self.readonly:
            self._set_status("只读模式：无法修改积分数据", FG_WARN)
            return False
        return True

    def _render_cards(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self._cards.clear()
        self._group_cards.clear()
        self._anim_jobs.clear()

        if self.view_mode == "group":
            self._render_group_cards()
        else:
            group_map = self._group_map()
            stu = self.all_students.get(self.current_class, {})
            for sid in self._sorted_sids(stu):
                info = stu[sid]
                card = tk.Button(self.inner, text=self._card_text(sid, info, group_map.get(sid)),
                                 font=(FONT, 10), bg=CARD_BG, fg=FG_TEXT,
                                 activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                                 relief=tk.FLAT, cursor="hand2", justify=tk.CENTER,
                                 wraplength=120, padx=6, pady=6,
                                 command=lambda s=sid: self._toggle_select(s))
                card.bind("<MouseWheel>", self._on_wheel)
                self._cards[sid] = card

            # 选中集合里可能残留已删除的学生
            self.selected_ids &= set(self._cards)
            for sid in self.selected_ids:
                self._cards[sid].config(bg=CARD_SELECT)

        self._update_count()
        self._schedule_layout()
        self._refresh_charts()

    def _render_group_cards(self):
        groups = self._groups()
        if not groups:
            tk.Label(self.inner, text="暂未分组", font=(FONT, 12),
                     bg=BG_PANEL, fg=FG_DIM).grid(row=0, column=0,
                                                  padx=24, pady=24, sticky="w")
            return

        stu = self.all_students.get(self.current_class, {})
        for gname, group in groups.items():
            members = [s for s in group.get("members", []) if s in stu]
            leader = group.get("leader", "")
            leader_name = stu[leader]["name"] if leader in stu else "未指定"
            total = store.group_total(group, stu)
            text = f"{gname}\n{len(members)}人 · {total}分\n组长 {leader_name}"
            card = tk.Button(self.inner, text=text, font=(FONT, 11),
                             bg=CARD_BG, fg=FG_TEXT,
                             activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                             relief=tk.FLAT, cursor="hand2", justify=tk.CENTER,
                             wraplength=140, padx=8, pady=6,
                             command=lambda g=gname: self._open_group_detail(g))
            card.bind("<MouseWheel>", self._on_wheel)
            self._group_cards[gname] = card

    def _refresh_scores(self):
        """只刷新卡片上的积分文本，不重建控件（实时生效、不闪屏）。"""
        stu = self.all_students.get(self.current_class, {})
        if self.view_mode == "group":
            groups = self._groups()
            for gname, card in self._group_cards.items():
                if not card.winfo_exists():
                    continue
                group = groups.get(gname)
                if not group:
                    continue
                members = [s for s in group.get("members", []) if s in stu]
                leader = group.get("leader", "")
                leader_name = stu[leader]["name"] if leader in stu else "未指定"
                total = store.group_total(group, stu)
                card.config(text=f"{gname}\n{len(members)}人 · {total}分\n组长 {leader_name}")
        else:
            group_map = self._group_map()
            for sid, card in self._cards.items():
                info = stu.get(sid)
                if not info or not card.winfo_exists():
                    continue
                card.config(text=self._card_text(sid, info, group_map.get(sid)))
        self._update_count()
        self._refresh_charts()

    def _open_group_detail(self, gname):
        """查看小组：组员各自的积分与每次得失记录。"""
        group = self._groups().get(gname)
        if not group:
            return
        stu = self.all_students.get(self.current_class, {})
        members = sorted((s for s in group.get("members", []) if s in stu),
                         key=store.sid_key)
        leader = group.get("leader", "")
        leader_text = f"{leader} {stu[leader]['name']}" if leader in stu else "未指定"
        total = store.group_total(group, stu)
        own = store.group_own_total(group)

        win = self._dialog(f"小组详情 · {gname}", 680, 620)
        tk.Label(win, text=gname, font=(FONT, 16, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text=f"组长：{leader_text}    人数：{len(members)}    "
                           f"小组积分：{total} 分（组员 {total - own} + 小组专项 {own}）",
                 font=(FONT, 10), bg=BG_MAIN, fg=FG_TEXT).pack()
        tk.Label(win, text="组员积分记在个人名下；小组专项分只记在小组，统计时单列一类",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack(pady=(2, 0))

        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=10)
        txt = tk.Text(body, font=("Consolas", 10), bg=BG_PANEL, fg=FG_TEXT,
                      relief=tk.FLAT, padx=10, pady=8, wrap=tk.WORD)
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        if not members:
            txt.insert(tk.END, "（无成员）")
        own_records = store.group_own_records(group)
        if own_records:
            txt.insert(tk.END, f"【小组专项】{own} 分（不摊到个人）\n")
            for r in reversed(own_records):
                sign = "+" if store.record_delta(r) >= 0 else "-"
                txt.insert(tk.END,
                           f"    {r.get('time', '')}    {sign}{abs(int(r.get('score', 0)))} 分"
                           f"    {r.get('reason', '')}\n")
            txt.insert(tk.END, "\n")
        for sid in members:
            info = stu[sid]
            mark = "（组长）" if sid == leader else ""
            txt.insert(tk.END, f"{sid}  {info['name']}{mark}    "
                               f"{store.student_total(info)} 分\n")
            records = store.student_records(info)
            if not records:
                txt.insert(tk.END, "    （暂无记录）\n")
            for r in reversed(records):
                sign = "+" if store.record_delta(r) >= 0 else "-"
                txt.insert(tk.END,
                           f"    {r.get('time', '')}    {sign}{abs(int(r.get('score', 0)))} 分"
                           f"    {r.get('reason', '')}\n")
            txt.insert(tk.END, "\n")
        txt.config(state=tk.DISABLED)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(fill=tk.X, padx=18, pady=12)
        if not self.readonly:
            self._btn(row, "给小组记分",
                      lambda: (win.destroy(),
                               self._open_score(target_groups=[gname], groups_fixed=True)),
                      primary=True).pack(side=tk.LEFT)
            self._btn(row, "为本组学生打分",
                      lambda: (win.destroy(), self._open_score(target_students=members))
                      ).pack(side=tk.LEFT, padx=8)
        self._btn(row, "关闭", win.destroy).pack(side=tk.RIGHT)

    def _schedule_layout(self):
        if self._layout_job:
            try:
                self.win.after_cancel(self._layout_job)
            except Exception:
                pass
        self._layout_job = self.win.after(60, self._apply_layout)

    def _ideal_card_width(self) -> int:
        """按最长文本估算卡片宽度：组名/姓名越长卡片越宽，避免被裁切。"""
        import tkinter.font as tkfont
        try:
            if self.view_mode == "group":
                font = tkfont.Font(font=(FONT, 11))
                texts = list(self._groups()) or ["暂未分组"]
            else:
                font = tkfont.Font(font=(FONT, 10))
                stu = self.all_students.get(self.current_class, {})
                gmap = self._group_map()
                texts = [info.get("name", "") for info in stu.values()]
                texts += [item[0] for item in gmap.values()]
                texts = texts or ["未分组"]
            widest = max(font.measure(t) for t in texts)
            return max(110, min(260, widest + 46))
        except Exception:
            return int(CARD_W)

    def _apply_layout(self):
        self._layout_job = None
        if not self.win.winfo_exists():
            return
        avail = max(120, self.canvas.winfo_width() - 16)
        ideal = max(1, int(self._ideal_card_width()))
        cols = max(1, avail // ideal)
        cell_w = max(96, avail // cols - 14)
        cards = (self._group_cards if self.view_mode == "group" else self._cards)
        for idx, card in enumerate(cards.values()):
            if not card.winfo_exists():
                continue
            # 卡片跟着列宽走，组名过长时自动换行而不是被截断
            card.configure(wraplength=max(70, cell_w - 14))
            card.grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="nsew")
        # 列数变化时把旧的列权重清掉，否则窗口放大后再缩小会残留空白列
        previous = getattr(self, "_grid_cols", 0)
        for c in range(max(cols, previous)):
            if c < cols:
                self.inner.grid_columnconfigure(c, weight=1, minsize=0, uniform="card")
            else:
                self.inner.grid_columnconfigure(c, weight=0, minsize=0, uniform="")
        self._grid_cols = cols
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._inner_window, width=event.width)
        self._schedule_layout()

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _update_count(self):
        stu = self.all_students.get(self.current_class, {})
        groups = self._groups()
        if self.view_mode == "group":
            self.count_label.config(text=f"共 {len(groups)} 组 · {len(stu)} 人")
            self.sel_label.config(text="")
        else:
            self.count_label.config(text=f"共 {len(stu)} 人 · {len(groups)} 组")
            self.sel_label.config(text=f"已选 {len(self.selected_ids)} 人" if self.selected_ids else "")

    def _set_status(self, text, color=FG_DIM):
        self.status_label.config(text=text, fg=color)

    def _center_on(self, sid):
        card = self._cards.get(sid)
        if not card or not card.winfo_exists():
            return
        self.inner.update_idletasks()
        total = max(1, self.inner.winfo_height())
        # 顶部偏移按 DPI 放大，否则高 DPI 下会滚不到位
        offset = int(60 * dpi_scale(self.win))
        frac = max(0.0, min(1.0, (card.winfo_y() - offset) / total))
        self.canvas.yview_moveto(frac)

    def _toggle_select(self, sid):
        card = self._cards.get(sid)
        if card is None:
            return
        if sid in self.selected_ids:
            self.selected_ids.discard(sid)
            self._animate(card, CARD_BG)
        else:
            self.selected_ids.add(sid)
            self._animate(card, CARD_SELECT)
        self._update_count()

    def _animate(self, card, end_color):
        """颜色过渡动画；控件销毁后回调自动失效，不再抛异常。"""
        if not card.winfo_exists():
            return
        job = self._anim_jobs.pop(card, None)
        if job:
            try:
                self.win.after_cancel(job)
            except Exception:
                pass
        start = card.cget("bg")
        if start == end_color:
            return
        r1, g1, b1 = (v // 256 for v in self.win.winfo_rgb(start))
        r2, g2, b2 = (v // 256 for v in self.win.winfo_rgb(end_color))
        steps = 8

        def step(i):
            self._anim_jobs.pop(card, None)
            if not card.winfo_exists():
                return
            if i >= steps:
                card.config(bg=end_color)
                return
            color = "#%02x%02x%02x" % (
                int(r1 + (r2 - r1) * i / steps),
                int(g1 + (g2 - g1) * i / steps),
                int(b1 + (b2 - b1) * i / steps),
            )
            card.config(bg=color)
            self._anim_jobs[card] = self.win.after(12, lambda: step(i + 1))

        step(1)

    def _select_all(self):
        self.selected_ids = set(self._cards)
        for card in self._cards.values():
            self._animate(card, CARD_SELECT)
        self._update_count()

    def _invert_select(self):
        self.selected_ids = set(self._cards) - self.selected_ids
        for sid, card in self._cards.items():
            self._animate(card, CARD_SELECT if sid in self.selected_ids else CARD_BG)
        self._update_count()

    def _random_call(self):
        """随机点名：先快速滚动高亮，再定格并弹出带彩带的结果窗口。"""
        if self.view_mode == "group":
            self._switch_view("student")
        if not self._cards:
            self._set_status("班级暂无学生", FG_WARN)
            return

        sids = list(self._cards)
        stu = self.all_students[self.current_class]
        self._call_seq = getattr(self, "_call_seq", 0) + 1
        seq = self._call_seq
        steps = 20

        def paint():
            for s, card in self._cards.items():
                if card.winfo_exists():
                    card.config(bg=CARD_SELECT if s in self.selected_ids else CARD_BG)

        def roll(step):
            if seq != self._call_seq or not self.win.winfo_exists():
                return
            s = random.choice(sids)
            paint()
            card = self._cards.get(s)
            if card and card.winfo_exists():
                card.config(bg=CARD_FLASH)
            self._set_status(f"🎲 抽取中… {stu[s]['name']}", FG_ACCENT)
            if step >= steps:
                self.win.after(180, finish)
            else:
                # 越到后面滚动越慢，制造"减速"效果
                self.win.after(40 + step * 7, lambda: roll(step + 1))

        def finish():
            if seq != self._call_seq or not self.win.winfo_exists():
                return
            sid = random.choice(sids)
            info = stu[sid]
            self.selected_ids = {sid}
            paint()
            self._update_count()
            self._center_on(sid)
            self._flash_card(sid, 6)
            group = self._group_map().get(sid)
            extra = f"（{group[0]} {group[2]} 分）" if group else "（未分组）"
            self._set_status(f"🎲 随机点名：{sid} {info['name']}{extra}", FG_ACCENT)
            self._show_call_result(sid, info, group)

        roll(0)

    def _flash_card(self, sid, times=6):
        """定格后让卡片金色闪烁几次。"""
        card = self._cards.get(sid)
        if card is None:
            return

        def step(n):
            if not card.winfo_exists():
                return
            if n <= 0:
                self._animate(card, CARD_SELECT)
                return
            card.config(bg=CARD_FLASH if n % 2 else CARD_BG)
            self.win.after(140, lambda: step(n - 1))

        step(times)

    def _show_call_result(self, sid, info, group):
        """随机点名结果窗口：大字名字 + 彩带下落 + 颜色/字号脉冲。"""
        k = dpi_scale(self.win)
        w, h = int(440 * k), int(280 * k)
        win = tk.Toplevel(self.win)
        win.title("随机点名")
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.attributes("-topmost", True)
        cv = tk.Canvas(win, width=w, height=h, bg=BG_MAIN, highlightthickness=0)
        cv.pack(fill=tk.BOTH, expand=True)

        colors = ["#ffd166", "#06d6a0", "#ef476f", "#4cc9f0", "#f8961e"]
        particles = []
        for _ in range(36):
            x = random.randint(0, w)
            y = random.randint(-h, 0)
            size = random.randint(3, 7)
            item = cv.create_oval(x, y, x + size, y + size,
                                  fill=random.choice(colors), outline="")
            particles.append([item, random.uniform(2.0, 5.0) * k,
                              random.uniform(-0.6, 0.6)])

        name_id = cv.create_text(w // 2, int(h * 0.42), text=info["name"],
                                 font=(FONT, int(30 * k), "bold"), fill=FG_WARN)
        sub = sid
        if group:
            sub += f" · {group[0]}" + (" · 组长" if group[1] else "")
        cv.create_text(w // 2, int(h * 0.64), text=sub,
                       font=(FONT, int(11 * k)), fill=FG_TEXT)
        cv.create_text(w // 2, h - int(14 * k), text="点击关闭",
                       font=(FONT, int(8 * k)), fill=FG_DIM)

        state = {"seq": getattr(self, "_call_seq", 0), "frame": 0}

        def tick():
            if not win.winfo_exists() or state["seq"] != getattr(self, "_call_seq", 0):
                return
            for p in particles:
                cv.move(p[0], p[2], p[1])
                box = cv.coords(p[0])
                if box and box[1] > h:
                    cv.move(p[0], 0, -h - 20)
            n = state["frame"]
            if n < 90:
                size = 30 + int(2 * abs((n % 20) - 10))
                cv.itemconfig(name_id, font=(FONT, int(size * k), "bold"),
                              fill=colors[(n // 5) % len(colors)])
                state["frame"] = n + 1
                win.after(45, tick)
            else:
                cv.itemconfig(name_id, font=(FONT, int(32 * k), "bold"), fill=FG_WARN)

        def close(_event=None):
            if win.winfo_exists():
                win.destroy()

        win.bind("<Button-1>", close)
        cv.bind("<Button-1>", close)
        win.protocol("WM_DELETE_WINDOW", close)
        win.after(4500, close)
        center_window(win, self.win, w, h, auto=False)
        tick()

    def _selected_or_warn(self) -> bool:
        if self.selected_ids:
            return True
        messagebox.showwarning("提示", "请先选择学生", parent=self.win)
        return False
