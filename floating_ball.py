"""
桌面悬浮球（由后台常驻进程负责，Always on Top）
- 独立进程运行（floating_ball_service.py / ClassSchedule_Ball.exe），由 backend_service.py 拉起并保活
- 外观与交互保持原来的方式：无边框圆形、圆外透明、可拖动、右键换肤
- 单击：弹密钥 → 打开学生积分；右键：换肤 / 打开积分 / 只读查看 / 隐藏
- 隐藏后进程仍常驻，由主界面「更多功能 → 显示悬浮球」重新唤出
- 位置按「任务栏之外的可用区域」计算并记忆拖动位置
"""

import json
import math
import os
import sys
import tkinter as tk
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
SETTINGS_FILE = APP_DIR / "settings.json"

BASE_SIZE = 68                      # 100% 缩放下的直径，实际按 DPI 放大
TRANSPARENT = "#010203"             # 透明色键（Windows -transparentcolor）

# 3 套皮肤：主体 / 描边 / 光晕 / 高光 / 星星 / 文字
SKINS = [
    {"name": "深蓝", "bg": "#1e2a44", "ring": "#4d9fff", "glow": "#101a2e",
     "gloss": "#8ec8ff", "star": "#ffd54f", "star_edge": "#f0a500",
     "fg": "#d6e9ff"},
    {"name": "翡翠", "bg": "#17332a", "ring": "#3ddc97", "glow": "#0b1d16",
     "gloss": "#8ff0c4", "star": "#ffd54f", "star_edge": "#e6a000",
     "fg": "#d6ffe9"},
    {"name": "紫夜", "bg": "#2b1f45", "ring": "#b07bff", "glow": "#1a1230",
     "gloss": "#d7bcff", "star": "#ffd54f", "star_edge": "#e6a000",
     "fg": "#e8dbff"},
]


