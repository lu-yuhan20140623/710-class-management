"""启动身份选择：学生端 / 教师端 / 值日生端 / 查看信息。

教师端 = 原主界面（需教师密钥）；学生端 = 学生只读门户（需学生密钥，默认学号）；
值日生端 = 按职务类型进入积分或卫生管理（需专用密钥）；查看信息 = 免密钥只读。
"""

from __future__ import annotations

import json
import sys
import time
import tkinter as tk
import urllib.request
from tkinter import ttk, messagebox
from pathlib import Path

import auth
import roles

from ui import (BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
                FG_TEXT, FG_DIM, FG_ACCENT, FG_DANGER, FG_WARN, FG_OK,
                fit_geometry, dpi_scale)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

STUDENT_FILE = APP_DIR / "student_data.txt"
FONT = "Microsoft YaHei UI"
ROLE_NAMES = ["值日长", "卫生长"]
ROLE_KINDS = {"值日长": roles.KIND_SCORE, "卫生长": roles.KIND_HYGIENE}


def _maximize(win, min_width=0, min_height=0):
    """登录相关窗口：允许调整大小并默认最大化。"""
    win.resizable(True, True)
    if min_width or min_height:
        win.minsize(min_width, min_height)
    try:
        win.state("zoomed")
    except tk.TclError:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{sw}x{sh}+0+0")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def students() -> dict:
    data = _load_json(STUDENT_FILE, {})
    return data if isinstance(data, dict) else {}


def _flat_students() -> list[tuple[str, str, str]]:
    """返回 [(班级, 学号, 姓名)]。"""
    out = []
    for cls, group in students().items():
        for sid, info in (group or {}).items():
            out.append((cls, str(sid), str(info.get("name") or sid)))
    return out


def _find_student(sid: str) -> tuple[str, str]:
    for cls, _sid, name in _flat_students():
        if _sid == str(sid):
            return cls, name
    return "", ""


# ===================== 通用小对话框 =====================
class _Dialog:
    def __init__(self, parent, title: str, width=420, height=280):
        self.ok = False
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=BG_MAIN)
        k = dpi_scale(self.win)
        # 不设 transient：Windows 下被拥有的窗口无法最大化
        _maximize(self.win, int((width + 60) * k), int((height + 60) * k))
        self.win.grab_set()
        holder = tk.Frame(self.win, bg=BG_MAIN)
        holder.pack(fill=tk.BOTH, expand=True)
        # 窗口最大化后表单仍保持居中、固定宽度，避免输入框被拉得过宽
        self.body = tk.Frame(holder, bg=BG_MAIN, padx=18, pady=16)
        self.body.place(relx=0.5, rely=0.5, anchor="center", width=int(width * k))

    def _label(self, text, row, color=FG_TEXT, size=10):
        tk.Label(self.body, text=text, font=(FONT, size), bg=BG_MAIN, fg=color,
                 anchor="w").grid(row=row, column=0, columnspan=2,
                                  sticky="ew", pady=(6, 2))

    def _entry(self, row, show=None):
        e = tk.Entry(self.body, font=(FONT, 11), bg=BG_CELL, fg=FG_TEXT,
                     insertbackground=FG_TEXT, relief=tk.FLAT, show=show or "")
        e.grid(row=row, column=0, columnspan=2, sticky="ew", ipady=5, pady=(0, 4))
        return e

    def _buttons(self, row, primary_text, primary_cmd):
        bar = tk.Frame(self.body, bg=BG_MAIN)
        bar.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        tk.Button(bar, text="取消", command=self.win.destroy, font=(FONT, 10),
                  bg=BG_CELL, fg=FG_TEXT, relief=tk.FLAT, padx=14, pady=5,
                  cursor="hand2").pack(side=tk.RIGHT, padx=(8, 0))
        btn = tk.Button(bar, text=primary_text, command=primary_cmd, font=(FONT, 10, "bold"),
                        bg=BG_IN_CLASS, fg=FG_TEXT, relief=tk.FLAT, padx=16, pady=5,
                        cursor="hand2")
        btn.pack(side=tk.RIGHT)
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)
        return btn


