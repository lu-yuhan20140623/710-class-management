"""学生积分：小组选择、小组管理与成员编辑。"""
import tkinter as tk
from tkinter import messagebox, ttk

import score_records as store
from score_data import CARD_SELECT, FONT
from ui import BG_CELL, BG_MAIN, BG_PANEL, FG_ACCENT, FG_DIM, FG_OK, FG_TEXT, dpi_scale


class ScoreGroupsMixin:
    def _pick_groups(self, title, prefer=None):
        """弹出小组多选框，返回选中的小组名列表（取消返回空列表）。"""
        groups = self._groups()
        if not groups:
            messagebox.showinfo("提示", "本班还没有小组，请先在「小组管理」里创建",
                                parent=self.win)
            return []
        names = list(groups)
        prefer = list(prefer or [])
        win = self._dialog(title, 360, 480)
        tk.Label(win, text="选择小组（可多选）", font=(FONT, 12, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))
        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=18)
        vars_ = {}
        for gname in names:
            group = groups.get(gname) or {}
            count = len(group.get("members", []))
            var = tk.BooleanVar(value=(gname in prefer) if prefer else True)
            vars_[gname] = var
            tk.Checkbutton(body, text=f"{gname}（{count}人）", variable=var,
                           font=(FONT, 10), bg=BG_PANEL, fg=FG_TEXT,
                           selectcolor=BG_CELL, activebackground=BG_PANEL,
                           activeforeground=FG_ACCENT, anchor="w",
                           padx=8, pady=4).pack(fill=tk.X, padx=6, pady=1)
        result = {}

        def set_all(value):
            for var in vars_.values():
                var.set(value)

        def ok():
            chosen = [g for g in names if vars_[g].get()]
            if not chosen:
                messagebox.showinfo("提示", "请至少勾选一个小组", parent=win)
                return
            result["groups"] = chosen
            win.destroy()

        tools = tk.Frame(win, bg=BG_MAIN)
        tools.pack(fill=tk.X, padx=18, pady=(6, 0))
        self._btn(tools, "全选", lambda: set_all(True)).pack(side=tk.LEFT)
        self._btn(tools, "全不选", lambda: set_all(False)).pack(side=tk.LEFT, padx=6)
        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=10)
        self._btn(row, "确定", ok, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        self.win.wait_window(win)
        return result.get("groups", [])

    def _open_groups(self):
        if not self._can_write():
            return
        groups = self.group_data.setdefault(self.current_class, {})
        stu = self.all_students.get(self.current_class, {})
        win = self._dialog("小组管理", 720, 480)
        tk.Label(win, text=f"小组管理 · {self.current_class}", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))

        body = tk.Frame(win, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=16)

        k = dpi_scale(self.win)
        style = ttk.Style()
        style.configure("Group.Treeview", background=BG_CELL, fieldbackground=BG_CELL,
                        foreground=FG_TEXT, rowheight=int(30 * k), borderwidth=0,
                        font=(FONT, 10))
        style.configure("Group.Treeview.Heading", background=BG_PANEL,
                        foreground=FG_ACCENT, relief=tk.FLAT,
                        font=(FONT, 10, "bold"))
        style.map("Group.Treeview", background=[("selected", CARD_SELECT)])

        tree = ttk.Treeview(body, columns=("name", "leader", "count", "own", "score"),
                            show="headings", style="Group.Treeview",
                            selectmode="browse")
        tree.heading("name", text="小组")
        tree.heading("leader", text="组长")
        tree.heading("count", text="人数")
        tree.heading("own", text="小组专项")
        tree.heading("score", text="积分")
        tree.column("name", width=int(220 * k), anchor="w")
        tree.column("leader", width=int(150 * k), anchor="center")
        tree.column("count", width=int(60 * k), anchor="center")
        tree.column("own", width=int(80 * k), anchor="center")
        tree.column("score", width=int(70 * k), anchor="center")
        sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def refresh(select=None):
            tree.delete(*tree.get_children())
            for gname, group in groups.items():
                members = [s for s in group.get("members", []) if s in stu]
                leader = group.get("leader", "")
                leader_text = f"{leader} {stu[leader]['name']}" if leader in stu else "未指定"
                tree.insert("", tk.END, iid=gname,
                            values=(gname, leader_text, len(members),
                                    store.group_own_total(group),
                                    store.group_total(group, stu)))
            if select and tree.exists(select):
                tree.selection_set(select)
                tree.see(select)

        def selected_group():
            sel = tree.selection()
            return sel[0] if sel else None

        def new_group():
            self._edit_group(None, groups, refresh)

        def edit_group(_event=None):
            gname = selected_group()
            if not gname:
                messagebox.showinfo("提示", "请先选择一个小小组", parent=win)
                return
            self._edit_group(gname, groups, refresh)

        def del_group():
            gname = selected_group()
            if not gname:
                messagebox.showinfo("提示", "请先选择一个小小组", parent=win)
                return
            if not messagebox.askyesno("确认删除", f"确定删除小组「{gname}」？\n组内学生不会被删除，该组积分记录会一并清除。",
                                       parent=win):
                return
            groups.pop(gname, None)
            self._save_all()
            self._render_cards()
            refresh()
            self._set_status(f"已删除小组 {gname}", FG_OK)

        btn_row = tk.Frame(win, bg=BG_MAIN)
        btn_row.pack(fill=tk.X, padx=16, pady=12)
        self._btn(btn_row, "新建小组", new_group, primary=True).pack(side=tk.LEFT)
        self._btn(btn_row, "编辑小组", edit_group).pack(side=tk.LEFT, padx=8)
        self._btn(btn_row, "删除小组", del_group).pack(side=tk.LEFT)
        self._btn(btn_row, "关闭", win.destroy).pack(side=tk.RIGHT)
        tree.bind("<Double-1>", edit_group)

        refresh()

    def _edit_group(self, name, groups, on_saved):
        """新建 / 编辑小组：填写组名、成员（多选）、组长。"""
        stu = self.all_students.get(self.current_class, {})
        editing = name is not None
        group = groups.get(name, {}) if editing else {}
        win = self._dialog("编辑小组" if editing else "新建小组", 520, 540)
        tk.Label(win, text=(f"编辑小组「{name}」" if editing else "新建小组"),
                 font=(FONT, 14, "bold"), bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack(fill=tk.X, padx=18)
        tk.Label(form, text="小组名称", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        name_entry = self._entry(form, 22)
        name_entry.grid(row=0, column=1, sticky="w", padx=8)
        if editing:
            name_entry.insert(0, name)

        tk.Label(win, text="成员（Ctrl / Shift 多选）", font=(FONT, 10),
                 bg=BG_MAIN, fg=FG_DIM).pack(anchor="w", padx=18, pady=(8, 4))
        list_frame = tk.Frame(win, bg=BG_MAIN)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=18)
        lb = tk.Listbox(list_frame, selectmode=tk.EXTENDED, font=(FONT, 10),
                        bg=BG_CELL, fg=FG_TEXT, selectbackground=CARD_SELECT,
                        selectforeground=FG_TEXT, activestyle="none",
                        relief=tk.FLAT, highlightthickness=0, exportselection=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        sids = sorted(stu)
        for sid in sids:
            lb.insert(tk.END, f"{sid}  {stu[sid]['name']}")
        current = set(group.get("members", []))
        for idx, sid in enumerate(sids):
            if sid in current:
                lb.selection_set(idx)

        leader_row = tk.Frame(win, bg=BG_MAIN)
        leader_row.pack(fill=tk.X, padx=18, pady=10)
        tk.Label(leader_row, text="组长", font=(FONT, 10), bg=BG_MAIN,
                 fg=FG_DIM).pack(side=tk.LEFT)
        no_leader = "（未指定）"
        leader_box = ttk.Combobox(leader_row, state="readonly", width=24,
                                  font=(FONT, 10), values=[no_leader])
        leader_box.set(no_leader)
        leader_box.pack(side=tk.LEFT, padx=8)
        leader_map = {}

        def selected_sids():
            return [sids[i] for i in lb.curselection()]

        def sync_leader(_event=None):
            prev = leader_box.get()
            values = [no_leader]
            leader_map.clear()
            for sid in selected_sids():
                label = f"{sid} {stu[sid]['name']}"
                values.append(label)
                leader_map[label] = sid
            leader_box.config(values=values)
            if prev != no_leader and prev in values:
                leader_box.set(prev)
            elif len(values) > 1:
                leader_box.set(values[1])
            else:
                leader_box.set(no_leader)

        lb.bind("<<ListboxSelect>>", sync_leader)
        sync_leader()
        if editing and group.get("leader") in current and group["leader"] in stu:
            lid = group["leader"]
            label = f"{lid} {stu[lid]['name']}"
            if label in leader_map:
                leader_box.set(label)

        def save():
            gname = name_entry.get().strip()
            if not gname:
                messagebox.showwarning("提示", "请输入小组名称", parent=win)
                return
            if gname in groups and gname != name:
                messagebox.showwarning("提示", "小组名称已存在", parent=win)
                return
            members = selected_sids()
            if not members:
                messagebox.showwarning("提示", "请至少选择一名成员", parent=win)
                return
            leader = leader_map.get(leader_box.get(), "")
            if leader not in members:
                leader = ""

            moved = []
            for other_name, other in groups.items():
                if other_name in (name, gname):
                    continue
                before = list(other.get("members", []))
                kept = [s for s in before if s not in members]
                if len(kept) != len(before):
                    moved += [s for s in before if s in members]
                    other["members"] = kept
                    if other.get("leader") not in kept:
                        other["leader"] = ""

            old = groups.get(name if editing else gname, {})
            if editing and gname != name:
                groups.pop(name, None)
            groups[gname] = {
                "leader": leader,
                "members": members,
                "total_score": int(old.get("total_score", 0)),
                "record": list(old.get("record", [])),
            }
            # 成员调整后按个人积分重新汇总小组积分
            store.sync_group_totals(self.all_students, self.group_data)

            self._save_all()
            self._render_cards()
            on_saved(gname)
            win.destroy()
            if moved:
                self._set_status(f"已保存小组 {gname}（{len(moved)} 人从原小组移入）", FG_OK)
            else:
                self._set_status(f"已保存小组 {gname}", FG_OK)

        btns = tk.Frame(win, bg=BG_MAIN)
        btns.pack(fill=tk.X, padx=18, pady=12)
        self._btn(btns, "保存", save, primary=True).pack(side=tk.LEFT)
        self._btn(btns, "取消", win.destroy).pack(side=tk.LEFT, padx=8)