def _load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _save_settings(patch: dict):
    """只更新指定键，保留 settings.json 里的其他配置（如预警阈值）。"""
    data = _load_settings()
    data.update(patch)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class FloatingBall:
    """可拖动、可换肤、始终置顶的悬浮球。"""

    def __init__(self, root: tk.Tk, size: int | None = None):
        self.root = root
        self.k = self._dpi()
        # 尺寸随 DPI 放大，避免高分屏上球小得像颗芝麻
        self.size = size or max(56, min(int(BASE_SIZE * self.k), 128))

        self._drag = None
        saved = _load_settings().get("floating_ball") or {}
        self._hidden = bool(saved.get("hidden", False))
        try:
            self._skin = int(saved.get("skin", 0)) % len(SKINS)
        except (TypeError, ValueError):
            self._skin = 0
        # 插件注册的图片皮肤 / 球菜单 / 单击动作
        self._extra_skins = []          # [{"name", "path", "order"}]
        self._plugin_menus = []         # [{"label", "callback", "order"}]
        self._click_action = None
        self._photo = None
        self._skin_pref = str(saved.get("skin_name") or "")

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        # 圆外区域做成透明色，才是真正的圆形，而不是一块深色方块
        self._bg = TRANSPARENT
        self.win.configure(bg=self._bg)
        try:
            self.win.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            # 系统不支持透明色键时退回与光晕同色，至少看不出方块边
            self._bg = SKINS[self._skin]["glow"]
            self.win.configure(bg=self._bg)

        self.canvas = tk.Canvas(self.win, width=self.size, height=self.size,
                                bg=self._bg, highlightthickness=0, bd=0)
        self.canvas.pack()

        self._place(saved)
        self._draw()
        self._bind()
        self._pin_topmost()
        if self._hidden:
            # 上次隐藏过，进程重启后依旧不显示，等主界面来唤
            self.win.withdraw()
            self._watch_show_request()

    # ---------- 环境 ----------
    def _dpi(self) -> float:
        try:
            return max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except Exception:
            return 1.0

    def _work_area(self):
        """任务栏之外的可用区域（left, top, right, bottom）。"""
        try:
            from ui import work_area
            return work_area(self.root)
        except Exception:
            return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _place(self, saved: dict):
        """优先恢复上次拖动的位置，越界则回到右侧 40% 高度处。"""
        wl, wt, wr, wb = self._work_area()
        margin = int(22 * self.k)
        x, y = saved.get("x"), saved.get("y")
        ok = (isinstance(x, int) and isinstance(y, int)
              and wl <= x <= wr - self.size and wt <= y <= wb - self.size)
        if not ok:
            x = wr - self.size - margin
            y = wt + int((wb - wt) * 0.40) - self.size // 2
        self.win.geometry(f"{self.size}x{self.size}+{x}+{y}")

    # ---------- 绘制 ----------
    @staticmethod
    def _star_points(cx, cy, r_out, r_in, rot=-90.0):
        pts = []
        for i in range(10):
            r = r_out if i % 2 == 0 else r_in
            a = math.radians(rot + i * 36)
            pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def _draw(self):
        items = self._skin_items()
        if not items:
            return
        self._skin %= len(items)
        item = items[self._skin]
        if item["kind"] == "image" and self._draw_image(item["path"]):
            return
        if item["kind"] == "image":
            # 图片皮肤不可用（缺 Pillow / 文件损坏）时退回第一套矢量皮肤
            self._skin = 0
        sk = SKINS[self._skin % len(SKINS)]
        s = self.size
        c = self.canvas
        c.delete("all")
        # 外圈光晕
        c.create_oval(0, 0, s, s, fill=sk["glow"], outline="")
        # 球体
        bw = max(2, s // 30)
        c.create_oval(bw, bw, s - bw, s - bw,
                      fill=sk["bg"], outline=sk["ring"], width=bw)
        # 左上高光弧，让球有玻璃质感
        c.create_arc(s * 0.16, s * 0.13, s * 0.84, s * 0.62,
                     start=25, extent=130, style=tk.ARC,
                     outline=sk["gloss"], width=max(2, s // 26))
        # 中央五角星
        c.create_polygon(self._star_points(s / 2, s * 0.43, s * 0.23, s * 0.095),
                         fill=sk["star"], outline=sk["star_edge"], width=1)
        # 球内文案
        c.create_text(s / 2, s * 0.77, text="积分", fill=sk["fg"],
                      font=("Microsoft YaHei UI", max(8, int(s * 0.14)), "bold"))

    # ---------- 皮肤 ----------
    def _skin_items(self) -> list:
        """矢量皮肤 + 插件注册的图片皮肤，按 order 排。"""
        items = [{"kind": "vector", "name": sk["name"], "index": i}
                 for i, sk in enumerate(SKINS)]
        for extra in sorted(self._extra_skins, key=lambda s: (s["order"], s["name"])):
            items.append({"kind": "image", "name": extra["name"],
                          "path": extra["path"]})
        return items

    def _skin_names(self) -> list:
        return [item["name"] for item in self._skin_items()]

    def _draw_image(self, path) -> bool:
        """把图片裁成圆形画到球上；缺 Pillow 或图片损坏时返回 False。"""
        try:
            from PIL import Image, ImageDraw, ImageOps, ImageTk
        except Exception:
            return False
        size = self.size
        try:
            img = Image.open(path).convert("RGBA")
            resample = getattr(Image, "Resampling", Image).LANCZOS
            img = ImageOps.fit(img, (size, size), resample)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
            img.putalpha(mask)
            self._photo = ImageTk.PhotoImage(img, master=self.win)
        except Exception:
            return False
        c = self.canvas
        s = size
        c.delete("all")
        c.create_oval(0, 0, s, s, fill="#101a2e", outline="")
        c.create_image(s / 2, s / 2, image=self._photo)
        bw = max(2, s // 30)
        c.create_oval(bw, bw, s - bw, s - bw, outline="#4d9fff", width=bw)
        return True

    # ---------- 事件 ----------
    def _bind(self):
        self.canvas.configure(cursor="hand2")
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._popup_menu)

    def _on_press(self, event):
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y(), False)

    def _on_drag(self, event):
        if not self._drag:
            return
        dx, dy, _ = self._drag
        wl, wt, wr, wb = self._work_area()
        nx = max(wl, min(event.x_root - dx, wr - self.size))
        ny = max(wt, min(event.y_root - dy, wb - self.size))
        self.win.geometry(f"+{nx}+{ny}")
        self._drag = (dx, dy, True)

    def _on_release(self, _event):
        moved = self._drag[2] if self._drag else False
        self._drag = None
        if moved:
            # 记住位置，下次启动还在原处
            self._save_position()
            return
        if self._click_action is not None:
            try:
                self._click_action()
            except Exception as exc:
                print(f"[悬浮球] 单击动作失败：{exc}")
            return
        self.open_score()          # 默认编辑模式，需密钥

    def _popup_menu(self, event):
        menu = tk.Menu(self.win, tearoff=0, bg="#2a2a3a", fg="#e8e8f0",
                       activebackground="#3a3a4a", activeforeground="#e8e8f0",
                       bd=0, font=("Microsoft YaHei UI", 10))
        for i, skin in enumerate(self._skin_items()):
            label = ("● " if i == self._skin else "○ ") + f"皮肤：{skin['name']}"
            menu.add_command(label=label, command=lambda i=i: self.set_skin(i))
        menu.add_separator()
        for item in self._plugin_menus:
            menu.add_command(label=item["label"], command=item["callback"])
        if self._plugin_menus:
            menu.add_separator()
        menu.add_command(label="打开学生积分（需密钥）", command=self.open_score)
        menu.add_command(label="只读查看", command=lambda: self.open_score(True))
        menu.add_separator()
        menu.add_command(label="隐藏悬浮球", command=self.hide)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---------- 插件接口 ----------
    def add_plugin_menu(self, label: str, callback, order: int = 100):
        self._plugin_menus.append({"label": label, "callback": callback,
                                   "order": order})
        self._plugin_menus.sort(key=lambda i: (i["order"], i["label"]))

    def register_image_skin(self, name: str, image_path, default: bool = False,
                            order: int = 100):
        self._extra_skins = [s for s in self._extra_skins if s["name"] != name]
        self._extra_skins.append({"name": str(name), "path": str(image_path),
                                  "order": order})
        names = self._skin_names()
        if self._skin_pref in names:
            self.set_skin_name(self._skin_pref)
        elif default:
            self.set_skin_name(str(name))
        else:
            self._draw()

    def refresh_skins(self):
        self._photo = None
        self._draw()

    def set_skin_name(self, name: str) -> bool:
        names = self._skin_names()
        if name not in names:
            return False
        self._skin = names.index(name)
        self._skin_pref = name
        self._draw()
        self._save_position()
        return True

    def set_click_action(self, callback):
        self._click_action = callback

    # ---------- 功能 ----------
    def _save_position(self):
        names = self._skin_names()
        try:
            _save_settings({"floating_ball": {
                "x": self.win.winfo_x(), "y": self.win.winfo_y(),
                "skin": self._skin,
                "skin_name": names[self._skin] if names else "",
                "hidden": self._hidden}})
        except tk.TclError:
            pass

    def hide(self):
        """隐藏悬浮球：窗口收起，进程继续常驻，等主界面「显示悬浮球」唤回。"""
        if self._hidden:
            return
        self._hidden = True
        try:
            # 丢弃之前遗留的显示请求，避免刚隐藏就被它弹回来
            import ball_bridge
            ball_bridge.take_show_ball_request()
        except Exception:
            pass
        self._save_position()
        try:
            self.win.withdraw()
        except tk.TclError:
            pass
        self._watch_show_request()

    def show(self):
        if not self._hidden:
            return
        self._hidden = False
        self._save_position()
        try:
            self.win.deiconify()
            self._pin_topmost()
            self.win.lift()
        except tk.TclError:
            pass

    def _watch_show_request(self):
        """隐藏期间每秒看一次主界面有没有发来显示请求。"""
        if not self._hidden:
            return
        try:
            import ball_bridge
            if ball_bridge.take_show_ball_request():
                self.show()
                return
        except Exception:
            pass
        try:
            self.root.after(1000, self._watch_show_request)
        except tk.TclError:
            pass

    def set_skin(self, index: int):
        items = self._skin_items()
        if not items:
            return
        self._skin = index % len(items)
        self._skin_pref = items[self._skin]["name"]
        self._draw()
        self._save_position()       # 换肤时连同位置一起保存，不再丢坐标

    def open_score(self, readonly: bool = False):
        """打开学生积分：主界面在运行时交给它打开，避免两个进程同时改同一份数据。"""
        try:
            import ball_bridge
            if ball_bridge.request_open_score(readonly):
                return
        except Exception:
            pass

        win = getattr(self.root, "_score_window", None)
        if win is not None and win.winfo_exists():
            if readonly or getattr(win, "_readonly", False) == readonly:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
            win.destroy()                 # 只读 → 编辑，需要重新校验密钥
            self.root._score_window = None

        if not readonly:
            from ui import AskPasswordDialog
            if not AskPasswordDialog(self.win, "进入学生积分需要密钥").result:
                return

        from student_score import StudentScoreWindow
        ctrl = StudentScoreWindow(self.win, readonly=readonly)
        ctrl.win._controller = ctrl
        self.root._score_window = ctrl.win

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # ---------- Win32 置顶 ----------
    def _pin_topmost(self):
        if os.name != "nt":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            HWND_TOPMOST = -1
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            # 不显示在 Alt+Tab 列表里，更像桌面挂件
            GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x00000080
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
        except Exception:
            pass
