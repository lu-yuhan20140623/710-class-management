"""成长档案用的轻量图表（纯 Canvas，无第三方依赖）。"""

import tkinter as tk

BG = "#1e1e2e"
GRID = "#3a3a4a"
TEXT = "#e8e8f0"
DIM = "#9090a0"
ACCENT = "#7ab8ff"
GOLD = "#ffd54f"
GREEN = "#66cc88"
RED = "#ff6b6b"

PALETTE = [ACCENT, GREEN, GOLD, "#b07bff", "#4dd0e1", "#ff8a65", "#9ccc65", "#f06292"]


def _font(size=10, bold=False):
    return ("Microsoft YaHei UI", size, "bold") if bold else ("Microsoft YaHei UI", size)


def bar_chart(canvas: tk.Canvas, rows: list, title: str = "", horizontal=True):
    """rows: [(标签, 数值)]，数值可为负；横向条形图更易读长名单。"""
    canvas.delete("all")
    w = max(canvas.winfo_width(), 200)
    h = max(canvas.winfo_height(), 160)
    if title:
        canvas.create_text(w / 2, 16, text=title, fill=TEXT, font=_font(11, True))
    if not rows:
        canvas.create_text(w / 2, h / 2, text="暂无数据", fill=DIM, font=_font(10))
        return

    rows = rows[:18]
    top, bottom, left, right = (38 if title else 12), 24, 96, 60
    if horizontal:
        plot_h = h - top - bottom
        step = plot_h / max(1, len(rows))
        bar_h = max(10, step * 0.62)
        max_abs = max(abs(v) for _, v in rows) or 1
        zero_x = left + (w - left - right) / 2
        canvas.create_line(zero_x, top - 4, zero_x, h - bottom + 4, fill=GRID)
        for i, (label, value) in enumerate(rows):
            y = top + step * i + step / 2
            length = abs(value) / max_abs * ((w - left - right) / 2 - 4)
            x0, x1 = (zero_x, zero_x + length) if value >= 0 else (zero_x - length, zero_x)
            color = GREEN if value >= 0 else RED
            canvas.create_rectangle(x0, y - bar_h / 2, x1, y + bar_h / 2,
                                    fill=color, outline="")
            canvas.create_text(left - 8, y, text=str(label), anchor="e",
                               fill=TEXT, font=_font(9))
            tx = x1 + 6 if value >= 0 else x0 - 6
            canvas.create_text(tx, y, text=str(value), anchor="w" if value >= 0 else "e",
                               fill=TEXT, font=_font(9, True))
    else:
        plot_w = w - left - right
        step = plot_w / max(1, len(rows))
        max_v = max(v for _, v in rows) or 1
        min_v = min(0, min(v for _, v in rows))
        span = max_v - min_v or 1
        base_y = h - bottom
        for i, (label, value) in enumerate(rows):
            x = left + step * i + step / 2
            bh = (value - min_v) / span * (h - top - bottom)
            canvas.create_rectangle(x - step * 0.28, base_y - bh,
                                    x + step * 0.28, base_y,
                                    fill=ACCENT if value >= 0 else RED, outline="")
            canvas.create_text(x, base_y + 12, text=str(label), fill=DIM, font=_font(8))
            canvas.create_text(x, base_y - bh - 10, text=str(value), fill=TEXT, font=_font(9, True))


def line_chart(canvas: tk.Canvas, series: dict, title: str = ""):
    """series: {名称: [(日期, 累计值)]}，用于学生成长曲线。"""
    canvas.delete("all")
    w = max(canvas.winfo_width(), 240)
    h = max(canvas.winfo_height(), 180)
    if title:
        canvas.create_text(w / 2, 16, text=title, fill=TEXT, font=_font(11, True))
    if not series:
        canvas.create_text(w / 2, h / 2, text="暂无数据", fill=DIM, font=_font(10))
        return

    left, right, top, bottom = 52, 130, 34, 34
    all_points = [p for pts in series.values() for p in pts]
    xs = sorted({p[0] for p in all_points})
    ys = [p[1] for p in all_points]
    min_v, max_v = min(ys), max(ys)
    if max_v == min_v:
        max_v = min_v + 1
    plot_w, plot_h = w - left - right, h - top - bottom

    def px(i):
        return left + (plot_w * i / max(1, len(xs) - 1))

    def py(v):
        return top + plot_h - (v - min_v) / (max_v - min_v) * plot_h

    # 网格与坐标
    for i in range(5):
        y = top + plot_h * i / 4
        canvas.create_line(left, y, left + plot_w, y, fill=GRID, dash=(2, 4))
        value = max_v - (max_v - min_v) * i / 4
        canvas.create_text(left - 6, y, text=f"{value:.0f}", anchor="e",
                           fill=DIM, font=_font(8))
    for i, day in enumerate(xs):
        if len(xs) <= 8 or i % max(1, len(xs) // 6) == 0:
            canvas.create_text(px(i), h - bottom + 12, text=day[5:], fill=DIM, font=_font(8))

    for idx, (name, pts) in enumerate(series.items()):
        color = PALETTE[idx % len(PALETTE)]
        points = []
        for day, value in pts:
            i = xs.index(day)
            points.extend((px(i), py(value)))
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=2, smooth=True)
        for x, y in zip(points[::2], points[1::2]):
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
        # 图例
        ly = top + 6 + idx * 18
        canvas.create_line(w - right + 6, ly, w - right + 26, ly, fill=color, width=2)
        canvas.create_text(w - right + 30, ly, text=name, anchor="w", fill=TEXT, font=_font(8))