class ChangeKeyDialog(_Dialog):
    """先用原密钥验证，再设置新密钥。"""

    def __init__(self, parent, verify_fn, save_fn, title="修改密钥"):
        self._verify = verify_fn
        self._save = save_fn
        super().__init__(parent, title, 420, 330)
        self._label("原密钥", 0)
        self.e_old = self._entry(1, show="*")
        self._label("新密钥", 2)
        self.e_new = self._entry(3, show="*")
        self._label("确认新密钥", 4)
        self.e_new2 = self._entry(5, show="*")
        self._buttons(6, "保存", self._on_save)
        self.win.wait_window()

    def _on_save(self):
        old, new, new2 = self.e_old.get(), self.e_new.get(), self.e_new2.get()
        if not self._verify(old):
            messagebox.showwarning("修改密钥", "原密钥不正确", parent=self.win)
            return
        if not new:
            messagebox.showwarning("修改密钥", "新密钥不能为空", parent=self.win)
            return
        if new != new2:
            messagebox.showwarning("修改密钥", "两次输入的新密钥不一致", parent=self.win)
            return
        ok, msg = self._save(new)
        if ok:
            messagebox.showinfo("修改密钥", msg, parent=self.win)
            self.ok = True
            self.win.destroy()
        else:
            messagebox.showwarning("修改密钥", msg, parent=self.win)


def _lan_base() -> str:
    try:
        import lan_server
        return f"http://127.0.0.1:{lan_server.configured_port()}"
    except Exception:
        return "http://127.0.0.1:8765"


def _http_json(url: str, payload=None, timeout=3):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def mobile_approval_request(title: str, detail: str) -> str:
    """向后台服务登记一条“待手机确认”的重置请求，返回请求 id（失败返回空串）。"""
    try:
        res = _http_json(_lan_base() + "/api/approvals",
                         {"kind": "reset", "title": title, "detail": detail})
        return str(res.get("id") or "") if res.get("ok") else ""
    except Exception:
        return ""


def mobile_approval_status(rid: str) -> str:
    try:
        res = _http_json(_lan_base() + f"/api/approvals/status?id={rid}", timeout=2)
        return str(res.get("status") or "missing")
    except Exception:
        return "offline"


class PhoneResetDialog(_Dialog):
    """忘记密钥：手机号 + 新密钥。

    所有身份（教师 / 学生 / 值日生）的密钥重置，都必须再由手机 App 点击“同意”才生效。
    """

    def __init__(self, parent, title, reset_fn, approval_title="", approval_detail=""):
        self._reset = reset_fn
        self._approval_title = approval_title
        self._approval_detail = approval_detail
        self._rid = ""
        self._phone = ""
        self._new = ""
        self._deadline = 0.0
        super().__init__(parent, title, 440, 360)
        self._label("教师绑定的手机号", 0, FG_DIM)
        self.e_phone = self._entry(1)
        self._label("新密钥", 2)
        self.e_new = self._entry(3, show="*")
        self._label("确认新密钥", 4)
        self.e_new2 = self._entry(5, show="*")
        self.hint = tk.Label(self.body, text="", font=(FONT, 9), bg=BG_MAIN,
                             fg=FG_WARN, anchor="w", justify="left",
                             wraplength=int(400 * dpi_scale(self.win)))
        self.hint.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.btn = self._buttons(7, "重置", self._on_reset)
        self.win.wait_window()

    def _on_reset(self):
        phone, new, new2 = self.e_phone.get().strip(), self.e_new.get(), self.e_new2.get()
        if not phone:
            messagebox.showwarning("重置密钥", "请输入教师绑定的手机号", parent=self.win)
            return
        if not new:
            messagebox.showwarning("重置密钥", "新密钥不能为空", parent=self.win)
            return
        if new != new2:
            messagebox.showwarning("重置密钥", "两次输入的新密钥不一致", parent=self.win)
            return
        if not self._approval_title:
            self._apply(phone, new)
            return

        if not roles.verify_phone(phone):
            messagebox.showwarning("重置密钥", "手机号与教师绑定的号码不一致", parent=self.win)
            return
        rid = mobile_approval_request(self._approval_title, self._approval_detail)
        if not rid:
            messagebox.showwarning(
                "重置密钥",
                "无法发起手机确认：后台服务未启动或手机端未连接。\n"
                "请先在手机 App 中保持连接后重试。", parent=self.win)
            return
        self._rid, self._phone, self._new = rid, phone, new
        self._deadline = time.time() + 120
        self.btn.config(state=tk.DISABLED, text="等待手机确认…")
        self.hint.config(text="已发送确认请求，请在手机 App 中点击「同意」。", fg=FG_WARN)
        self.win.after(600, self._poll)

    def _poll(self):
        if not self.win.winfo_exists():
            return
        status = mobile_approval_status(self._rid)
        if status == "approved":
            self._apply(self._phone, self._new)
            return
        if status == "rejected":
            self._retry("手机端已拒绝本次重置，密钥未修改。")
            return
        if status in ("expired", "missing"):
            self._retry("手机确认已超时，请重新发起。")
            return
        if status == "offline":
            self._retry("与后台服务的连接中断，请确认手机端在线后重试。")
            return
        if time.time() > self._deadline:
            self._retry("等待手机确认超时，请重新发起。")
            return
        self.win.after(700, self._poll)

    def _retry(self, msg: str):
        self.btn.config(state=tk.NORMAL, text="重置")
        self.hint.config(text=msg, fg=FG_DANGER)

    def _apply(self, phone, new):
        ok, msg = self._reset(phone, new)
        if ok:
            messagebox.showinfo("重置密钥", msg, parent=self.win)
            self.ok = True
            self.win.destroy()
        else:
            self._retry(msg)


