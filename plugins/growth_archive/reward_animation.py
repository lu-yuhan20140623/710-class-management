"""加分大屏奖励动画。

独立的全屏置顶窗口，与倒计时窗口互不干扰；连续加分时自动排队，
播完一条再播下一条，中途关闭不影响积分数据。
"""

import math
import threading
import time
import tkinter as tk

DURATION = 2600          # 单条动画时长（毫秒）
FPS = 30
GOLD = "#ffd54f"
ACCENT = "#7ab8ff"
TEXT = "#f5f7ff"
BG = "#101426"

# 队列与「当前正在播」都挂在 Tk 根窗口上：插件模块即使被重复加载成两份，
# 也共用同一份状态，不会再出现两拨动画同时叠在大屏上。
_QUEUE_ATTR = "_reward_queue"
_ACTIVE_ATTR = "_reward_active"
_LOCK = threading.RLock()


def show_rewards(root: tk.Tk, items: list):
    """items: [(姓名, 分值, 理由)]，加分时调用。"""
    if root is None or not items:
        return
    if threading.current_thread() is not threading.main_thread():
        # Tk 只能在主线程操作：跨线程直接建窗会留下关不掉的残影窗口
        try:
            root.after(0, lambda: show_rewards(root, items))
        except tk.TclError:
            pass
        return
    with _LOCK:
        queue = getattr(root, _QUEUE_ATTR, None)
        if queue is None:
            queue = []
            setattr(root, _QUEUE_ATTR, queue)
        # 同一事件被重复派发（插件模块双份加载等）时只保留一条，避免叠播
        now = time.time()
        last = getattr(root, "_reward_last", None) or (None, 0.0)
        for item in items:
            key = tuple(item)
            if key == last[0] and now - last[1] < 1.5:
                continue
            queue.append(item)
            last = (key, now)
        setattr(root, "_reward_last", last)
    _next(root)


def _next(root):
    with _LOCK:
        if getattr(root, _ACTIVE_ATTR, None) is not None:
            return
        queue = getattr(root, _QUEUE_ATTR, None) or []
        if not queue:
            return
        name, delta, reason = queue.pop(0)
        # 先占位再建窗：构造过程中若出异常，也不会让后续事件叠一个窗口上来
        setattr(root, _ACTIVE_ATTR, True)
    try:
        burst = RewardBurst(root, name, delta, reason, on_done=lambda: _next(root))
    except Exception:
        setattr(root, _ACTIVE_ATTR, None)
        _next(root)
        return
    setattr(root, _ACTIVE_ATTR, burst)


class RewardBurst:
    def __init__(self, root: tk.Tk, name: str, delta: int, reason: str, on_done):
        self.root = root
        self.on_done = on_done
        self.elapsed = 0
        self.particles = []
        self.closed = False

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        try:
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

            cx, cy = sw // 2, int(sh * 0.42)
            size = max(32, min(sw, sh) // 12)
            # 按实际渲染高度依次往下排，避免字体随 DPI 放大后互相压住
            rows = [
                ("积分奖励", ACCENT, size * 0.42, "bold"),
                (name, TEXT, size * 0.95, "bold"),
                (f"+{delta}", GOLD, size * 1.15, "bold"),
                (reason or "表现优秀", "#c9d4ea", size * 0.38, "normal"),
            ]
            items = []
            for text, color, fs, weight in rows:
                items.append(self.canvas.create_text(
                    cx, 0, text=text, fill=color,
                    font=("Microsoft YaHei UI", max(10, int(fs)), weight)))
            # 姓名过长时先缩字号，避免超出屏幕
            name_item = items[1]
            fs = int(size * 0.95)
            while fs > 14:
                box = self.canvas.bbox(name_item)
                if not box or (box[2] - box[0]) <= sw * 0.88:
                    break
                fs -= 2
                self.canvas.itemconfigure(
                    name_item, font=("Microsoft YaHei UI", fs, "bold"))

            gap = max(8, int(size * 0.22))
            heights = []
            for it in items:
                box = self.canvas.bbox(it)
                heights.append(box[3] - box[1] if box else 0)
            total = sum(heights) + gap * (len(items) - 1)
            y = cy - total // 2
            widths = []
            for it, h in zip(items, heights):
                self.canvas.coords(it, cx, y + h // 2)
                box = self.canvas.bbox(it)
                widths.append(box[2] - box[0] if box else 0)
                y += h + gap

            # 星星从文字块外侧起跑，不压在任何一行字上
            margin = size * 0.25
            start_r = min(min(sw, sh) * 0.44, max(widths) / 2 + margin)
            for i in range(24):
                ang = i * (math.pi * 2 / 24)
                self.particles.append({
                    "angle": ang,
                    "r": start_r,
                    "speed": size * (0.035 + 0.01 * (i % 3)),
                    "item": self.canvas.create_text(cx, cy, text="★", fill=GOLD,
                                                    font=("Microsoft YaHei UI",
                                                          max(10, size // 7), "bold")),
                })
            self.cx, self.cy = cx, cy
            self.win.bind("<Button-1>", lambda e: self.close())
            self.win.focus_force()
        except Exception:
            # 构造失败（窗口已建了一半）必须销毁，否则会留一张关不掉的全屏残影
            try:
                self.win.destroy()
            except Exception:
                pass
            raise
        self._tick()

    def _tick(self):
        if self.closed:
            return
        self.elapsed += int(1000 / FPS)
        p = min(1.0, self.elapsed / DURATION)
        try:
            self.win.attributes("-alpha", min(1.0, p * 6) if p < 0.85 else max(0.0, (1 - p) * 6.7))
        except tk.TclError:
            self.closed = True
            return
        for part in self.particles:
            part["r"] += part["speed"]
            x = self.cx + part["r"] * math.cos(part["angle"])
            y = self.cy + part["r"] * math.sin(part["angle"] * 1.0) * 0.8
            try:
                self.canvas.coords(part["item"], x, y)
            except tk.TclError:
                self.closed = True
                return
        if p >= 1.0:
            self.close()
            return
        try:
            self.win.after(int(1000 / FPS), self._tick)
        except tk.TclError:
            self.closed = True

    def close(self):
        if getattr(self.root, _ACTIVE_ATTR, None) is not self:
            return
        self.closed = True
        setattr(self.root, _ACTIVE_ATTR, None)
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_done()
