"""PyInstaller 启动器：真正的业务代码放在 exe 同目录的 app/ 下。

这样打包后 exe 只携带 Python 运行时（tkinter 等），业务代码以独立 .py 文件
存在，补丁可以按文件替换，无需重新打包整个程序。
"""
import importlib
import os
import sys


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _prepare() -> str:
    base = _base_dir()
    app_dir = os.path.join(base, "app")
    if os.path.isdir(app_dir) and app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    _redirect_stdio(base)
    try:
        os.chdir(base)
    except OSError:
        pass
    return base


def _redirect_stdio(base: str):
    """窗口模式没有控制台，把 print 输出重定向到 logs/app.log，避免报错。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    try:
        log_dir = os.path.join(base, "logs")
        os.makedirs(log_dir, exist_ok=True)
        stream = open(os.path.join(log_dir, "app.log"), "a",
                      encoding="utf-8", buffering=1)
    except OSError:
        pass
    if stream is None:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main():
    _prepare()
    importlib.import_module("main").main()


if __name__ == "__main__":
    main()