# ===================== 登录对话框 =====================
class TeacherLoginDialog(_Dialog):
    def __init__(self, parent):
        super().__init__(parent, "教师端 · 密钥", 420, 260)
        self._label("教师密钥", 0)
        if auth.is_default():
            self._label("初始密钥为 710，登录后可在「设置 → 密钥管理」修改", 1, FG_DIM, 9)
        self.e_key = self._entry(2, show="*")
        self.e_key.focus_set()
        self.win.bind("<Return>", lambda e: self._on_login())
        bar = tk.Frame(self.body, bg=BG_MAIN)
        bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        tk.Button(bar, text="忘记密钥", command=self._forgot, font=(FONT, 9),
                  bg=BG_PANEL, fg=FG_WARN, relief=tk.FLAT, padx=10, pady=5,
                  cursor="hand2").pack(side=tk.LEFT)
        tk.Button(bar, text="取消", command=self.win.destroy, font=(FONT, 10),
                  bg=BG_CELL, fg=FG_TEXT, relief=tk.FLAT, padx=14, pady=5,
                  cursor="hand2").pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(bar, text="进入教师端", command=self._on_login,
                  font=(FONT, 10, "bold"), bg=BG_IN_CLASS, fg=FG_TEXT,
                  relief=tk.FLAT, padx=16, pady=5, cursor="hand2").pack(side=tk.RIGHT)
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)
        self.win.wait_window()

    def _on_login(self):
        if auth.verify(self.e_key.get()):
            self.ok = True
            self.win.destroy()
        else:
            messagebox.showwarning("教师端", "密钥不正确", parent=self.win)
            self.e_key.delete(0, tk.END)
            self.e_key.focus_set()

    def _forgot(self):
        if not roles.get_phone():
            messagebox.showinfo("忘记密钥", "尚未绑定手机号，请联系管理员或重装后使用初始密钥 710。",
                                parent=self.win)
            return
        d = PhoneResetDialog(
            self.win, "教师端 · 重置密钥", auth.reset_password_by_phone,
            approval_title="重置教师密钥",
            approval_detail="电脑端发起了教师密钥重置，同意后新密钥立即生效。")
        if d.ok:
            messagebox.showinfo("重置密钥", "教师密钥已重置，请用新密钥登录。", parent=self.win)


class StudentLoginDialog(_Dialog):
    def __init__(self, parent):
        super().__init__(parent, "学生端 · 登录", 460, 360)
        self.ok = False
        self.sid = ""
        self.cls = ""
        self.name = ""

        data = students()
        self._classes = list(data.keys())
        self._label("班级", 0, FG_DIM)
        self.cb_class = ttk.Combobox(self.body, values=self._classes, state="readonly",
                                     font=(FONT, 10))
        self.cb_class.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=3)
        self.cb_class.bind("<<ComboboxSelected>>", lambda e: self._fill_students())
        if self._classes:
            self.cb_class.set(self._classes[0])

        self._label("我是谁", 2, FG_DIM)
        self.cb_student = ttk.Combobox(self.body, values=[], state="readonly",
                                       font=(FONT, 10))
        self.cb_student.grid(row=3, column=0, columnspan=2, sticky="ew", ipady=3)

        self._label("学生密钥（默认学号）", 4, FG_DIM)
        self.e_key = self._entry(5, show="*")

        bar = tk.Frame(self.body, bg=BG_MAIN)
        bar.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        for text, cmd, color in (("忘记密钥", self._forgot, FG_WARN),
                                 ("修改密钥", self._change, FG_DIM)):
            tk.Button(bar, text=text, command=cmd, font=(FONT, 9),
                      bg=BG_PANEL, fg=color, relief=tk.FLAT, padx=10, pady=5,
                      cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(bar, text="进入", command=self._on_login, font=(FONT, 10, "bold"),
                  bg=BG_IN_CLASS, fg=FG_TEXT, relief=tk.FLAT, padx=18, pady=5,
                  cursor="hand2").pack(side=tk.RIGHT)
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)
        self._fill_students()
        self.win.wait_window()

    def _fill_students(self):
        cls = self.cb_class.get()
        group = students().get(cls, {}) or {}
        self._list = [(str(sid), str(info.get("name") or sid))
                      for sid, info in group.items()]
        self.cb_student["values"] = [f"{sid} {name}" for sid, name in self._list]
        if self._list:
            self.cb_student.current(0)

    def _pick(self):
        idx = self.cb_student.current()
        if idx < 0 or idx >= len(self._list):
            messagebox.showwarning("学生端", "请选择学生", parent=self.win)
            return None
        return self._list[idx]

    def _on_login(self):
        picked = self._pick()
        if not picked:
            return
        sid, name = picked
        if roles.student_verify(sid, self.e_key.get()):
            self.ok, self.sid, self.name = True, sid, name
            self.cls = self.cb_class.get()
            self.win.destroy()
        else:
            messagebox.showwarning("学生端", "密钥不正确", parent=self.win)

    def _change(self):
        picked = self._pick()
        if not picked:
            return
        sid, name = picked
        d = ChangeKeyDialog(
            self.win,
            lambda old, s=sid: roles.student_verify(s, old),
            lambda new, s=sid: roles.student_set_key(s, new),
            title=f"修改 {name} 的学生密钥",
        )
        if d.ok:
            self.e_key.delete(0, tk.END)

    def _forgot(self):
        picked = self._pick()
        if not picked:
            return
        sid, name = picked
        if not roles.get_phone():
            messagebox.showinfo("忘记密钥", "教师尚未绑定手机号，无法自助重置。", parent=self.win)
            return
        PhoneResetDialog(
            self.win, f"{name} · 重置学生密钥",
            lambda phone, new, s=sid: roles.student_reset_with_phone(s, phone, new),
            approval_title=f"重置学生密钥：{name}",
            approval_detail=f"班级：{self.cb_class.get()}\n学生：{sid} {name}",
        )


