"""
纯 tkinter Canvas 统计图表：饼图 / 双向条形图
- 不依赖 matplotlib：避免额外依赖与 PyInstaller 打包钩子，界面随窗口即时绘制
- 配色与 ui.py 深色主题一致
"""

import tkinter as tk
import tkinter.font as tkfont

from ui import dpi_scale

BG_PANEL = "#2a2a3a"
FG_TEXT = "#e8e8f0"
FG_DIM = "#9090a0"
FG_OK = "#66cc88"
FG_DANGER = "#ff6b6b"
FONT = "Microsoft YaHei UI"

# 扇区 / 图例配色（12 色循环）
PALETTE = [
    "#7ab8ff", "#66cc88", "#ffcc66", "#ff8f6b", "#c792ea", "#4dd0e1",
    "#f06292", "#aed581", "#ffd54f", "#9575cd", "#4db6ac", "#e57373",
]


def _short(text: str, n: int = 8) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _empty(parent, text="暂无数据"):
    return tk.Label(parent, text=text, font=(FONT, 11), bg=BG_PANEL, fg=FG_DIM)


def pie_chart(parent, data, size=300, max_items=12):
    """饼图：data = [(理由, 次数), ...]；返回包含饼图 + 图例的 Frame。"""
    frame = tk.Frame(parent, bg=BG_PANEL)
    # 画布是固定像素坐标，必须按 DPI 放大，否则高 DPI 下字体变大、圆盘不变
    scale = dpi_scale(frame)
    size = int(size * scale)
    items = [(str(k), float(v)) for k, v in data if v]
    if not items:
        _empty(frame).pack(padx=20, pady=20)
        return frame

    # 超过 max_items 时把尾部合并为「其他」，避免图例撑爆窗口
    if len(items) > max_items:
        head, tail = items[: max_items - 1], items[max_items - 1:]
        items = head + [("其他", sum(v for _, v in tail))]
    total = sum(v for _, v in items) or 1

    left = tk.Frame(frame, bg=BG_PANEL)
    left.pack(side=tk.LEFT, padx=(10, 0), pady=10)
    canvas = tk.Canvas(left, width=size, height=size, bg=BG_PANEL,
                       highlightthickness=0, bd=0)
    canvas.pack()

    # 从 12 点方向顺时针绘制
    inset = max(2, int(8 * scale))
    start = 90.0
    if len(items) == 1:
        # 只有一类时角度是 360°，Tk 的 create_arc 画不出整圆，改用椭圆
        canvas.create_oval(inset, inset, size - inset, size - inset,
                           fill=PALETTE[0], outline=BG_PANEL, width=2)
    else:
        for i, (_label, val) in enumerate(items):
            extent = -360.0 * val / total
            canvas.create_arc(inset, inset, size - inset, size - inset,
                              start=start, extent=extent,
                              fill=PALETTE[i % len(PALETTE)], outline=BG_PANEL,
                              width=2)
            start += extent

    legend = tk.Frame(frame, bg=BG_PANEL)
    legend.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                padx=14, pady=10, anchor="n")
    for i, (label, val) in enumerate(items):
        row = tk.Frame(legend, bg=BG_PANEL)
        row.pack(fill=tk.X, pady=2)
        sw_size = max(6, int(12 * scale))
        sw = tk.Frame(row, bg=PALETTE[i % len(PALETTE)], width=sw_size, height=sw_size)
        sw.pack(side=tk.LEFT, padx=(0, 8))
        sw.pack_propagate(False)
        pct = 100.0 * val / total
        tk.Label(row, text=f"{label}  {pct:.1f}%  ({int(val)})",
                 font=(FONT, 10), bg=BG_PANEL, fg=FG_TEXT,
                 anchor="w").pack(side=tk.LEFT)
    return frame


