"""加分大屏奖励动画。

独立的全屏置顶窗口，与倒计时窗口互不干扰；连续加分时自动排队，
播完一条再播下一条，中途关闭不影响积分数据。
"""

import math
import tkinter as tk

DURATION = 2600          # 单条动画时长（毫秒）
FPS = 30
GOLD = "#ffd54f"
ACCENT = "#7ab8ff"
TEXT = "#f5f7ff"
BG = "#101426"

_queue: list = []
_active = None


def show_rewards(root: tk.Tk, items: list):
    """items: [(姓名, 分值, 理由)]，加分时调用。"""
    _queue.extend(items)
    _next(root)


def _next(root):
    global _active
    if _active is not None or not _queue:
        return
    name, delta, reason = _queue.pop(0)
    _active = RewardBurst(root, name, delta, reason, on_done=lambda: _next(root))


class RewardBurst:
    def __init__(self, root: tk.Tk, name: str, delta: int, reason: str, on_done):
        self.root = root
        self.on_done = on_done
        self.elapsed = 0
        self.particles = []

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{sw}x{sh}+0+0")
        self.win.configure(bg=BG)
        try:
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(self.win, width=sw, height=sh, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        cx, cy = sw // 2, int(sh * 0.40)
        size = max(32, min(sw, sh) // 10)
        self.canvas.create_text(cx, cy - size * 1.5, text="积分奖励",
                                fill=ACCENT,
                                font=("Microsoft YaHei UI", int(size * 0.5), "bold"))
        self.canvas.create_text(cx, cy + size * 0.35, text=name, fill=TEXT,
                                font=("Microsoft YaHei UI", int(size * 1.1), "bold"))
        self.canvas.create_text(cx, cy + size * 1.35, text=f"+{delta}",
                                fill=GOLD,
                                font=("Microsoft YaHei UI", int(size * 1.5), "bold"))
        self.canvas.create_text(cx, cy + size * 2.35, text=reason or "表现优秀",
                                fill="#c9d4ea",
                                font=("Microsoft YaHei UI", int(size * 0.42)))

        # 放射线 + 星星粒子
        for i in range(24):
            ang = i * (math.pi * 2 / 24)
            self.particles.append({
                "angle": ang,
                "r": size * 0.4,
                "speed": size * (0.035 + 0.01 * (i % 3)),
                "item": self.canvas.create_text(cx, cy, text="★", fill=GOLD,
                                                font=("Microsoft YaHei UI",
                                                      max(10, size // 6), "bold")),
            })
        self.cx, self.cy = cx, cy
        self.win.bind("<Button-1>", lambda e: self.close())
        self.win.focus_force()
        self._tick()

    def _tick(self):
        self.elapsed += int(1000 / FPS)
        p = min(1.0, self.elapsed / DURATION)
        try:
            self.win.attributes("-alpha", min(1.0, p * 6) if p < 0.85 else max(0.0, (1 - p) * 6.7))
        except tk.TclError:
            pass
        for part in self.particles:
            part["r"] += part["speed"]
            x = self.cx + part["r"] * math.cos(part["angle"])
            y = self.cy + part["r"] * math.sin(part["angle"] * 1.0) * 0.8
            self.canvas.coords(part["item"], x, y)
        if p >= 1.0:
            self.close()
            return
        self.win.after(int(1000 / FPS), self._tick)

    def close(self):
        global _active
        if _active is not self:
            return
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        _active = None
        self.on_done()