class DutyLoginDialog(_Dialog):
    def __init__(self, parent):
        super().__init__(parent, "值日生端 · 登录", 470, 430)
        self.ok = False
        self.duty = None
        self.cls = ""

        flat = _flat_students()
        self._sid_map = {f"{sid} {name}": (cls, sid, name) for cls, sid, name in flat}
        self._label("学号", 0, FG_DIM)
        self.cb_sid = ttk.Combobox(self.body, values=list(self._sid_map.keys()),
                                   state="readonly", font=(FONT, 10))
        self.cb_sid.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=3)
        self.cb_sid.bind("<<ComboboxSelected>>", lambda e: self._fill_duties())
        if self._sid_map:
            self.cb_sid.current(0)

        self._label("姓名", 2, FG_DIM)
        self.lbl_name = tk.Label(self.body, text="", font=(FONT, 11, "bold"),
                                 bg=BG_CELL, fg=FG_TEXT, anchor="w", padx=8)
        self.lbl_name.grid(row=3, column=0, columnspan=2, sticky="ew", ipady=4)

        self._label("职务", 4, FG_DIM)
        self.cb_duty = ttk.Combobox(self.body, values=[], state="readonly", font=(FONT, 10))
        self.cb_duty.grid(row=5, column=0, columnspan=2, sticky="ew", ipady=3)

        self._label("专用密钥", 6, FG_DIM)
        self.e_key = self._entry(7, show="*")

        bar = tk.Frame(self.body, bg=BG_MAIN)
        bar.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        tk.Button(bar, text="忘记密钥", command=self._forgot, font=(FONT, 9),
                  bg=BG_PANEL, fg=FG_WARN, relief=tk.FLAT, padx=10, pady=5,
                  cursor="hand2").pack(side=tk.LEFT)
        self.btn_login = tk.Button(bar, text="进入", command=self._on_login,
                                   font=(FONT, 10, "bold"),
                                   bg=BG_IN_CLASS, fg=FG_TEXT, relief=tk.FLAT,
                                   padx=18, pady=5, cursor="hand2")
        self.btn_login.pack(side=tk.RIGHT)
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)
        self._fill_duties()
        self.win.wait_window()

    def _current_student(self):
        return self._sid_map.get(self.cb_sid.get())

    def _fill_duties(self):
        info = self._current_student()
        self._duty_list = []
        if not info:
            return
        _cls, sid, name = info
        self.lbl_name.config(text=name)
        self._duty_list = roles.duties_for(sid)
        self.cb_duty["values"] = [f"{d['role']} · {roles.kind_label(d['kind'])}"
                                  for d in self._duty_list]
        if self._duty_list:
            self.cb_duty.current(0)
        else:
            self.cb_duty.set("")
            self.lbl_name.config(text=f"{name}（暂无值日生任命）")
        self.btn_login.config(
            state=tk.NORMAL if self._duty_list else tk.DISABLED)

    def _pick_duty(self):
        idx = self.cb_duty.current()
        if idx < 0 or idx >= len(self._duty_list):
            messagebox.showwarning("值日生端", "该学生没有被任命为值日生", parent=self.win)
            return None
        return self._duty_list[idx]

    def _on_login(self):
        duty = self._pick_duty()
        if not duty:
            return
        if roles.duty_verify(duty, self.e_key.get()):
            self.ok, self.duty = True, duty
            self.cls = self._current_student()[0]
            self.win.destroy()
        else:
            messagebox.showwarning("值日生端", "专用密钥不正确", parent=self.win)

    def _forgot(self):
        duty = self._pick_duty()
        if not duty:
            return
        if not roles.get_phone():
            messagebox.showinfo("忘记密钥", "教师尚未绑定手机号，无法自助重置。", parent=self.win)
            return
        PhoneResetDialog(
            self.win, f"{duty['name']} · 重置值日生密钥",
            lambda phone, new, d=duty["id"]: roles.duty_reset_with_phone(d, phone, new),
            approval_title=f"重置值日生密钥：{duty['name']}",
            approval_detail=(f"班级：{self._current_student()[0]}\n"
                             f"学生：{duty['sid']} {duty['name']}\n"
                             f"职务：{duty['role']}"),
        )


