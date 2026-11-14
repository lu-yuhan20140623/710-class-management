"""极简事件总线。

业务代码（如 score_records）只负责 emit，插件负责 on 订阅，
双方互不依赖；订阅方抛异常不会影响发事件的一方。
"""

from collections import defaultdict

_handlers = defaultdict(list)


def on(event: str, handler):
    """订阅事件，返回 handler 方便链式使用。"""
    if handler not in _handlers[event]:
        _handlers[event].append(handler)
    return handler


def off(event: str, handler):
    try:
        _handlers[event].remove(handler)
    except (KeyError, ValueError):
        pass


def emit(event: str, **payload) -> list:
    """广播事件；逐个捕获异常，避免一个插件出错拖垮其他插件。"""
    results = []
    for handler in list(_handlers.get(event, [])):
        try:
            results.append(handler(**payload))
        except Exception:
            import traceback
            traceback.print_exc()
    return results


def clear():
    _handlers.clear()
