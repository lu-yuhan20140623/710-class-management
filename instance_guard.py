"""单实例守卫：用 Windows 命名互斥体阻止同一角色启动多个进程。

互斥体句柄保存在模块级字典里，进程存活期间一直持有，进程退出后由系统释放。
"""

import ctypes
import sys

_ERROR_ALREADY_EXISTS = 183
_handles = {}


def _kernel32():
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    return k32


def acquire(role: str) -> bool:
    """获取命名互斥体；已有同类实例在运行时返回 False。"""
    if not sys.platform.startswith("win"):
        return True
    try:
        k32 = _kernel32()
        handle = k32.CreateMutexW(None, False, f"Local\\ClassSchedule_{role}")
        if not handle:
            return True
        if k32.GetLastError() == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle(handle)
            return False
        _handles[role] = handle
        return True
    except Exception:
        return True


def activate_window(title: str) -> bool:
    """把已存在的主窗口恢复到前台。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)      # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
