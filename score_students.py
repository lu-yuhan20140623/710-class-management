"""学生积分：班级切换、数据持久化、通用弹窗工具与学生名单管理。"""
import tkinter as tk
from tkinter import messagebox, simpledialog

from score_data import (
    CLASS_FILE, FONT, GROUP_FILE, LOG_DIR, OP_LOG, STUDENT_FILE,
    WEEKLY_ARCHIVE, _save_json,
)
from ui import BG_CELL, BG_MAIN, FG_ACCENT, FG_DANGER, FG_DIM, FG_OK, FG_TEXT, FG_WARN, center_window
from touch_keyboard import bind_touch_keyboard


class ScoreStudentsMixin:
    def _on_class_change(self, _event=None):
        name = self.class_box.get()
        if not name:
            return
        self.current_class = name
        self.selected_ids.clear()
        self._render_cards()
        self._set_status(f"已切换到 {name}", FG_ACCENT)

    def _create_class(self):
        if not self._can_write():
            return
        name = simpledialog.askstring("新建班级", "请输入班级名称：", parent=self.win)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.class_list:
            self._set_status("班级已存在", FG_DANGER)
            return
        self.class_list.append(name)
        self.all_students[name] = {}
        self.group_data[name] = {}
        self._save_all()
        self.class_box.config(values=self.class_list)
        self.class_box.set(name)
        self.current_class = name
        self.selected_ids.clear()
        self._render_cards()
        self._set_status(f"已创建班级 {name}", FG_OK)

    def _save_all(self):
        _save_json(CLASS_FILE, self.class_list)
        _save_json(STUDENT_FILE, self.all_students)
        _save_json(GROUP_FILE, self.group_data)
        _save_json(WEEKLY_ARCHIVE, dict(self.week_archive))
        try:
            import plugin_api
            plugin_api.emit("score_changed", {"cls": self.current_class})
        except Exception:
            pass

    def _log_ops(self, lines):
        """把加减分操作追加到 logs/score_operations.log（失败不影响业务）。"""
        if not lines:
            return
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(OP_LOG, "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
        except OSError:
            pass

    def _dialog(self, title, w, h):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.grab_set()
        win.resizable(False, False)
        # 内容由调用方添加，等布局完成后再按实际需要居中
        win.after_idle(
            lambda: center_window(win, self.win, w, h) if win.winfo_exists() else None)
        return win

    def _entry(self, parent, width=18):
        return bind_touch_keyboard(tk.Entry(parent, width=width, font=(FONT, 11), bg=BG_CELL,
                        fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT))

    def _hint(self, parent, text):
        return tk.Label(parent, text=text, font=(FONT, 9), bg=BG_MAIN,
                        fg=FG_DIM, justify=tk.LEFT, wraplength=380)

    def _add_student(self):
        if not self._can_write():
            return
        win = self._dialog("新增学生", 360, 240)
        tk.Label(win, text="新增学生", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(16, 10))

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack()
        tk.Label(form, text="学号", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        e_id = self._entry(form)
        e_id.grid(row=0, column=1, pady=6)
        tk.Label(form, text="姓名", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=6)
        e_name = self._entry(form)
        e_name.grid(row=1, column=1, pady=6)
        e_id.focus_set()

        def submit():
            sid, name = e_id.get().strip(), e_name.get().strip()
            if not sid or not name:
                messagebox.showwarning("提示", "学号姓名不能为空", parent=win)
                return
            stu = self.all_students.setdefault(self.current_class, {})
            if sid in stu:
                messagebox.showerror("错误", "学号已存在", parent=win)
                return
            stu[sid] = {"stu_id": sid, "name": name}
            self._save_all()
            win.destroy()
            self._render_cards()
            self._center_on(sid)
            self._set_status(f"已添加 {sid} {name}", FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=16)
        self._btn(row, "确定", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: submit())

    def _batch_import(self):
        if not self._can_write():
            return
        win = self._dialog("批量导入学生", 460, 430)
        tk.Label(win, text="批量导入", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        self._hint(win, "每行一条：学号,姓名（支持中文逗号；重复学号自动跳过）\n"
                        "例如：01,张三   /   02,李四")\
            .pack(fill=tk.X, padx=18)

        txt = tk.Text(win, height=12, font=(FONT, 10), bg=BG_CELL, fg=FG_TEXT,
                      insertbackground=FG_TEXT, relief=tk.FLAT, padx=8, pady=6)
        txt.pack(fill=tk.BOTH, expand=True, padx=18, pady=8)
        txt.focus_set()

        def submit():
            stu = self.all_students.setdefault(self.current_class, {})
            count = skipped = 0
            for line in txt.get("1.0", tk.END).splitlines():
                line = line.strip().replace("，", ",")
                if not line:
                    continue
                parts = line.split(",", 1)
                if len(parts) != 2:
                    skipped += 1
                    continue
                sid, name = parts[0].strip(), parts[1].strip()
                if not sid or not name or sid in stu:
                    skipped += 1
                    continue
                stu[sid] = {"stu_id": sid, "name": name}
                count += 1
            self._save_all()
            win.destroy()
            self._render_cards()
            msg = f"成功导入 {count} 名学生"
            if skipped:
                msg += f"，跳过 {skipped} 条"
            self._set_status(msg, FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=(0, 14))
        self._btn(row, "导入", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)

    def _delete_students(self):
        if not self._can_write():
            return
        if not self._selected_or_warn():
            return
        stu = self.all_students.get(self.current_class, {})
        names = [f"{sid} {stu[sid]['name']}" for sid in sorted(self.selected_ids) if sid in stu]
        if not messagebox.askyesno("确认删除", "确定删除以下学生？\n\n" + "\n".join(names),
                                   parent=self.win):
            return
        for sid in list(self.selected_ids):
            stu.pop(sid, None)
        # 同步清理小组中的成员与组长
        removed = set(self.selected_ids)
        for group in self.group_data.get(self.current_class, {}).values():
            group["members"] = [s for s in group.get("members", []) if s not in removed]
            if group.get("leader") not in group["members"]:
                group["leader"] = ""
        self.selected_ids.clear()
        self._save_all()
        self._render_cards()
        self._set_status("已删除选中学生", FG_OK)

    def _edit_student(self):
        if not self._can_write():
            return
        if not self._selected_or_warn():
            return
        sid = sorted(self.selected_ids)[0]
        stu = self.all_students[self.current_class][sid]

        win = self._dialog("编辑学生资料", 380, 230)
        tk.Label(win, text=f"{sid} · 编辑资料", font=(FONT, 13, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(16, 10))
        form = tk.Frame(win, bg=BG_MAIN)
        form.pack()
        tk.Label(form, text="学号", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        e_id = self._entry(form)
        e_id.insert(0, sid)
        e_id.grid(row=0, column=1, pady=6)
        tk.Label(form, text="姓名", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=6)
        e_name = self._entry(form)
        e_name.insert(0, stu.get("name", ""))
        e_name.grid(row=1, column=1, pady=6)
        e_id.focus_set()

        def save():
            new_id = e_id.get().strip()
            new_name = e_name.get().strip()
            if not new_id or not new_name:
                messagebox.showwarning("提示", "学号和姓名不能为空", parent=win)
                return
            students = self.all_students[self.current_class]
            if new_id != sid and new_id in students:
                messagebox.showerror("错误", "学号已存在", parent=win)
                return
            if new_id != sid and not messagebox.askyesno(
                    "确认修改学号",
                    f"将 {sid} 的学号改为 {new_id}？\n积分、小组、登录密钥会一起迁移。",
                    parent=win):
                return
            record = students.pop(sid)
            record["stu_id"] = new_id
            record["name"] = new_name
            students[new_id] = record
            for group in self.group_data.get(self.current_class, {}).values():
                group["members"] = [new_id if m == sid else m
                                    for m in group.get("members", [])]
                if group.get("leader") == sid:
                    group["leader"] = new_id
            if sid in self.selected_ids:
                self.selected_ids.remove(sid)
                self.selected_ids.add(new_id)
            if new_id != sid:
                try:
                    import roles
                    roles.rename_student(sid, new_id)
                except Exception:
                    pass
            self._save_all()
            win.destroy()
            self._render_cards()
            self._center_on(new_id)
            self._set_status("学生资料已更新", FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=(14, 16))
        self._btn(row, "保存", save, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: save())
