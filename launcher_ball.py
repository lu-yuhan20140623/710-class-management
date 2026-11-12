"""PyInstaller 启动器：桌面悬浮球常驻进程（无控制台）。"""
import importlib
import os
import sys


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    base = _base_dir()
    app_dir = os.path.join(base, "app")
    if os.path.isdir(app_dir) and app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    _redirect_stdio(base)
    try:
        os.chdir(base)
    except OSError:
        pass
    importlib.import_module("floating_ball_service").main()


def _redirect_stdio(base: str):
    """无控制台运行，print 重定向到 logs/ball.log。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    try:
        log_dir = os.path.join(base, "logs")
        os.makedirs(log_dir, exist_ok=True)
        stream = open(os.path.join(log_dir, "ball.log"), "a",
                      encoding="utf-8", buffering=1)
    except OSError:
        pass
    if stream is None:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


if __name__ == "__main__":
    main()