# ===================== 身份选择窗口 =====================
class EntryWindow:
    def __init__(self, root):
        self.root = root
        self.mode = None
        self.payload = None
        self.win = tk.Toplevel(root)
        self.win.title("课程表 · 选择身份")
        self.win.configure(bg=BG_MAIN)
        _maximize(self.win, 640, 560)
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.grab_set()

        panel = tk.Frame(self.win, bg=BG_MAIN)
        panel.place(relx=0.5, rely=0.5, anchor="center",
                    width=int(760 * dpi_scale(self.win)))

        tk.Label(panel, text="课程表", font=(FONT, 26, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(28, 2))
        tk.Label(panel, text="请选择进入的身份", font=(FONT, 11),
                 bg=BG_MAIN, fg=FG_DIM).pack(pady=(0, 16))

        grid = tk.Frame(panel, bg=BG_MAIN)
        grid.pack(padx=26, pady=4, fill=tk.BOTH, expand=True)
        cards = [
            ("👨‍🏫", "教师端", "进入主界面，需要教师密钥", self._teacher),
            ("🎒", "学生端", "查看自己的积分与课表，需学生密钥", self._student),
            ("🧹", "值日生端", "按职务进入积分 / 卫生管理", self._duty),
            ("📖", "查看信息", "课程表、积分、卫生（只读）", self._view),
        ]
        for i, (icon, title, desc, cmd) in enumerate(cards):
            card = tk.Frame(grid, bg=BG_PANEL, cursor="hand2",
                            highlightbackground=BG_CELL, highlightthickness=1)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            inner = tk.Frame(card, bg=BG_PANEL, cursor="hand2")
            inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
            tk.Label(inner, text=icon, font=(FONT, 22), bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
            tk.Label(inner, text=title, font=(FONT, 13, "bold"), bg=BG_PANEL,
                     fg=FG_TEXT).pack(anchor="w", pady=(4, 0))
            tk.Label(inner, text=desc, font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM,
                     wraplength=300, justify="left").pack(anchor="w", pady=(2, 0))
            for w in (card, inner, *inner.winfo_children()):
                w.bind("<Button-1>", lambda e, c=cmd: c())
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        for r in range(2):
            grid.rowconfigure(r, weight=1)

        tk.Label(panel, text="教师初始密钥 710 · 忘记密钥可用教师手机号重置",
                 font=(FONT, 8), bg=BG_MAIN, fg=FG_DIM).pack(side=tk.BOTTOM, pady=10)

        self.win.wait_window()

    def _finish(self, mode, payload=None):
        self.mode, self.payload = mode, payload
        self.win.destroy()

    def _cancel(self):
        self.mode = None
        self.win.destroy()

    def _teacher(self):
        d = TeacherLoginDialog(self.win)
        if d.ok:
            self._finish("teacher")

    def _student(self):
        d = StudentLoginDialog(self.win)
        if d.ok:
            self._finish("student", {"sid": d.sid, "name": d.name, "cls": d.cls})

    def _duty(self):
        d = DutyLoginDialog(self.win)
        if d.ok:
            self._finish("duty", {"duty": d.duty, "cls": d.cls})

    def _view(self):
        self._finish("view")


def choose(root):
    """显示身份选择；返回 (mode, payload)。取消时 mode 为 None。"""
    w = EntryWindow(root)
    return w.mode, w.payload


# ===================== 目标窗口 =====================
def _bind_close(win, root, extra=None):
    def _close():
        try:
            if extra:
                extra()
        except Exception:
            pass
        for w in (win, root):
            try:
                w.destroy()
            except Exception:
                pass
    win.protocol("WM_DELETE_WINDOW", _close)


def open_target(root, mode, payload):
    """打开非教师端的目标窗口；返回打开的窗口对象。"""
    payload = payload or {}
    if mode == "student":
        import plugin_api
        mgr = plugin_api.init(app=root)
        mgr.load_all()
        ctx = mgr.contexts.get("role_portal")
        if ctx is None:
            from student_score import StudentScoreWindow
            win = StudentScoreWindow(root, default_class=payload.get("cls") or "七年级10班",
                                     readonly=True).win
            _bind_close(win, root)
            return win
        from plugins.role_portal import StudentPortalWindow
        portal = StudentPortalWindow(ctx, class_name=payload.get("cls"),
                                     sid=payload.get("sid"),
                                     allow_switch=False)
        _bind_close(portal.win, root, extra=portal.close)
        return portal.win

    if mode == "duty":
        duty = payload.get("duty") or {}
        cls = payload.get("cls") or None
        if duty.get("kind") == roles.KIND_HYGIENE:
            from hygiene import HygieneWindow
            win = HygieneWindow(
                root, default_class=cls,
                operator={"name": duty.get("name", ""), "sid": duty.get("sid", ""),
                          "role": duty.get("role", "卫生长")},
            ).win
        else:
            from student_score import StudentScoreWindow
            win = StudentScoreWindow(root, default_class=cls).win
        _bind_close(win, root)
        return win

    win = ViewerWindow(root).win
    _bind_close(win, root)
    return win


# ===================== 查看信息 =====================
class ViewerWindow:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("查看信息（只读）· 课程表")
        self.win.configure(bg=BG_MAIN)
        fit_geometry(self.win, 520, 420, 420, 340)

        tk.Label(self.win, text="查看信息", font=(FONT, 20, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(22, 2))
        tk.Label(self.win, text="以下内容均为只读", font=(FONT, 10),
                 bg=BG_MAIN, fg=FG_DIM).pack(pady=(0, 14))

        for text, cmd in (("📅 课程表", self._schedule),
                          ("👥 积分（只读）", self._scores),
                          ("🧹 卫生（只读）", self._hygiene)):
            tk.Button(self.win, text=text, command=cmd, font=(FONT, 12),
                      bg=BG_CELL, fg=FG_TEXT, activebackground=BG_CELL_ALT,
                      activeforeground=FG_TEXT, relief=tk.FLAT, padx=16, pady=12,
                      cursor="hand2").pack(fill=tk.X, padx=40, pady=6)

    def _schedule(self):
        ScheduleViewer(self.win)

    def _scores(self):
        from student_score import StudentScoreWindow
        StudentScoreWindow(self.win, readonly=True)

    def _hygiene(self):
        from hygiene import HygieneWindow
        HygieneWindow(self.win, readonly=True)


class ScheduleViewer:
    """只读周课表。"""

    DAYS = ["周一", "周二", "周三", "周四", "周五"]

    def __init__(self, parent):
        import schedule_core as sch
        win = tk.Toplevel(parent)
        win.title("课程表（只读）")
        win.configure(bg=BG_MAIN)
        fit_geometry(win, 760, 520, 620, 420)
        self.win = win

        tk.Label(win, text="本周课程表", font=(FONT, 18, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))

        grid = tk.Frame(win, bg=BG_PANEL)
        grid.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        tk.Label(grid, text="节次", font=(FONT, 10, "bold"), bg=BG_PANEL,
                 fg=FG_DIM, width=8).grid(row=0, column=0, padx=1, pady=1, sticky="nsew")
        for c, day in enumerate(self.DAYS, start=1):
            tk.Label(grid, text=day, font=(FONT, 11, "bold"), bg=BG_PANEL,
                     fg=FG_TEXT).grid(row=0, column=c, padx=1, pady=1, sticky="nsew")
            grid.columnconfigure(c, weight=1)

        for r, period in enumerate(sorted(sch.PERIODS), start=1):
            start, end = sch.PERIODS[period]
            tk.Label(grid, text=f"{period}\n{start:%H:%M}", font=(FONT, 8),
                     bg=BG_PANEL, fg=FG_DIM).grid(row=r, column=0, padx=1, pady=1,
                                                  sticky="nsew")
            for c in range(5):
                subject = sch.get_subject(c, period)
                tk.Label(grid, text=subject or "—", font=(FONT, 10),
                         bg=BG_CELL, fg=FG_TEXT if subject else FG_DIM,
                         wraplength=110).grid(row=r, column=c + 1, padx=1, pady=1,
                                              sticky="nsew")
            grid.rowconfigure(r, weight=1)

        r = len(sch.PERIODS) + 1
        tk.Label(grid, text=f"午间\n{sch.PRACTICE_START:%H:%M}", font=(FONT, 8),
                 bg=BG_PANEL, fg=FG_DIM).grid(row=r, column=0, padx=1, pady=1, sticky="nsew")
        for c in range(5):
            tk.Label(grid, text=sch.PRACTICE_SUBJECTS.get(c, "—"), font=(FONT, 10),
                     bg=BG_CELL, fg=FG_TEXT).grid(row=r, column=c + 1, padx=1, pady=1,
                                                  sticky="nsew")
        grid.rowconfigure(r, weight=1)


# ===================== 教师端：值日生任命 =====================
class DutyAdminWindow:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("值日生任命 · 课程表")
        self.win.configure(bg=BG_MAIN)
        fit_geometry(self.win, 820, 600, 700, 520)

        tk.Label(self.win, text="值日生任命", font=(FONT, 19, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(self.win, text="为值日长分配积分管理、为卫生长分配卫生管理；密钥可通过教师手机号重置",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack(anchor="w", padx=18)

        # 列表
        body = tk.Frame(self.win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=10)
        cols = ("name", "role", "kind", "key")
        style = ttk.Style()
        style.configure("Duty.Treeview", background=BG_CELL, fieldbackground=BG_CELL,
                        foreground=FG_TEXT, borderwidth=0,
                        rowheight=max(24, int(28 * dpi_scale(self.win))),
                        font=(FONT, 10))
        style.configure("Duty.Treeview.Heading", background=BG_CELL_ALT,
                        foreground=FG_ACCENT, relief=tk.FLAT,
                        font=(FONT, 10, "bold"))
        style.map("Duty.Treeview",
                  background=[("selected", "#2f5f8f")],
                  foreground=[("selected", FG_TEXT)])
        style.map("Duty.Treeview.Heading",
                  background=[("active", BG_CELL_ALT)],
                  foreground=[("active", FG_ACCENT)])
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=9,
                                 style="Duty.Treeview")
        for col, text, width in (("name", "姓名", 120), ("role", "职务", 160),
                                 ("kind", "类型", 120), ("key", "密钥", 110)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        btns = tk.Frame(self.win, bg=BG_MAIN)
        btns.pack(fill=tk.X, padx=18)
        self._btn(btns, "重置密钥", self._reset_key).pack(side=tk.LEFT)
        self._btn(btns, "撤销任命", self._remove).pack(side=tk.LEFT, padx=8)

        # 新增
        form = tk.Frame(self.win, bg=BG_PANEL)
        form.pack(fill=tk.X, padx=18, pady=12)
        row = tk.Frame(form, bg=BG_PANEL)
        row.pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(row, text="学生", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM).pack(side=tk.LEFT)
        self._flat = _flat_students()
        self.cb_student = ttk.Combobox(row, values=[f"{sid} {name}" for _c, sid, name in self._flat],
                                       state="readonly", width=18, font=(FONT, 10))
        self.cb_student.pack(side=tk.LEFT, padx=8)
        if self._flat:
            self.cb_student.current(0)

        tk.Label(row, text="职务", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM).pack(side=tk.LEFT, padx=(12, 0))
        self.cb_role = ttk.Combobox(row, values=ROLE_NAMES, state="normal", width=12,
                                    font=(FONT, 10))
        self.cb_role.set("值日长")
        self.cb_role.pack(side=tk.LEFT, padx=8)
        self.cb_role.bind("<<ComboboxSelected>>", lambda e: self._sync_kind())

        tk.Label(row, text="类型", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM).pack(side=tk.LEFT, padx=(12, 0))
        self.cb_kind = ttk.Combobox(row, values=list(roles.KIND_LABELS.values()),
                                    state="readonly", width=10, font=(FONT, 10))
        self.cb_kind.set(roles.kind_label(roles.KIND_SCORE))
        self.cb_kind.pack(side=tk.LEFT, padx=8)

        row2 = tk.Frame(form, bg=BG_PANEL)
        row2.pack(fill=tk.X, padx=12, pady=(2, 12))
        tk.Label(row2, text="专用密钥", font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM).pack(side=tk.LEFT)
        self.e_key = tk.Entry(row2, font=(FONT, 10), bg=BG_CELL, fg=FG_TEXT,
                              insertbackground=FG_TEXT, relief=tk.FLAT, width=16)
        self.e_key.pack(side=tk.LEFT, padx=8, ipady=3)
        tk.Label(row2, text="留空自动生成 6 位数字", font=(FONT, 8),
                 bg=BG_PANEL, fg=FG_DIM).pack(side=tk.LEFT, padx=6)
        self._btn(row2, "添加任命", self._add, primary=True).pack(side=tk.RIGHT)

        self._refresh()

    def _btn(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd,
                         bg=BG_IN_CLASS if primary else BG_CELL, fg=FG_TEXT,
                         activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                         relief=tk.FLAT, font=(FONT, 10, "bold" if primary else "normal"),
                         padx=14, pady=5, cursor="hand2")

    def _sync_kind(self):
        name = self.cb_role.get().strip()
        kind = ROLE_KINDS.get(name)
        if kind:
            self.cb_kind.set(roles.kind_label(kind))

    def _kind_value(self):
        label = self.cb_kind.get()
        for kind, text in roles.KIND_LABELS.items():
            if text == label:
                return kind
        return roles.KIND_SCORE

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for d in roles.duties():
            self.tree.insert("", "end", iid=d["id"],
                             values=(d.get("name", ""), d.get("role", ""),
                                     roles.kind_label(d.get("kind", "")), "••••••"))

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("值日生任命", "请先在列表中选择一条任命", parent=self.win)
            return None
        return roles.find_duty(sel[0])

    def _add(self):
        idx = self.cb_student.current()
        if idx < 0 or idx >= len(self._flat):
            messagebox.showwarning("值日生任命", "请选择学生", parent=self.win)
            return
        _cls, sid, name = self._flat[idx]
        ok, msg, duty = roles.add_duty(sid, name, self.cb_role.get(),
                                       self._kind_value(), self.e_key.get())
        if not ok:
            messagebox.showwarning("值日生任命", msg, parent=self.win)
            return
        self.e_key.delete(0, tk.END)
        self._refresh()
        key = (duty or {}).get("plain_key")
        if key:
            self._show_key(name, self.cb_role.get(), key)
        else:
            messagebox.showinfo("值日生任命", msg, parent=self.win)

    def _show_key(self, name, role, key):
        """任命成功：展示自动生成的密钥，并支持一键复制。"""
        top = tk.Toplevel(self.win)
        top.title("任命成功")
        top.configure(bg=BG_MAIN)
        top.resizable(False, False)
        k = dpi_scale(top)
        top.geometry(f"{int(460 * k)}x{int(250 * k)}"
                     f"+{self.win.winfo_rootx() + int(120 * k)}"
                     f"+{self.win.winfo_rooty() + int(120 * k)}")
        top.grab_set()
        tk.Label(top, text=f"已任命 {name} 为「{role}」", font=(FONT, 12, "bold"),
                 bg=BG_MAIN, fg=FG_OK).pack(pady=(18, 6))
        tk.Label(top, text="专用密钥（仅显示这一次，请转告本人）", font=(FONT, 9),
                 bg=BG_MAIN, fg=FG_DIM).pack()
        row = tk.Frame(top, bg=BG_MAIN)
        row.pack(pady=12)
        ent = tk.Entry(row, font=(FONT, 18, "bold"), bg=BG_CELL, fg=FG_ACCENT,
                       justify="center", relief=tk.FLAT, width=9)
        ent.insert(0, key)
        ent.config(state="readonly")
        ent.pack(side=tk.LEFT, ipady=6)
        copy_btn = tk.Button(row, text="复制", font=(FONT, 10), bg=BG_CELL,
                             fg=FG_TEXT, relief=tk.FLAT, padx=12, pady=6,
                             cursor="hand2")

        def copy():
            top.clipboard_clear()
            top.clipboard_append(key)
            copy_btn.config(text="已复制")

        copy_btn.config(command=copy)
        copy_btn.pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(top, text="知道了", command=top.destroy, font=(FONT, 10, "bold"),
                  bg=BG_IN_CLASS, fg=FG_TEXT, relief=tk.FLAT, padx=18, pady=5,
                  cursor="hand2").pack()
        top.wait_window()

    def _reset_key(self):
        duty = self._selected()
        if not duty:
            return
        d = ChangeKeyDialog(
            self.win,
            lambda old: roles.duty_verify(duty, old),
            lambda new: roles.duty_set_key(duty["id"], new),
            title=f"重置 {duty['name']} 的密钥",
        )
        if d.ok:
            self._refresh()

    def _remove(self):
        duty = self._selected()
        if not duty:
            return
        if not messagebox.askyesno("撤销任命",
                                   f"确定撤销 {duty['name']} 的「{duty['role']}」任命吗？",
                                   parent=self.win):
            return
        ok, msg = roles.remove_duty(duty["id"])
        if not ok:
            messagebox.showwarning("撤销任命", msg, parent=self.win)
        self._refresh()
