"""成长档案插件。

- 主界面「更多功能」提供入口
- 订阅 points_added 事件：写入永久档案，加分时播放大屏奖励动画
"""

NAME = "成长档案"
VERSION = "1.0.0"
DESCRIPTION = "积分榜单、奖励记录、成长趋势、岗位履职、德育台账导出"

PLUGIN = {
    "id": "growth_archive",
    "name": NAME,
    "version": VERSION,
    "description": DESCRIPTION,
    "api_version": 1,
    "priority": 50,
}

_ctx = None


def register(ctx):
    global _ctx
    _ctx = ctx
    ctx.ui.add_main_menu("🏆  成长档案（榜单 / 台账）", open_window, order=50)
    ctx.events.on("points_added", _on_points_added)


def _root():
    root = getattr(_ctx, "app", None)
    if root is None:
        import tkinter as tk
        root = tk._default_root
    return root


def open_window():
    from .window import GrowthArchiveWindow

    root = _root()
    if root is None:
        return
    return GrowthArchiveWindow(root, host=getattr(_ctx, "host", None))


def _on_points_added(payload=None):
    from . import store

    payload = payload if isinstance(payload, dict) else {}
    cls = payload.get("cls") or payload.get("class") or ""
    sids = payload.get("sids") or []
    delta = int(payload.get("delta") or 0)
    reason = payload.get("reason") or ""
    store.record_points(cls, sids, delta, reason)
    if delta <= 0:
        return
    root = _root()
    if root is None:
        return
    students = store.students_brief(cls)
    name_map = {sid: name for sid, name, _ in students}
    names = [name_map.get(sid, str(sid)) for sid in sids]
    if not names:
        return
    label = "、".join(names) if len(names) <= 4 else f"{'、'.join(names[:4])} 等 {len(names)} 人"
    from . import reward_animation
    reward_animation.show_rewards(root, [(label, delta, reason)])
