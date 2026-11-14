"""
悬浮球增强（插件）

- 默认皮肤使用随插件附带的头像图片（assets/default_ball.png）
- 支持自定义悬浮球皮肤（自动裁成圆形）
- 单击悬浮球弹出快捷面板：快捷点名 / 课堂倒计时 / 班级排行
- 快捷点名、课堂倒计时、班级排行也可以从主界面「更多功能 → 插件」打开
"""

import hashlib
import random
import subprocess
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import plugin_api as plug
import schedule
from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
    FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_DANGER, FG_OK, dpi_scale,
)

PLUGIN = {
    "id": "ball_plus",
    "name": "悬浮球增强",
    "version": "1.0.0",
    "api_version": 1,
    "description": "头像皮肤 / 自定义皮肤 / 快捷点名 / 课堂倒计时 / 班级排行",
    "author": "710",
    "requires": [],
    "priority": 10,
}

FONT = "Microsoft YaHei UI"
ASSET_DIR = Path(__file__).parent / "assets"
DEFAULT_SKIN = "默认头像"
CUSTOM_SKIN = "自定义皮肤"

_WINDOWS = {}
_PANEL = None


# ===================== 小工具 =====================
def _place(win, width, height):
    k = dpi_scale(win)
    w, h = int(width * k), int(height * k)
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = max(10, (sw - w) // 2)
    y = max(20, (sh - h) // 3)
    win.geometry(f"{w}x{h}+{x}+{y}")


def _btn(parent, text, command, primary=False, width=None):
    return tk.Button(
        parent, text=text, command=command, font=(FONT, 10, "bold" if primary else "normal"),
        bg=BG_IN_CLASS if primary else BG_CELL, fg=FG_TEXT,
        activebackground="#4b7b4b" if primary else BG_CELL_ALT,
        activeforeground=FG_TEXT, relief=tk.FLAT, padx=12, pady=6,
        cursor="hand2", width=width)


def _open_singleton(key, factory):
    obj = _WINDOWS.get(key)
    try:
        if obj is not None and obj.win.winfo_exists():
            obj.win.deiconify()
            obj.win.lift()
            obj.win.focus_force()
            return obj.win
    except (tk.TclError, AttributeError):
        pass
    obj = factory()
    _WINDOWS[key] = obj

    def _forget(_event=None):
        if _WINDOWS.get(key) is obj:
            _WINDOWS.pop(key, None)
    obj.win.bind("<Destroy>", _forget, add="+")
    return obj.win


def _class_options(ctx):
    students = ctx.data.load_students()
    names = ctx.data.class_names() or list(students.keys())
    names = [n for n in names if n in students] or list(students.keys())
    return students, names


# ===================== 快捷面板 =====================
def open_quick_panel(ctx):
    global _PANEL
    try:
        if _PANEL is not None and _PANEL.winfo_exists():
            _PANEL.destroy()
            _PANEL = None
            return
    except tk.TclError:
        _PANEL = None

    win = tk.Toplevel(ctx.app)
    _PANEL = win
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=BG_CELL)
    k = dpi_scale(win)

    head = tk.Frame(win, bg=BG_CELL)
    head.pack(fill=tk.X, padx=14, pady=(10, 4))
    tk.Label(head, text="快捷操作", font=(FONT, 12, "bold"), bg=BG_CELL,
             fg=FG_ACCENT).pack(side=tk.LEFT)
    tk.Button(head, text="✕", command=win.destroy, bg=BG_CELL, fg=FG_DIM,
              activebackground=BG_CELL, activeforeground=FG_TEXT, relief=tk.FLAT,
              font=(FONT, 10), cursor="hand2").pack(side=tk.RIGHT)

    actions = [
        ("🎲 快捷点名", lambda: open_quick_call(ctx), True),
        ("⏳ 课堂倒计时", lambda: open_countdown(ctx), False),
        ("🏅 班级排行", lambda: open_ranking(ctx), False),
        ("📊 学生积分", lambda: ctx.ball.open_score(), False),
        ("🎨 更换悬浮球皮肤", lambda: choose_skin(ctx), False),
        ("👀 隐藏悬浮球", lambda: ctx.ball.hide(), False),
    ]
    for text, action, primary in actions:
        def run(act=action):
            try:
                win.destroy()
            except tk.TclError:
                pass
            act()
        _btn(win, text, run, primary=primary, width=20)\
            .pack(fill=tk.X, padx=14, pady=3)
    tk.Frame(win, bg=BG_CELL, height=8).pack()

    win.bind("<Escape>", lambda e: win.destroy())
    win.update_idletasks()
    width = int(220 * k)
    height = win.winfo_reqheight()
    pos = ctx.ball.position()
    if pos:
        bx, by, bsize = pos
        x = bx - width - int(10 * k)
        if x < 8:
            x = bx + bsize + int(10 * k)
        y = min(max(8, by + bsize - height), win.winfo_screenheight() - height - 40)
    else:
        x = (win.winfo_screenwidth() - width) // 2
        y = (win.winfo_screenheight() - height) // 3
    win.geometry(f"{width}x{height}+{x}+{y}")
    win.focus_force()


# ===================== 快捷点名 =====================
class QuickCallWindow:
    def __init__(self, ctx):
        self.ctx = ctx
        self.win = tk.Toplevel(ctx.app)
        self.win.title("快捷点名")
        self.win.configure(bg=BG_MAIN)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._rolling = False
        self._after_id = None
        self._pool = []
        self._result = None

        students, names = _class_options(ctx)
        self._students = students
        current = ctx.settings.get("class") or (names[0] if names else "")
        if current not in names:
            current = names[0] if names else ""

        header = tk.Frame(self.win, bg=BG_MAIN)
        header.pack(fill=tk.X, padx=22, pady=(16, 4))
        tk.Label(header, text="🎲 快捷点名", font=(FONT, 18, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        tk.Label(header, text="班级", font=(FONT, 10), bg=BG_MAIN,
                 fg=FG_DIM).pack(side=tk.LEFT, padx=(20, 6))
        self.class_var = tk.StringVar(value=current)
        self.class_box = ttk.Combobox(header, textvariable=self.class_var,
                                      values=names, state="readonly",
                                      width=16, font=(FONT, 10))
        self.class_box.pack(side=tk.LEFT)
        self.class_box.bind("<<ComboboxSelected>>", lambda e: self.reload())

        self.roll_label = tk.Label(self.win, text="准备好了吗？", font=(FONT, 44, "bold"),
                                   bg=BG_MAIN, fg=FG_TEXT)
        self.roll_label.pack(expand=True, pady=(10, 0))
        self.sub_label = tk.Label(self.win, text="", font=(FONT, 12),
                                  bg=BG_MAIN, fg=FG_DIM)
        self.sub_label.pack(pady=(0, 12))

        footer = tk.Frame(self.win, bg=BG_MAIN)
        footer.pack(pady=(0, 20))
        self.action_btn = _btn(footer, "开始点名", self.start_or_stop, primary=True,
                               width=14)
        self.action_btn.pack(side=tk.LEFT, padx=8)
        _btn(footer, "关闭", self.close, width=8).pack(side=tk.LEFT, padx=8)

        self.win.bind("<space>", lambda e: self.start_or_stop())
        self.win.bind("<Escape>", lambda e: self.close())
        _place(self.win, 600, 420)
        self.reload()

    def reload(self):
        cls = self.class_var.get()
        self.ctx.settings.set("class", cls)
        self._students = self.ctx.data.load_students()
        stu = self._students.get(cls, {})
        self._pool = [(sid, info) for sid, info in stu.items()
                      if isinstance(info, dict)]
        self.sub_label.config(text=f"{cls} · {len(self._pool)} 人")

    def start_or_stop(self):
        if self._rolling:
            self._rolling = False
            if self._after_id:
                try:
                    self.win.after_cancel(self._after_id)
                except tk.TclError:
                    pass
                self._after_id = None
            self._finish()
            return
        if not self._pool:
            messagebox.showinfo("快捷点名", "当前班级还没有学生", parent=self.win)
            return
        self._rolling = True
        self._result = random.choice(self._pool)
        self.action_btn.config(text="停 下", bg=BG_CELL, activebackground=BG_CELL_ALT)
        self._tick(int(1.6 * 1000))

    def _tick(self, remain):
        if not self._rolling or not self.win.winfo_exists():
            return
        sid, info = random.choice(self._pool)
        self.roll_label.config(text=info.get("name", sid), fg=FG_ACCENT)
        self.sub_label.config(text=f"{self.class_var.get()} · 点名中…",
                              fg=FG_DIM)
        if remain <= 0:
            self._finish()
            return
        delay = 60 if remain > 500 else 110
        self._after_id = self.win.after(delay, lambda: self._tick(remain - delay))

    def _finish(self):
        self._rolling = False
        if not self._result:
            return
        sid, info = self._result
        name = info.get("name", sid)
        self.roll_label.config(text=name, fg=FG_OK)
        groups = self.ctx.data.load_groups().get(self.class_var.get(), {})
        gmap = self.ctx.data.group_map(groups, self._students.get(
            self.class_var.get(), {}))
        total = self.ctx.data.total(info)
        self.sub_label.config(
            text=f"{self.class_var.get()} · {gmap.get(sid, '未分组')} · 当前 {total} 分",
            fg=FG_TEXT)
        self.action_btn.config(text="再点一次", bg=BG_IN_CLASS,
                               activebackground="#4b7b4b")
        self._result = None

    def close(self):
        self._rolling = False
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ===================== 课堂倒计时 =====================
class CountdownWindow:
    def __init__(self, ctx):
        self.ctx = ctx
        self.win = tk.Toplevel(ctx.app)
        self.win.title("课堂倒计时")
        self.win.configure(bg=BG_MAIN)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._custom_deadline = None
        self._custom_paused = False
        self._custom_left = 0
        self._closed = False

        self.state_label = tk.Label(self.win, text="", font=(FONT, 13),
                                    bg=BG_MAIN, fg=FG_DIM)
        self.state_label.pack(pady=(18, 2))
        self.big_label = tk.Label(self.win, text="--:--:--", font=(FONT, 52, "bold"),
                                  bg=BG_MAIN, fg=FG_ACCENT)
        self.big_label.pack()
        self.detail_label = tk.Label(self.win, text="", font=(FONT, 11),
                                     bg=BG_MAIN, fg=FG_TEXT)
        self.detail_label.pack(pady=(0, 10))

        box = tk.Frame(self.win, bg=BG_PANEL, highlightbackground=BG_CELL,
                       highlightthickness=1)
        box.pack(fill=tk.X, padx=26, pady=8)
        tk.Label(box, text="自定义倒计时", font=(FONT, 11, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        row = tk.Frame(box, bg=BG_PANEL)
        row.pack(fill=tk.X, padx=14, pady=(0, 10))
        tk.Label(row, text="分钟", font=(FONT, 9), bg=BG_PANEL, fg=FG_DIM)\
            .pack(side=tk.LEFT)
        self.minutes = tk.Spinbox(row, from_=1, to=120, width=6, font=(FONT, 11),
                                  bg=BG_CELL, fg=FG_TEXT, relief=tk.FLAT,
                                  buttonbackground=BG_CELL, insertbackground=FG_TEXT)
        self.minutes.delete(0, tk.END)
        self.minutes.insert(0, "5")
        self.minutes.pack(side=tk.LEFT, padx=6)
        self.custom_label = tk.Label(row, text="05:00", font=(FONT, 18, "bold"),
                                     bg=BG_PANEL, fg=FG_WARN)
        self.custom_label.pack(side=tk.LEFT, padx=14)
        _btn(row, "开始", self.start_custom).pack(side=tk.LEFT, padx=2)
        _btn(row, "暂停", self.pause_custom).pack(side=tk.LEFT, padx=2)
        _btn(row, "重置", self.reset_custom).pack(side=tk.LEFT, padx=2)
        _btn(row, "关闭", self.close).pack(side=tk.RIGHT, padx=2)

        self.win.bind("<Escape>", lambda e: self.close())
        _place(self.win, 620, 430)
        self._tick()

    def _tick(self):
        if self._closed or not self.win.winfo_exists():
            return
        info = schedule.find_current_period()
        now = datetime.now()
        state = info.get("state")
        seconds = 0
        if state == "in_class":
            end = info.get("current_end")
            target = datetime.combine(now.date(), end) if end else now
            seconds = max(0, int((target - now).total_seconds()))
            self.state_label.config(
                text=f"正在上课 · {info.get('current_name', '')} "
                     f"{info.get('current_subject', '')}", fg=FG_OK)
            nxt = info.get("next_name")
            self.detail_label.config(
                text=(f"下一节：{nxt} {info.get('next_subject', '')} "
                      f"{info.get('next_start').strftime('%H:%M')}"
                      if nxt and info.get("next_start") else "今天最后一节")
                )
        elif state in ("before_class", "between_class"):
            seconds = max(0, int(info.get("seconds_to_next", 0)))
            self.state_label.config(
                text=f"距离 {info.get('next_name', '')} "
                     f"{info.get('next_subject', '')} 上课", fg=FG_WARN)
            start = info.get("next_start")
            self.detail_label.config(
                text=f"上课时间 {start.strftime('%H:%M')}" if start else "")
        elif state == "disabled":
            self.state_label.config(text="当前处于禁用时间段", fg=FG_DANGER)
            self.detail_label.config(text=info.get("disabled_note", ""))
        elif state == "weekend":
            self.state_label.config(text="周末愉快", fg=FG_ACCENT)
            self.detail_label.config(text="今天没有课程安排")
        else:
            self.state_label.config(text="今日课程已结束", fg=FG_ACCENT)
            self.detail_label.config(text="好好休息，明天见")

        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        self.big_label.config(text=f"{hours:02d}:{minutes:02d}:{secs:02d}",
                              fg=FG_OK if state == "in_class" else FG_ACCENT)

        # 自定义倒计时
        if self._custom_deadline is not None and not self._custom_paused:
            left = int(self._custom_deadline - time.monotonic())
            if left <= 0:
                self._custom_deadline = None
                left = 0
                self.custom_label.config(text="时间到", fg=FG_DANGER)
                self.win.bell()
                try:
                    self.win.attributes("-topmost", True)
                except tk.TclError:
                    pass
            else:
                self._custom_left = left
                self.custom_label.config(text=self._format(left), fg=FG_WARN)
        elif self._custom_paused:
            self.custom_label.config(text=self._format(self._custom_left), fg=FG_DIM)

        self.win.after(500, self._tick)

    @staticmethod
    def _format(seconds):
        m, s = divmod(max(0, seconds), 60)
        return f"{m:02d}:{s:02d}"

    def start_custom(self):
        try:
            minutes = max(1, int(float(self.minutes.get())))
        except ValueError:
            minutes = 5
        if self._custom_paused and self._custom_left > 0:
            self._custom_deadline = time.monotonic() + self._custom_left
        else:
            self._custom_left = minutes * 60
            self._custom_deadline = time.monotonic() + self._custom_left
        self._custom_paused = False

    def pause_custom(self):
        if self._custom_deadline is not None and not self._custom_paused:
            self._custom_left = max(0, int(self._custom_deadline - time.monotonic()))
            self._custom_paused = True

    def reset_custom(self):
        self._custom_deadline = None
        self._custom_paused = False
        self._custom_left = 0
        self.custom_label.config(text="00:00", fg=FG_WARN)

    def close(self):
        self._closed = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ===================== 班级排行 =====================
class RankingWindow:
    def __init__(self, ctx):
        self.ctx = ctx
        self.win = tk.Toplevel(ctx.app)
        self.win.title("班级排行")
        self.win.configure(bg=BG_MAIN)
        self.mode = "student"
        self._students = self.ctx.data.load_students()
        names = self.ctx.data.class_names() or list(self._students.keys())
        names = [n for n in names if n in self._students] or list(self._students.keys())
        self.cls = self.ctx.settings.get("class") or (names[0] if names else "")
        if self.cls not in names:
            self.cls = names[0] if names else ""

        header = tk.Frame(self.win, bg=BG_MAIN)
        header.pack(fill=tk.X, padx=20, pady=(14, 4))
        tk.Label(header, text="🏅 班级排行", font=(FONT, 18, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        self.class_box = ttk.Combobox(header, values=names, state="readonly",
                                      width=16, font=(FONT, 10))
        if self.cls in names:
            self.class_box.set(self.cls)
        self.class_box.pack(side=tk.LEFT, padx=16)
        self.class_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        _btn(header, "学生榜", lambda: self.set_mode("student")).pack(
            side=tk.RIGHT, padx=3)
        _btn(header, "小组榜", lambda: self.set_mode("group")).pack(
            side=tk.RIGHT, padx=3)

        self.body = tk.Frame(self.win, bg=BG_MAIN)
        self.body.pack(fill=tk.BOTH, expand=True, padx=18, pady=8)
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        _place(self.win, 720, 640)
        self.refresh()

    def set_mode(self, mode):
        self.mode = mode
        self.refresh()

    def refresh(self):
        self.cls = self.class_box.get() or self.cls
        self.ctx.settings.set("class", self.cls)
        self._students = self.ctx.data.load_students()
        groups = self.ctx.data.load_groups()
        for child in self.body.winfo_children():
            child.destroy()

        if self.mode == "student":
            rows = self.ctx.data.rank_students(self._students, groups, self.cls)
            rows = [(r[0], f"{r[2]}", f"{r[1]}", r[4]) for r in rows]
            title = f"{self.cls} · 学生积分榜（共 {len(rows)} 人）"
        else:
            rows = self.ctx.data.rank_groups(self._students, groups, self.cls)
            rows = [(r[0], r[1], f"{r[2]} 人", r[3]) for r in rows]
            title = f"{self.cls} · 小组积分榜（共 {len(rows)} 组）"
        tk.Label(self.body, text=title, font=(FONT, 10), bg=BG_MAIN,
                 fg=FG_DIM).pack(anchor="w", pady=(0, 6))

        if not rows:
            tk.Label(self.body, text="暂无排行数据", font=(FONT, 12),
                     bg=BG_MAIN, fg=FG_DIM).pack(pady=40)
            return

        canvas = tk.Canvas(self.body, bg=BG_MAIN, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self.body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas, bg=BG_MAIN)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        max_val = max(1, max(abs(r[3]) for r in rows))
        for rank, name, extra, value in rows:
            row = tk.Frame(inner, bg=BG_CELL)
            row.pack(fill=tk.X, pady=2)
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else ""
            tk.Label(row, text=f"{medal}{rank}", font=(FONT, 11, "bold"),
                     bg=BG_CELL, fg=FG_ACCENT, width=6).pack(side=tk.LEFT, pady=7)
            tk.Label(row, text=name, font=(FONT, 11, "bold"), bg=BG_CELL,
                     fg=FG_TEXT, anchor="w", width=13).pack(side=tk.LEFT)
            tk.Label(row, text=extra, font=(FONT, 9), bg=BG_CELL, fg=FG_DIM,
                     width=7).pack(side=tk.LEFT)
            track = tk.Frame(row, bg="#2f2f3f", height=10)
            track.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            fill = tk.Frame(track, bg=FG_ACCENT if value >= 0 else FG_DANGER,
                            height=10, width=max(2, int(200 * abs(value) / max_val)))
            fill.pack(side=tk.LEFT)
            tk.Label(row, text=f"{value}", font=(FONT, 12, "bold"), bg=BG_CELL,
                     fg=FG_OK if value >= 0 else FG_DANGER, width=7,
                     anchor="e").pack(side=tk.LEFT, padx=(0, 8))


# ===================== 自定义皮肤 =====================
def _prepare_skin(source: Path) -> Path | None:
    source = Path(source)
    out_dir = plug.APP_DIR / "plugins_data" / "ball_skins"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        stamp = f"{source.stat().st_mtime}-{source.stat().st_size}"
    except OSError:
        stamp = str(source)
    digest = hashlib.md5(f"{source}|{stamp}".encode("utf-8")).hexdigest()[:12]
    out = out_dir / f"skin_{digest}.png"
    if out.exists():
        return out
    if source.resolve() == (ASSET_DIR / "default_ball.png").resolve():
        return source

    # 优先 Pillow（如果环境里装了）
    try:
        from PIL import Image, ImageDraw  # type: ignore
        img = Image.open(source).convert("RGBA")
        size = min(img.size)
        img = img.crop(((img.width - size) // 2, (img.height - size) // 2,
                        (img.width + size) // 2, (img.height + size) // 2))
        img = img.resize((256, 256), Image.LANCZOS)
        mask = Image.new("L", (256, 256), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 255, 255), fill=255)
        img.putalpha(mask)
        img.save(out, "PNG")
        return out
    except Exception:
        pass

    # Windows 自带 .NET，用 PowerShell 裁成圆形 PNG
    ps = out_dir / "_make_skin.ps1"
    script = f"""
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Image]::FromFile('{str(source).replace("'", "''")}')
$size = 256
$bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.Clear([System.Drawing.Color]::Transparent)
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.AddEllipse(0, 0, $size, $size)
$g.SetClip($path)
$g.DrawImage($src, 0, 0, $size, $size)
$g.ResetClip()
$bmp.Save('{str(out).replace("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose(); $src.Dispose()
"""
    try:
        ps.write_text(script, encoding="utf-8-sig")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(ps)], capture_output=True, timeout=40,
                       creationflags=flags)
        if out.exists():
            return out
    except Exception:
        pass
    finally:
        try:
            ps.unlink()
        except OSError:
            pass
    return None


def choose_skin(ctx):
    path = filedialog.askopenfilename(
        title="选择悬浮球皮肤图片",
        filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                   ("所有文件", "*.*")])
    if not path:
        return
    png = _prepare_skin(Path(path))
    if not png:
        messagebox.showerror("皮肤", "图片处理失败，请换一张 PNG 图片试试。")
        return
    ctx.ball.register_skin(CUSTOM_SKIN, png, default=False, order=1)
    ctx.ball.redraw()
    ok = ctx.ball.set_skin_name(CUSTOM_SKIN)
    ctx.settings.set("custom_skin", str(png))
    if ok:
        messagebox.showinfo("皮肤", "皮肤已更换，可拖拽悬浮球查看效果。")


def reset_skin(ctx):
    ctx.ball.set_skin_name(DEFAULT_SKIN)
    ctx.settings.set("custom_skin", "")


# ===================== 入口 =====================
def open_quick_call(ctx):
    return _open_singleton("quick_call", lambda: QuickCallWindow(ctx))


def open_countdown(ctx):
    return _open_singleton("countdown", lambda: CountdownWindow(ctx))


def open_ranking(ctx):
    return _open_singleton("ranking", lambda: RankingWindow(ctx))


def register(ctx):
    # 默认头像皮肤（用户提供的那张图）
    mascot = ASSET_DIR / "default_ball.png"
    if mascot.exists():
        ctx.ball.register_skin(DEFAULT_SKIN, mascot, default=True, order=0)

    # 上次选择的自定义皮肤
    saved = ctx.settings.get("custom_skin")
    if saved and Path(saved).exists():
        ctx.ball.register_skin(CUSTOM_SKIN, Path(saved), default=False, order=1)

    ctx.ball.add_menu("🎲 快捷点名", lambda: open_quick_call(ctx), order=10)
    ctx.ball.add_menu("⏳ 课堂倒计时", lambda: open_countdown(ctx), order=20)
    ctx.ball.add_menu("🏅 班级排行", lambda: open_ranking(ctx), order=30)
    ctx.ball.add_menu("🎨 自定义皮肤…", lambda: choose_skin(ctx), order=80)
    ctx.ball.add_menu("↺ 恢复默认头像", lambda: reset_skin(ctx), order=81)
    ctx.ball.set_click_action(lambda: open_quick_panel(ctx))

    ctx.ui.add_main_menu("🎲 快捷点名", lambda: open_quick_call(ctx), order=30)
    ctx.ui.add_main_menu("⏳ 课堂倒计时", lambda: open_countdown(ctx), order=31)
    ctx.ui.add_main_menu("🏅 班级排行", lambda: open_ranking(ctx), order=32)