def bar_chart(parent, rows, width=700, name_col=130):
    """双向条形图：rows = [(名称, 加分, 扣分), ...]。

    加分向右（绿），扣分向左（红），0 轴按数据比例居中。
    """
    frame = tk.Frame(parent, bg=BG_PANEL)
    rows = [(str(n), max(0.0, float(a)), max(0.0, float(b))) for n, a, b in rows]
    if not rows:
        _empty(frame).pack(padx=20, pady=20)
        return frame

    # 画布坐标是固定像素，全部按 DPI 放大；字体用 pt 由 tk 自动缩放，不能再乘
    scale = dpi_scale(frame)
    width = int(width * scale)
    name_col = int(name_col * scale)
    row_h = max(1, int(34 * scale))
    top = int(40 * scale)      # 顶部留出图例的高度
    bottom = int(26 * scale)   # 底部留出 0 轴标签的位置
    height = top + row_h * len(rows) + bottom

    canvas = tk.Canvas(frame, width=width, height=height, bg=BG_PANEL,
                       highlightthickness=0, bd=0)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    max_add = max(a for _, a, _ in rows) or 1
    max_sub = max(b for _, _, b in rows) or 1
    plot_l = name_col
    plot_r = width - int(80 * scale)
    scale_px = (plot_r - plot_l) / (max_add + max_sub)
    zero_x = plot_l + max_sub * scale_px

    # 0 轴（标签放在最下方，避免和图例挤在一起）
    canvas.create_line(zero_x, top - int(10 * scale), zero_x, height - bottom,
                       fill=FG_DIM, width=1, dash=(3, 3))
    canvas.create_text(zero_x, height - int(2 * scale), text="0", anchor="s",
                       font=(FONT, 8), fill=FG_DIM)

    # 图例：按实际字体宽度依次排布，避免高 DPI 下文字变宽后互相压住
    lfont = tkfont.Font(family=FONT, size=9)
    lx = int(10 * scale)
    for color, text in ((FG_OK, "加分（右）"), (FG_DANGER, "扣分（左）")):
        canvas.create_rectangle(lx, int(6 * scale), lx + int(12 * scale), int(18 * scale),
                                fill=color, outline="")
        canvas.create_text(lx + int(17 * scale), int(12 * scale), text=text, anchor="w",
                           font=lfont, fill=color)
        lx += int(17 * scale) + lfont.measure(text) + int(18 * scale)

    bar_h = max(2, int(16 * scale))
    row_font = tkfont.Font(family=FONT, size=9)
    name_max_w = name_col - int(24 * scale)      # 名称列可用宽度，超出按像素截断
    for i, (name, add, sub) in enumerate(rows):
        cy = top + i * row_h + row_h / 2
        # 名称（按实际像素宽度截断，避免高 DPI 下压到图形）
        label = _short(name, 8)
        while label and row_font.measure(label) > name_max_w:
            label = label[:-2] + "…" if len(label) > 2 else label[:-1]
        canvas.create_text(name_col - int(12 * scale), cy, text=label,
                           anchor="e", font=row_font, fill=FG_TEXT)
        if add:
            canvas.create_rectangle(zero_x, cy - bar_h / 2,
                                    zero_x + add * scale_px, cy + bar_h / 2,
                                    fill=FG_OK, outline="")
            canvas.create_text(zero_x + add * scale_px + int(6 * scale), cy,
                               text=f"+{int(add)}", anchor="w",
                               font=(FONT, 9), fill=FG_OK)
        if sub:
            canvas.create_rectangle(zero_x - sub * scale_px, cy - bar_h / 2,
                                    zero_x, cy + bar_h / 2,
                                    fill=FG_DANGER, outline="")
            canvas.create_text(zero_x - sub * scale_px - int(6 * scale), cy,
                               text=f"-{int(sub)}", anchor="e",
                               font=(FONT, 9), fill=FG_DANGER)
    return frame


def deduction_bar(parent, rows, width=700, name_col=140):
    """单向条形图（只统计扣分）：rows = [(名称, 扣分), ...]。

    所有条目都向右延伸（红色），没有加分方向，适合卫生扣分这类纯扣分数据。
    """
    frame = tk.Frame(parent, bg=BG_PANEL)
    rows = [(str(n), abs(float(v))) for n, v in rows]
    if not rows:
        _empty(frame).pack(padx=20, pady=20)
        return frame

    # 画布坐标按 DPI 放大；字体用 pt 交给 tk 自动缩放
    scale = dpi_scale(frame)
    width = int(width * scale)
    name_col = int(name_col * scale)
    row_h = max(1, int(34 * scale))
    top = int(16 * scale)
    bottom = int(26 * scale)
    height = top + row_h * len(rows) + bottom

    canvas = tk.Canvas(frame, width=width, height=height, bg=BG_PANEL,
                       highlightthickness=0, bd=0)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    max_val = max(v for _, v in rows) or 1
    plot_l = name_col
    plot_r = width - int(80 * scale)
    scale_px = (plot_r - plot_l) / max_val

    canvas.create_line(plot_l, top - int(6 * scale), plot_l, height - bottom,
                       fill=FG_DIM, width=1, dash=(3, 3))
    canvas.create_text(plot_l, height - int(2 * scale), text="0", anchor="s",
                       font=(FONT, 8), fill=FG_DIM)

    bar_h = max(2, int(16 * scale))
    row_font = tkfont.Font(family=FONT, size=9)
    name_max_w = name_col - int(24 * scale)
    for i, (name, val) in enumerate(rows):
        cy = top + i * row_h + row_h / 2
        label = _short(name, 8)
        while label and row_font.measure(label) > name_max_w:
            label = label[:-2] + "…" if len(label) > 2 else label[:-1]
        canvas.create_text(name_col - int(12 * scale), cy, text=label,
                           anchor="e", font=row_font, fill=FG_TEXT)
        if val:
            canvas.create_rectangle(plot_l, cy - bar_h / 2,
                                    plot_l + val * scale_px, cy + bar_h / 2,
                                    fill=FG_DANGER, outline="")
            canvas.create_text(plot_l + val * scale_px + int(6 * scale), cy,
                               text=f"-{val:g}", anchor="w",
                               font=row_font, fill=FG_DANGER)
        else:
            canvas.create_text(plot_l + int(6 * scale), cy, text="0",
                               anchor="w", font=row_font, fill=FG_DIM)
    return frame
