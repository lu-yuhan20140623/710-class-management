"""单实例守卫：用 Windows 命名互斥体阻止同一角色启动多个进程。

互斥体句柄保存在模块级字典里，进程存活期间一直持有，进程退出后由系统释放。
activate_all_windows() 在检测到已有实例时枚举并恢复全部属于本程序的顶层窗口，
避免「显示桌面」后只恢复一个窗口、其余报表/统计图仍是最小化状态。
"""

import ctypes
import sys

# Windows 类型别名：直接使用 ctypes 内置类型，不依赖 ctypes.wintypes 子模块
# （部分 onedir 打包环境未收集该子模块，from ctypes import wintypes 会启动即崩溃）
_HWND = ctypes.c_void_p
_BOOL = ctypes.c_int
_LPARAM = ctypes.c_ssize_t

_ERROR_ALREADY_EXISTS = 183
_handles = {}

# 本程序所有窗口标题都含这些关键字（主界面 / 身份选择 / 报表 / 统计图 / 积分等）
_WINDOW_KEYWORDS = ("课程表", "积分", "卫生", "统计图", "身份")


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


def _window_title(hwnd) -> str:
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if not n:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def activate_window(title: str = "") -> bool:
    """恢复并激活已有实例的顶层窗口。

    优先按给定标题精确查找；找不到时枚举所有顶层窗口，恢复标题包含程序关键字
    的窗口（主界面、报表、统计图、积分窗口等），解决显示桌面后只恢复一个的问题。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = _HWND
        user32.ShowWindow.argtypes = [_HWND, ctypes.c_int]
        user32.IsIconic.argtypes = [_HWND]
        user32.GetWindowTextW.argtypes = [_HWND, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextLengthW.argtypes = [_HWND]

        found = []
        if title:
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                found.append(hwnd)
        if not found:
            WNDENUMPROC = ctypes.WINFUNCTYPE(_BOOL, _HWND, _LPARAM)

            def _collect(hwnd, _lparam):
                t = _window_title(hwnd)
                if t and any(k in t for k in _WINDOW_KEYWORDS):
                    found.append(hwnd)
                return True

            user32.EnumWindows(WNDENUMPROC(_collect), 0)

        if not found:
            return False
        restored = False
        for hwnd in found:
            if user32.IsIconic(hwnd):                 # 最小化才恢复，避免把正常窗口又置前
                user32.ShowWindow(hwnd, 9)            # SW_RESTORE
                restored = True
            else:
                user32.ShowWindow(hwnd, 5)            # SW_SHOW
        if found:
            try:
                user32.SetForegroundWindow(found[0])
            except Exception:
                pass
        return True
    except Exception:
        return False


def activate_all_windows() -> bool:
    """兼容旧调用：恢复本程序全部顶层窗口。"""
    return activate_window("")
