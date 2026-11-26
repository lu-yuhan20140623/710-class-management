"""学生积分：评价打分、撤回记录、手动改分与本周归档。"""
import json
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import plugin_api as plug
import score_records as store
from score_data import CHECK_BG, FONT, add_custom_reason, custom_reasons, reason_categories
from ui import BG_CELL, BG_MAIN, BG_PANEL, FG_ACCENT, FG_DANGER, FG_DIM, FG_OK, FG_TEXT


class ScoreScoringMixin:
    def _open_score(self, target_groups=None, target_students=None, groups_fixed=False):
        if not self._can_write():
            return
        if self._score_win and self._score_win.winfo_exists():
            self._score_win.lift()
            return
        stu = self.all_students.get(self.current_class, {})
        groups = self._groups()

        sids = list(target_students or [])
        preset_groups = list(target_groups or [])
        if not sids:
            if target_groups:
                for gname in target_groups:
                    group = groups.get(gname)
                    if group:
                        sids += [s for s in group.get("members", []) if s in stu]
            elif self.view_mode == "group":
                gnames = self._pick_groups("评价打分")
                if not gnames:
                    return
                preset_groups = gnames
                groups_fixed = True
                for gname in gnames:
                    group = groups.get(gname) or {}
                    sids += [s for s in group.get("members", []) if s in stu]
            else:
                if not self._selected_or_warn():
                    return
                sids = [s for s in sorted(self.selected_ids) if s in stu]
        sids = list(dict.fromkeys(sids))
        is_group_view = bool(preset_groups)
        if not sids and not groups:
            messagebox.showinfo("提示", "所选范围内没有学生", parent=self.win)
            return

        gmap = store.student_group_map(groups, stu)
        win = self._dialog("评价打分", 560, 620)
        self._score_win = win
        tk.Label(win, text="评价打分", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        scope = tk.StringVar(value="group" if is_group_view else "person")
        hint = tk.Label(win, text="", font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM)
        hint.pack()

        # 底部区域先占位：窗口高度不够时由上方勾选列表收缩，按钮不会被挤出窗口
        bottom = tk.Frame(win, bg=BG_MAIN)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        vars_ = {}
        group_vars = {}
        # 已经在“选择打分组”里选过就直接沿用，不再让用户重复勾选
        fixed = bool(groups_fixed and preset_groups)

        if fixed:
            hint.config(text="本次打分：" + "、".join(preset_groups) +
                             f"（已选 {len(preset_groups)} 个小组）")
            for gname in preset_groups:
                group_vars[gname] = tk.BooleanVar(value=True)
        else:
            scope_row = tk.Frame(win, bg=BG_MAIN)
            scope_row.pack(pady=(6, 2))
            tk.Label(scope_row, text="记录到", font=(FONT, 10), bg=BG_MAIN,
                     fg=FG_DIM).pack(side=tk.LEFT, padx=(0, 8))
            for value, label in (("person", "个人"), ("group", "小组（小组专项分）")):
                tk.Radiobutton(scope_row, text=label, value=value, variable=scope,
                               font=(FONT, 10), bg=BG_MAIN, fg=FG_TEXT,
                               selectcolor=BG_CELL, activebackground=BG_MAIN,
                               activeforeground=FG_ACCENT, bd=0,
                               highlightthickness=0,
                               command=lambda: rebuild()).pack(side=tk.LEFT, padx=4)

            pick_body = tk.Frame(win, bg=BG_PANEL,
                                 highlightbackground=BG_CELL, highlightthickness=1)
            pick_body.pack(fill=tk.BOTH, expand=True, padx=22, pady=(8, 6))
            cv = tk.Canvas(pick_body, bg=BG_PANEL, height=120,
                           highlightthickness=0, bd=0)
            sb = ttk.Scrollbar(pick_body, orient="vertical", command=cv.yview)
            cv.configure(yscrollcommand=sb.set)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            pick_inner = tk.Frame(cv, bg=BG_PANEL)
            cv.create_window((0, 0), window=pick_inner, anchor="nw")
            pick_inner.bind("<Configure>",
                            lambda e: cv.configure(scrollregion=cv.bbox("all")))
            cv.bind("<MouseWheel>",
                    lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))

        def add_check(container, text, var, checked=True):
            var.set(checked)
            cb = tk.Checkbutton(container, text="✔ " + text, variable=var,
                                font=(FONT, 10), bg=BG_PANEL, fg="#ffffff",
                                activebackground=CHECK_BG, activeforeground="#ffffff",
                                selectcolor=CHECK_BG, relief="flat", bd=0,
                                highlightthickness=0, padx=10, pady=4,
                                anchor="w", cursor="hand2", indicatoron=False)
            cb.pack(fill=tk.X, padx=6, pady=1)

            def sync(w=cb, v=var, base=text):
                on = v.get()
                w.config(text=("✔ " if on else "   ") + base,
                         fg="#ffffff" if on else FG_DIM)
            var.trace_add("write", lambda *a, f=sync: f())

        def rebuild():
            if fixed:
                return
            for child in pick_inner.winfo_children():
                child.destroy()
            vars_.clear()
            group_vars.clear()
            if scope.get() == "group":
                hint.config(text="小组专项分只记在小组名下，不计入任何学生个人积分")
                if not groups:
                    tk.Label(pick_inner, text="本班还没有小组，请先创建小组",
                             font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM).pack(
                        pady=12, padx=12, anchor="w")
                    return
                for gname, group in groups.items():
                    members = [s for s in group.get("members", []) if s in stu]
                    var = tk.BooleanVar()
                    group_vars[gname] = var
                    add_check(pick_inner, f"{gname}（{len(members)}人）", var,
                              checked=(not preset_groups) or gname in preset_groups)
            else:
                hint.config(text="积分记在每位学生名下，可只勾选本次涉及的学生")
                for sid in sids:
                    info = stu[sid]
                    var = tk.BooleanVar()
                    vars_[sid] = var
                    gname = gmap.get(sid, "未分组")
                    add_check(pick_inner, f"{sid}  {info['name']}（{gname}）", var)
            pick_inner.update_idletasks()
            cv.configure(scrollregion=cv.bbox("all"))

        if not fixed:
            rebuild()

        form = tk.Frame(bottom, bg=BG_MAIN)
        form.pack(padx=24, pady=4, fill=tk.X)
        form.columnconfigure(1, weight=1)

        # 分类
        tk.Label(form, text="分类", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=5)
        cat_box = ttk.Combobox(form, values=list(reason_categories), state="readonly",
                               width=22, font=(FONT, 10))
        cat_box.current(0)
        cat_box.grid(row=0, column=1, sticky="w", pady=5)

        # 具体理由：可直接输入自定义理由
        tk.Label(form, text="理由", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=5)
        reason_box = ttk.Combobox(
            form, values=reason_categories["常用"] + custom_reasons(),
            width=26, font=(FONT, 10))
        reason_box.current(0)
        reason_box.grid(row=1, column=1, sticky="w", pady=5)

        def change_cat(_event=None):
            reason_box["values"] = reason_categories[cat_box.get()] + custom_reasons()
            reason_box.current(0)
        cat_box.bind("<<ComboboxSelected>>", change_cat)

        # 分值：正数加分、负数扣分
        tk.Label(form, text="分值", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=2, column=0, sticky="w", pady=5)
        score_entry = self._entry(form, width=10)
        score_entry.grid(row=2, column=1, sticky="w", pady=5)

        tip_label = tk.Label(bottom, text="", font=(FONT, 8), bg=BG_MAIN,
                             fg=FG_DIM, wraplength=480, justify=tk.CENTER)
        tip_label.pack()

        def refresh_tip():
            extra = plug.score_hint()
            tip_label.config(text="分值填正数加分、负数扣分（如 3 或 -2）；"
                                  "理由可直接输入新内容，会保存为预设"
                                  + (f"；{extra}" if extra else ""))
        refresh_tip()
        score_entry.focus_set()

        err = tk.Label(bottom, text="", font=(FONT, 9), bg=BG_MAIN, fg=FG_DANGER)
        err.pack()

        def submit():
            group_mode = fixed or scope.get() == "group"
            chosen = [g for g in group_vars if group_vars[g].get()] if group_mode \
                else [sid for sid in sids if vars_[sid].get()]
            reason = reason_box.get().strip()
            score_str = score_entry.get().strip()
            if not chosen:
                err.config(text="请至少勾选一个小组" if group_mode else "请至少勾选一名学生")
                return
            if not reason:
                err.config(text="请填写理由")
                return
            if not score_str:
                err.config(text="分值不能为空")
                return
            delta, parse_error = plug.parse_score(score_str)
            if parse_error:
                err.config(text=parse_error)
                return
            if delta == 0:
                err.config(text="分值不能为 0（正数加分，负数扣分）")
                return
            if abs(delta) > 10 and not messagebox.askyesno(
                    "提醒", f"分值 {store.fmt_delta(delta)} 超过 10，确定提交？",
                    parent=win):
                return

            mode = "加分" if delta > 0 else "扣分"
            score = abs(delta)
            # 自定义理由：保存下来，下次可直接选用
            if reason not in reason_categories.get(cat_box.get(), []) \
                    and reason not in custom_reasons():
                add_custom_reason(reason)

            if group_mode:
                count = store.add_group_point_records(
                    self.group_data, self.all_students, self.current_class,
                    chosen, reason, delta)
            else:
                count = store.add_point_records(self.all_students, self.group_data,
                                                self.current_class, chosen, reason, delta)
            self._save_all()
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            log_lines = []
            if group_mode:
                for gname in chosen:
                    group = groups.get(gname, {})
                    log_lines.append(
                        f"{now} | {self.current_class} | 小组 {gname} | "
                        f"{mode} {score} 分 | {reason} | 余额 "
                        f"{store.group_own_total(group)}（小组专项）")
            else:
                for sid in chosen:
                    info = stu.get(sid, {})
                    log_lines.append(
                        f"{now} | {self.current_class} | {sid} {info.get('name', '')} | "
                        f"{mode} {score} 分 | {reason} | 余额 {store.student_total(info)}")
            self._log_ops(log_lines)
            win.destroy()
            self._score_win = None
            # 只刷新数字，不重建卡片：积分即时变化，不会闪屏
            self._refresh_scores()
            target = "个小组" if group_mode else "名学生"
            self._set_status(f"已为 {count} {target}{mode} {score} 分 · {reason}", FG_OK)

        row = tk.Frame(bottom, bg=BG_MAIN)
        row.pack(pady=(6, 14))
        self._btn(row, "提交", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: submit())
        # 按实际内容撑高：高 DPI 下字体变大也不会把底部按钮挤出窗口
        win.update_idletasks()
        cur_h = win.winfo_height()
        win.geometry(f"{max(560, win.winfo_reqwidth())}x"
                     f"{max(cur_h, win.winfo_reqheight())}")

    def _revoke_record(self):
        if not self._can_write():
            return
        stu = self.all_students.get(self.current_class, {})
        gmap = store.student_group_map(self._groups(), stu)

        win = self._dialog("撤回积分记录", 760, 560)
        tk.Label(win, text="撤回积分记录", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text="个人与小组积分均可撤回；撤回后对应积分立即回退",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack()

        body = tk.Frame(win, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)
        tree = ttk.Treeview(body, columns=("time", "student", "group", "delta", "reason"),
                            show="headings", selectmode="browse")
        for col, text, width in (("time", "时间", 150), ("student", "学生", 130),
                                 ("group", "小组", 110), ("delta", "分值", 70),
                                 ("reason", "理由", 220)):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w" if col in ("student", "group", "reason")
                        else "center")
        sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def fill():
            tree.delete(*tree.get_children())
            rows = []
            for sid, info in stu.items():
                for idx, rec in enumerate(store.student_records(info)):
                    if isinstance(rec, dict):
                        rows.append((sid, info.get("name", ""), idx, rec))
            for gname, group in self._groups().items():
                for idx, rec in enumerate(group.get("group_records", [])):
                    if isinstance(rec, dict):
                        rows.append((f"GROUP|{gname}", gname, idx, rec))
            rows.sort(key=lambda item: item[3].get("time", ""), reverse=True)
            for sid, name, idx, rec in rows:
                delta = store.record_delta(rec)
                is_group = sid.startswith("GROUP|")
                tree.insert("", tk.END, iid=f"{sid}|{idx}", values=(
                    rec.get("time", ""), name if is_group else f"{sid} {name}",
                    sid.split("|", 1)[1] if is_group else gmap.get(sid, "未分组"),
                    store.fmt_delta(delta), rec.get("reason", "")))
            return bool(rows)

        def revoke():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择一条记录", parent=win)
                return
            sid, idx_text = sel[0].rsplit("|", 1)
            try:
                idx = int(idx_text)
            except ValueError:
                return
            is_group = sid.startswith("GROUP|")
            if is_group:
                gname = sid.split("|", 1)[1]
                group = self._groups().get(gname)
                if not group:
                    return
                records = group.get("group_records", [])
                try:
                    rec = records[idx]
                except IndexError:
                    return
                label = f"小组 {gname}"
            else:
                info = stu.get(sid)
                if not info:
                    return
                records = store.student_records(info)
                try:
                    rec = records[idx]
                except IndexError:
                    return
                label = f"{sid} {info.get('name', '')}"
            if not messagebox.askyesno(
                    "确认撤回",
                    f"撤回 {label} 的这条记录？\n\n"
                    f"{rec.get('time', '')}  {rec.get('reason', '')}  "
                    f"{store.fmt_delta(store.record_delta(rec))} 分",
                    parent=win):
                return
            records.pop(idx)
            if not is_group:
                info["total_score"] = store.student_total(info)
            store.sync_group_totals(self.all_students, self.group_data)
            self._save_all()
            self._log_ops([f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {self.current_class} | "
                           f"{label} | 撤回 {rec.get('reason', '')} | "
                           f"原记录 {rec.get('time', '')}"])
            self._refresh_scores()
            if not fill():
                win.destroy()
            self._set_status(f"已撤回 {label} 的积分记录", FG_OK)

        if not fill():
            win.destroy()
            messagebox.showinfo("提示", "当前班级暂无积分记录", parent=self.win)
            return

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(fill=tk.X, padx=16, pady=(0, 12))
        self._btn(row, "撤回选中记录", revoke, primary=True).pack(side=tk.LEFT)
        self._btn(row, "关闭", win.destroy).pack(side=tk.RIGHT)

    def _manual_score(self):
        if not self._can_write():
            return
        stu = self.all_students.get(self.current_class, {})
        sids = [s for s in sorted(self.selected_ids) if s in stu]
        if not sids and self.view_mode == "group":
            gnames = self._pick_groups("手动修改积分")
            if not gnames:
                return
            for gname in gnames:
                sids += [s for s in self._groups().get(gname, {}).get("members", [])
                         if s in stu]
            sids = list(dict.fromkeys(sids))
        if not sids:
            messagebox.showinfo("提示", "请先选择学生（或切换到「按学生」视图）",
                                parent=self.win)
            return
        names = "、".join(f"{s} {stu[s]['name']}" for s in sids)
        num = simpledialog.askstring(
            "手动修改积分",
            f"把选中的 {len(sids)} 名学生积分设为：\n{names}",
            parent=self.win,
        )
        if num is None:
            return
        new_score, parse_error = plug.parse_score(num.strip())
        if parse_error:
            messagebox.showerror("错误", parse_error, parent=self.win)
            return
        if not messagebox.askyesno(
                "确认修改",
                f"确定把这些学生的积分直接设为 {new_score} 分？\n\n"
                f"{names}\n\n"
                "（差额会写入一条「手动调整」记录）",
                parent=self.win):
            return
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        week = time.strftime("%G-W%V")
        log_lines = []
        for sid in sids:
            info = stu[sid]
            old = store.student_total(info)
            delta = new_score - old
            if delta == 0:
                continue
            info.setdefault("records", []).append({
                "operate": "加分" if delta > 0 else "扣分",
                "score": abs(delta), "reason": "手动调整",
                "time": now, "week": week,
            })
            info["total_score"] = store.student_total(info)
            log_lines.append(f"{now} | {self.current_class} | {sid} {info['name']} | "
                             f"手动改分 {old} → {new_score}")
        store.sync_group_totals(self.all_students, self.group_data)
        self._save_all()
        self._log_ops(log_lines)
        self._refresh_scores()
        self._set_status(f"已将 {len(sids)} 名学生积分设为 {new_score}", FG_OK)

    def _archive_week(self):
        if not self._can_write():
            return
        wk = time.strftime("%G-W%V")
        store.sync_group_totals(self.all_students, self.group_data)
        # 用 JSON 序列化深拷贝，避免 deepcopy 在含循环引用时的性能/内存问题
        snapshot = json.loads(json.dumps(self._groups(), ensure_ascii=False))
        self.week_archive[wk].append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "class": self.current_class,
            "data": snapshot,
        })
        self._save_all()
        self._set_status(f"{self.current_class} · {wk} 小组数据已归档", FG_OK)
