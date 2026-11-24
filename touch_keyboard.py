"""触摸屏幕键盘：在没有物理键盘的 Windows 设备上，输入框获得焦点时启动 osk.exe。

- install_global() 在程序启动时调用一次，全局给所有 tk.Entry / tk.Text 绑定；
- bind_touch_keyboard(widget) 可对单个控件显式绑定。
"""
from __future__ import annotations

import sys

_checked = False
_needed = False
_installed = False


def _need_touch_keyboard() -> bool:
    global _checked, _needed
    if _checked:
        return _needed
    _checked = True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # 触摸设备、无物理键盘、或平板模式，任一成立即弹出软键盘
        touch_capable = bool(user32.GetSystemMetrics(94))       # SM_DIGITIZER
        no_keyboard = user32.GetKeyboardType(0) == 0
        slate_mode = user32.GetSystemMetrics(0x2003) == 0       # SM_CONVERTIBLESLATEMODE
        _needed = touch_capable or no_keyboard or slate_mode
    except Exception:
        _needed = False
    return _needed


def show_touch_keyboard(_event=None):
    """在输入框聚焦时触发；检测失败时直接忽略，不影响输入。"""
    if not _need_touch_keyboard():
        return
    try:
        import subprocess
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["osk.exe"], creationflags=flags)
    except Exception:
        pass


def bind_touch_keyboard(widget):
    """给输入框绑定 FocusIn 自动弹出屏幕键盘，返回原 widget 便于链式调用。"""
    try:
        widget.bind("<FocusIn>", show_touch_keyboard, add="+")
    except Exception:
        pass
    return widget


def install_global():
    """全局注入：所有 Tk Entry/Text 创建时自动绑定软键盘，只需调用一次。"""
    global _installed
    if _installed:
        return
    _installed = True
    if sys.platform != "win32":
        return
    try:
        import tkinter as tk
        for cls in (tk.Entry, tk.Text):
            original = cls.__init__

            def patched(self, *args, _original=original, **kwargs):
                _original(self, *args, **kwargs)
                bind_touch_keyboard(self)

            cls.__init__ = patched
    except Exception:
        pass
