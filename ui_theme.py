"""Tkinter 主题与 DPI 工具：配色常量、高 DPI 适配、窗口尺寸计算、ttk 暗色主题。"""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# ---------- 颜色主题 ----------
BG_MAIN      = "#1e1e2e"
BG_PANEL     = "#2a2a3a"
BG_CELL      = "#3a3a4a"
BG_CELL_ALT  = "#444458"
BG_IN_CLASS  = "#3b6b3b"
BG_COUNTING  = "#8b5a2b"
BG_PREBELL   = "#b5651d"
BG_DANGER    = "#4a1e1e"
FG_TEXT      = "#e8e8f0"
FG_DIM       = "#9090a0"
FG_ACCENT    = "#7ab8ff"
FG_WARN      = "#ffcc66"
FG_PREBELL   = "#ffe0b3"   # 预备铃提示文字（配 BG_PREBELL 深橙底）
FG_DANGER    = "#ff6b6b"
FG_OK        = "#66cc88"   # 成功/已自定义密码用
FG_SUBJECT   = "#66cc88"   # 课程标题/上课中用（绿色）


def enable_high_dpi(root: tk.Tk | None = None):
    """高 DPI 适配：否则 2K/4K 屏幕上字体和控件会被系统拉伸导致发虚。

    - 必须在创建任何窗口之前调用（进程级设置）
    - 传入 root 后再按实际 DPI 调整 tk 缩放比例
    """
    if os.name == "nt":
        try:
            import ctypes
            # 1 = SYSTEM_DPI_AWARE，对 tkinter 最稳妥（2 逐显示器模式会错乱布局）
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    if root is not None:
        try:
            root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass


def work_area(root):
    """屏幕可用区域（left, top, right, bottom），已排除任务栏。"""
    if os.name == "nt":
        try:
            import ctypes
            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            rect = _RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x0030, 0, ctypes.byref(rect), 0):
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def dpi_scale(root) -> float:
    """当前 DPI 相对 96 的缩放比（高分屏下返回 1.25 / 1.5 / 2.0 等）。"""
    try:
        return max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        return 1.0


def fit_geometry(root, width, height, min_width=0, min_height=0):
    """按 DPI 放大窗口、钳制到可用区域，并居中显示（不再跑到屏幕外）。"""
    k = dpi_scale(root)
    wl, wt, wr, wb = work_area(root)
    aw, ah = wr - wl, wb - wt
    w = min(int(width * k), int(aw * 0.95))
    h = min(int(height * k), int(ah * 0.92))
    mw = min(int(min_width * k), w) if min_width else w
    mh = min(int(min_height * k), h) if min_height else h
    x = wl + (aw - w) // 2
    y = wt + (ah - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(mw, mh)


def center_window(win: tk.Toplevel, parent, width: int, height: int, auto: bool = True):
    """把弹窗居中到父窗口，并按内容实际需要的最小尺寸放大（避免高 DPI 下裁切）。"""
    try:
        win.update_idletasks()
        if auto:
            width = max(width, win.winfo_reqwidth())
            height = max(height, win.winfo_reqheight())
    except Exception:
        pass
    # 尺寸也不能超过可用区域，否则小屏上按钮照样会被裁掉
    wl, wt, wr, wb = work_area(win)
    width = min(width, int((wr - wl) * 0.98))
    height = min(height, int((wb - wt) * 0.96))
    try:
        parent.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        x = px + (pw - width) // 2
        y = py + (ph - height) // 2
    except Exception:
        x = (win.winfo_screenwidth() - width) // 2
        y = (win.winfo_screenheight() - height) // 2
    # 钳制到可用区域，避免主窗口贴边时弹窗跑到屏幕外
    x = max(wl, min(x, wr - width))
    y = max(wt, min(y, wb - height))
    win.geometry(f"{width}x{height}+{x}+{y}")


# ttk 主题适配暗色
def _apply_ttk_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TNotebook", background=BG_MAIN, borderwidth=0)
    style.configure("TNotebook.Tab",
                    background=BG_PANEL, foreground=FG_DIM,
                    padding=(14, 6), font=("Microsoft YaHei UI", 10))
    style.map("TNotebook.Tab",
              background=[("selected", BG_CELL)],
              foreground=[("selected", FG_ACCENT)])
    # 表格行高按实际字体高度算，高分屏下文字不会被上下裁掉
    try:
        _line = tkfont.Font(root=root, family="Microsoft YaHei UI",
                            size=10).metrics("linespace")
    except Exception:
        _line = 20
    style.configure("Treeview",
                    background=BG_CELL, foreground=FG_TEXT,
                    fieldbackground=BG_CELL, rowheight=_line + 8,
                    font=("Microsoft YaHei UI", 10))
    style.configure("Treeview.Heading",
                    background=BG_PANEL, foreground=FG_ACCENT,
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.map("Treeview", background=[("selected", "#2f5f8f")],
              foreground=[("selected", FG_TEXT)])
    style.map("Treeview.Heading",
              background=[("active", BG_CELL_ALT)],
              foreground=[("active", FG_ACCENT)])
    # 下拉框 / 滚动条暗色适配（学生积分模块使用）
    style.configure("TCombobox",
                    fieldbackground=BG_CELL, background=BG_PANEL,
                    foreground=FG_TEXT, arrowcolor=FG_DIM,
                    bordercolor=BG_CELL, lightcolor=BG_CELL, darkcolor=BG_CELL,
                    insertcolor=FG_TEXT)
    style.map("TCombobox",
              fieldbackground=[("readonly", BG_CELL)],
              foreground=[("readonly", FG_TEXT)],
              background=[("readonly", BG_CELL), ("active", BG_CELL_ALT)],
              selectbackground=[("readonly", BG_CELL)],
              selectforeground=[("readonly", FG_TEXT)])
    style.configure("Vertical.TScrollbar",
                    background=BG_CELL, troughcolor=BG_PANEL,
                    bordercolor=BG_PANEL, arrowcolor=FG_DIM)
    root.option_add("*TCombobox*Listbox.background", BG_CELL)
    root.option_add("*TCombobox*Listbox.foreground", FG_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", BG_IN_CLASS)
    root.option_add("*TCombobox*Listbox.selectForeground", FG_TEXT)
