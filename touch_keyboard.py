"""触摸屏幕键盘：输入框获得焦点时尝试启动 Windows 屏幕键盘 osk.exe。

- install_global() 在程序启动时调用一次，全局给 tk/ttk 的输入控件绑定；
- bind_touch_keyboard(widget) 可对单个控件显式绑定。
"""
from __future__ import annotations

import sys

_installed = False


def show_touch_keyboard(_event=None):
    """每次聚焦都尝试拉起 osk.exe；已在运行时系统会激活已有实例，失败静默。"""
    if sys.platform != "win32":
        return
    try:
        import subprocess
        subprocess.Popen(["osk.exe"])
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
    """全局注入：所有 Tk/Ttk 输入控件创建时自动绑定软键盘，只需调用一次。"""
    global _installed
    if _installed:
        return
    _installed = True
    if sys.platform != "win32":
        return
    try:
        import tkinter as tk
        from tkinter import ttk
        for cls in (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox):
            original = cls.__init__

            def patched(self, *args, _original=original, **kwargs):
                _original(self, *args, **kwargs)
                bind_touch_keyboard(self)

            cls.__init__ = patched
    except Exception:
        pass
