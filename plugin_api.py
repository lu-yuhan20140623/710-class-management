"""
轻量插件框架（与业务代码解耦，可同时加载多个插件）

插件放在 plugins/ 目录，一个文件一个插件，文件里必须提供：

    PLUGIN = {
        "id": "score_center",            # 唯一标识
        "name": "积分分析中心",
        "version": "1.0.0",
        "api_version": 1,                # 兼容的框架版本（<= API_VERSION）
        "description": "...",
        "author": "...",
        "requires": [],                  # 依赖的其他插件 id（按顺序加载）
        "priority": 100,                 # 越小越先注册
    }

    def register(ctx):
        ctx.ui.add_main_menu("积分分析中心", open_center)
        ctx.ui.add_score_menu("积分分析中心", open_center)
        ctx.ball.add_menu("快捷点名", quick_call)
        ctx.ball.register_skin("默认头像", image_path, default=True)
        ctx.events.on("score_changed", on_score_changed)
        ctx.scores.set_parser(parse_decimal)   # 可选：改写分值录入规则

设计要点（保证与别的插件兼容）：
- 每个插件注册时拿到的都是同一个 ctx，各自的异常会被捕获，不会影响其他插件
- 菜单项/按钮按 order 排序合并，不覆盖宿主原有功能
- 数据读写统一走 ctx.data，自动做小组总分同步，避免各插件各写一份
- 每个插件有独立 settings（plugins_data/<id>.json）与日志前缀
- 事件总线解耦：score_changed / class_changed / app_ready / ball_ready
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

API_VERSION = 1

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

# 打包后业务代码在 app/ 下，sys.path 只含 app/ 不含程序根目录，
# 导致 from plugins.role_portal import ... 找不到包；插件通过文件路径加载不受影响。
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

PLUGIN_DIR = APP_DIR / "plugins"
PLUGIN_DATA_DIR = APP_DIR / "plugins_data"
ENABLED_FILE = PLUGIN_DATA_DIR / "enabled.json"
LOG_FILE = APP_DIR / "logs" / "plugins.log"


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"[插件] {msg}")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _load_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    return default


def _save_json(path: Path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        _log(f"写入 {path.name} 失败：{exc}")
        return False


def _load_enabled() -> dict:
    """插件开关：未记录的插件默认启用，保证老插件升级后照常工作。"""
    data = _load_json(ENABLED_FILE, {})
    return data if isinstance(data, dict) else {}


def _store_enabled(plugin_id: str, enabled: bool) -> bool:
    data = _load_enabled()
    data[str(plugin_id)] = bool(enabled)
    return _save_json(ENABLED_FILE, data)


# ===================== 分值解析（插件可覆盖） =====================
def _parse_int_score(text: str):
    try:
        return int(str(text).strip()), ""
    except (TypeError, ValueError):
        return None, "分值必须是整数（正数加分，负数扣分）"


class ScoreBridge:
    """默认只允许整数；插件可注册自己的解析器（例如支持小数）。"""

    def __init__(self, manager):
        self.manager = manager
        self._parsers: list[dict] = []
        self._hints: list[dict] = []

    def set_parser(self, parser, order: int = 100, owner: str | None = None):
        if not callable(parser):
            raise TypeError("分值解析器必须是可调用对象")
        self._parsers = [p for p in self._parsers if p["owner"] != owner]
        self._parsers.append({"parser": parser, "order": order, "owner": owner})
        self._parsers.sort(key=lambda p: (p["order"], p["owner"] or ""))

    def set_hint(self, text: str, owner: str | None = None):
        self._hints = [h for h in self._hints if h["owner"] != owner]
        self._hints.append({"text": str(text), "owner": owner})

    def parse(self, text) -> tuple:
        """返回 (分值, 错误提示)；成功时错误提示为空字符串。"""
        for item in list(self._parsers):
            if not self.manager.is_enabled(item["owner"]):
                continue
            try:
                result = item["parser"](text)
            except Exception:
                _log(f"分值解析器异常：\n{traceback.format_exc()}")
                continue
            if isinstance(result, tuple) and len(result) == 2:
                value, error = result
                if error:
                    return None, str(error)
                if value is not None:
                    return value, ""
            elif result is not None:
                return result, ""
        return _parse_int_score(text)

    def hint(self) -> str:
        return "；".join(h["text"] for h in self._hints
                        if self.manager.is_enabled(h["owner"]))

    def remove_owner(self, owner: str):
        self._parsers = [p for p in self._parsers if p["owner"] != owner]
        self._hints = [h for h in self._hints if h["owner"] != owner]


# ===================== 事件总线 =====================
class EventBus:
    def __init__(self):
        self._subs: dict[str, list] = {}

    def on(self, event: str, callback):
        self._subs.setdefault(str(event), []).append(callback)
        return callback

    def off(self, event: str, callback):
        try:
            self._subs.get(str(event), []).remove(callback)
        except ValueError:
            pass

    def emit(self, event: str, payload=None):
        for cb in list(self._subs.get(str(event), [])):
            try:
                cb(payload)
            except Exception:
                _log(f"事件 {event} 回调异常：\n{traceback.format_exc()}")


# ===================== 插件配置 =====================
class PluginSettings:
    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.path = PLUGIN_DATA_DIR / f"{plugin_id}.json"

    def all(self) -> dict:
        data = _load_json(self.path, {})
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default=None):
        return self.all().get(key, default)

    def set(self, key: str, value):
        data = self.all()
        data[key] = value
        return _save_json(self.path, data)

    def update(self, patch: dict):
        data = self.all()
        data.update(patch or {})
        return _save_json(self.path, data)


# ===================== 数据 API =====================
class DataAPI:
    """积分 / 小组 / 卫生的统一读写入口，供所有插件复用。"""

    def load_students(self) -> dict:
        import score_records
        return score_records.load_students()

    def save_students(self, data: dict):
        import score_records
        score_records.save_students(data)

    def load_groups(self) -> dict:
        import score_records
        return score_records.load_groups()

    def save_groups(self, data: dict):
        import score_records
        score_records.save_groups(data)

    def load_hygiene(self) -> dict:
        import score_records
        return score_records.load_hygiene()

    def save_all(self, students: dict, groups: dict):
        import score_records
        score_records.sync_group_totals(students, groups)
        score_records.save_students(students)
        score_records.save_groups(groups)

    def class_names(self) -> list:
        data = _load_json(APP_DIR / "class_data.txt", [])
        if not isinstance(data, list):
            return []
        return [str(c) for c in data if str(c).strip()]

    def default_class(self) -> str:
        names = self.class_names()
        return names[0] if names else "七年级10班"

    # ---- 只读计算 ----
    def total(self, info: dict) -> int:
        import score_records
        return score_records.student_total(info)

    def records(self, info: dict) -> list:
        import score_records
        return score_records.student_records(info)

    def delta(self, rec: dict) -> int:
        import score_records
        return score_records.record_delta(rec)

    def iter_records(self, students: dict, groups: dict, cls: str):
        import score_records
        return score_records.iter_point_records(students, groups, cls)

    def group_total(self, group: dict, stu: dict) -> int:
        import score_records
        return score_records.group_total(group, stu)

    def group_map(self, groups: dict, stu: dict) -> dict:
        import score_records
        return score_records.student_group_map(groups, stu)

    # ---- 写入 ----
    def add_records(self, students: dict, groups: dict, cls: str,
                    sids: list, reason: str, delta: int) -> int:
        import score_records
        count = score_records.add_point_records(students, groups, cls, sids, reason, delta)
        score_records.sync_group_totals(students, groups)
        return count

    def remove_records(self, students: dict, groups: dict, cls: str,
                       items: list) -> int:
        """items = [(sid, rec_dict), ...]；按对象身份删除，避免下标错位。"""
        stu = students.get(cls, {})
        removed = 0
        for sid, rec in items:
            info = stu.get(sid)
            if not isinstance(info, dict):
                continue
            records = info.get("records", [])
            for idx, current in enumerate(records):
                if current is rec:
                    records.pop(idx)
                    removed += 1
                    break
            info["total_score"] = self.total(info)
        if removed:
            self.save_all(students, groups)
        return removed

    def log_ops(self, lines):
        if not lines:
            return
        try:
            log_dir = APP_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "score_operations.log", "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(str(line) + "\n")
        except OSError:
            pass

    # ---- 排行 / 荣誉 ----
    def rank_students(self, students: dict, groups: dict, cls: str) -> list:
        """[(名次, 学号, 姓名, 小组, 总分)]"""
        stu = students.get(cls, {})
        gmap = self.group_map(groups.get(cls, {}), stu)
        rows = []
        for sid, info in stu.items():
            if not isinstance(info, dict):
                continue
            rows.append((sid, info.get("name", ""), gmap.get(sid, "未分组"),
                         self.total(info)))
        rows.sort(key=lambda r: (-r[3], r[0]))
        return [(i + 1, *row) for i, row in enumerate(rows)]

    def rank_groups(self, students: dict, groups: dict, cls: str) -> list:
        """[(名次, 小组, 人数, 总分)]"""
        stu = students.get(cls, {})
        rows = []
        for gname, group in groups.get(cls, {}).items():
            if not isinstance(group, dict):
                continue
            members = [s for s in group.get("members", []) if s in stu]
            rows.append((gname, len(members), self.group_total(group, stu)))
        rows.sort(key=lambda r: (-r[2], r[0]))
        return [(i + 1, *row) for i, row in enumerate(rows)]

    @staticmethod
    def week_key(moment: datetime | None = None) -> str:
        return (moment or datetime.now()).strftime("%G-W%V")

    @classmethod
    def previous_week_key(cls) -> str:
        return (datetime.now() - timedelta(days=7)).strftime("%G-W%V")

    def record_week(self, rec: dict) -> str:
        week = rec.get("week")
        if week:
            return str(week)
        text = rec.get("time", "")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).strftime("%G-W%V")
            except (ValueError, TypeError):
                continue
        return "未知"

    def weekly_net(self, info: dict, week: str) -> int:
        return sum(self.delta(r) for r in self.records(info)
                   if isinstance(r, dict) and self.record_week(r) == week)

    def honors(self, students: dict, groups: dict, cls: str) -> dict:
        """荣誉榜数据：总分榜 / 小组榜 / 本周之星 / 进步之星。"""
        cur, prev = self.week_key(), self.previous_week_key()
        stu = students.get(cls, {})
        gmap = self.group_map(groups.get(cls, {}), stu)
        week_rows, imp_rows = [], []
        for sid, info in stu.items():
            if not isinstance(info, dict):
                continue
            now = self.weekly_net(info, cur)
            before = self.weekly_net(info, prev)
            base = (sid, info.get("name", ""), gmap.get(sid, "未分组"))
            week_rows.append((*base, now))
            imp_rows.append((*base, now - before))
        week_rows.sort(key=lambda r: (-r[3], r[0]))
        imp_rows = [r for r in imp_rows if r[3] > 0]
        imp_rows.sort(key=lambda r: (-r[3], r[0]))
        return {
            "week": cur,
            "previous_week": prev,
            "top_students": self.rank_students(students, groups, cls)[:3],
            "top_groups": self.rank_groups(students, groups, cls)[:3],
            "week_stars": week_rows[:3],
            "improvers": imp_rows[:3],
        }


# ===================== 学生积分窗口适配 =====================
class ScoreWindowAPI:
    """把宿主 StudentScoreWindow 包装成插件可用的稳定接口。"""

    def __init__(self, window):
        self._w = window

    @property
    def window(self):
        return self._w.win

    @property
    def app_root(self):
        return self._w.win.master

    @property
    def current_class(self) -> str:
        return self._w.current_class

    @current_class.setter
    def current_class(self, value: str):
        self._w.current_class = value
        if hasattr(self._w, "class_box"):
            self._w.class_box.set(value)

    @property
    def readonly(self) -> bool:
        return bool(getattr(self._w, "readonly", False))

    @property
    def students(self) -> dict:
        return self._w.all_students.setdefault(self._w.current_class, {})

    @property
    def groups(self) -> dict:
        return self._w.group_data.setdefault(self._w.current_class, {})

    @property
    def all_students(self) -> dict:
        return self._w.all_students

    @property
    def group_data(self) -> dict:
        return self._w.group_data

    @property
    def selected_ids(self) -> set:
        return set(getattr(self._w, "selected_ids", set()))

    def save(self):
        self._w._save_all()

    def refresh(self):
        self._w._refresh_scores()

    def render(self):
        self._w._render_cards()

    def status(self, text: str, color: str = "#9090a0"):
        if hasattr(self._w, "_set_status"):
            self._w._set_status(text, color)

    def log(self, lines):
        if hasattr(self._w, "_log_ops"):
            self._w._log_ops(lines)

    def dialog(self, title, width, height):
        return self._w._dialog(title, width, height)

    def button(self, parent, text, command, primary=False):
        return self._w._btn(parent, text, command, primary=primary)

    def entry(self, parent, width=18):
        return self._w._entry(parent, width)

    def chart_window(self, title, width, height, draw):
        return self._w._chart_window(title, width, height, draw)

    def open_score(self, sids=None):
        target = list(sids or [])
        self._w._open_score(target_students=target)

    @property
    def theme(self) -> dict:
        import ui
        return {
            "bg_main": ui.BG_MAIN, "bg_panel": ui.BG_PANEL, "bg_cell": ui.BG_CELL,
            "bg_cell_alt": ui.BG_CELL_ALT, "bg_in_class": ui.BG_IN_CLASS,
            "fg_text": ui.FG_TEXT, "fg_dim": ui.FG_DIM, "fg_accent": ui.FG_ACCENT,
            "fg_warn": ui.FG_WARN, "fg_danger": ui.FG_DANGER, "fg_ok": ui.FG_OK,
            "font": "Microsoft YaHei UI",
        }


# ===================== UI 注册桥 =====================
class UIBridge:
    def __init__(self, app=None, manager=None):
        self.app = app
        self.manager = manager
        self._main_menus: list[dict] = []
        self._score_menus: list[dict] = []
        self._top_buttons: list[dict] = []

    def _active(self, item: dict) -> bool:
        return self.manager is None or self.manager.is_enabled(item.get("owner"))

    def _host(self):
        """宿主界面对象：优先 ScheduleUI 实例（可能是 root._schedule_ui），否则退回 app。"""
        app = self.app
        if app is None:
            return None
        if hasattr(app, "refresh_plugin_top_buttons"):
            return app
        return getattr(app, "_schedule_ui", app)

    # ---- 主界面 ----
    def add_main_menu(self, label: str, callback, order: int = 100,
                      owner: str | None = None):
        self._main_menus.append({"label": label, "callback": callback,
                                 "order": order, "owner": owner})
        self._sort(self._main_menus)

    def main_menu_items(self) -> list:
        return [(i["label"], i["callback"]) for i in self._main_menus
                if self._active(i)]

    # ---- 学生积分窗口 ----
    def add_score_menu(self, label: str, callback, order: int = 100,
                       readonly_ok: bool = True, owner: str | None = None):
        self._score_menus.append({"label": label, "callback": callback,
                                  "order": order, "readonly_ok": readonly_ok,
                                  "owner": owner})
        self._sort(self._score_menus)

    def score_menu_items(self, readonly: bool = False) -> list:
        return [(i["label"], i["callback"]) for i in self._score_menus
                if self._active(i) and
                ((not readonly) or i.get("readonly_ok", True))]

    def get_score_window_api(self):
        try:
            host = self._host()
            if host is None:
                return None
            root = getattr(host, "root", host)
            win = getattr(root, "_score_window", None)
            if win is not None and win.winfo_exists():
                ctrl = getattr(win, "_controller", None)
                if ctrl is not None:
                    return ScoreWindowAPI(ctrl)
        except Exception:
            pass
        return None

    # ---- 顶部按钮 ----
    def add_top_button(self, text: str, callback, order: int = 100,
                       owner: str | None = None):
        self._top_buttons.append({"text": text, "callback": callback,
                                  "order": order, "owner": owner})
        self._sort(self._top_buttons)
        self._refresh_top_buttons()

    def top_button_items(self) -> list:
        return [(i["text"], i["callback"]) for i in self._top_buttons
                if self._active(i)]

    def remove_owner(self, owner: str):
        for items in (self._main_menus, self._score_menus, self._top_buttons):
            items[:] = [i for i in items if i.get("owner") != owner]
        self._refresh_top_buttons()

    def _refresh_top_buttons(self):
        host = self._host()
        if host is None:
            return
        fn = getattr(host, "refresh_plugin_top_buttons", None)
        if fn is None:
            return
        try:
            fn(self.top_button_items())
        except Exception:
            _log(f"刷新顶部按钮失败：\n{traceback.format_exc()}")

    # ---- 与宿主交互 ----
    def open_student_score(self, readonly: bool = False):
        host = self._host()
        if host is not None and hasattr(host, "_show_student_score"):
            return host._show_student_score(readonly=readonly)
        return None

    def open_hygiene(self):
        host = self._host()
        if host is not None and hasattr(host, "_open_hygiene"):
            return host._open_hygiene()
        return None

    @staticmethod
    def _sort(items: list):
        items.sort(key=lambda i: (i.get("order", 100), i.get("label", "") or
                                  i.get("text", "")))


# ===================== 悬浮球注册桥 =====================
class BallBridge:
    def __init__(self, ball=None, manager=None):
        self._ball = ball
        self.manager = manager
        self._menu_items: list[dict] = []
        self._skins: list[dict] = []
        self._click_actions: list[dict] = []

    @property
    def available(self) -> bool:
        return self._ball is not None

    def _active(self, item: dict) -> bool:
        return self.manager is None or self.manager.is_enabled(item.get("owner"))

    def attach(self, ball):
        self._ball = ball
        self._sync_ball()

    def _sync_ball(self):
        """按当前启用状态重建悬浮球菜单 / 皮肤 / 单击动作。"""
        if self._ball is None:
            return
        try:
            clear = getattr(self._ball, "clear_plugin_items", None)
            if clear is not None:
                clear()
            for item in self._menu_items:
                if self._active(item):
                    self._ball.add_plugin_menu(item["label"], item["callback"],
                                               item["order"])
            for skin in self._skins:
                if self._active(skin):
                    self._ball.register_image_skin(
                        skin["name"], skin["path"], skin["default"], skin["order"])
            actions = [a for a in self._click_actions if self._active(a)]
            self._ball.set_click_action(actions[-1]["callback"] if actions else None)
        except Exception:
            _log(f"同步悬浮球插件项失败：\n{traceback.format_exc()}")

    def add_menu(self, label: str, callback, order: int = 100,
                 owner: str | None = None):
        self._menu_items.append({"label": label, "callback": callback,
                                 "order": order, "owner": owner})
        self._menu_items.sort(key=lambda i: (i["order"], i["label"]))
        self._sync_ball()

    def register_skin(self, name: str, image_path, default: bool = False,
                      order: int = 100, owner: str | None = None):
        self._skins = [s for s in self._skins if s["name"] != name]
        self._skins.append({"name": str(name), "path": str(image_path),
                            "default": default, "order": order, "owner": owner})
        self._sync_ball()

    def set_click_action(self, callback, owner: str | None = None):
        self._click_actions = [a for a in self._click_actions
                               if a["owner"] != owner]
        if callback is not None:
            self._click_actions.append({"callback": callback, "owner": owner})
        self._sync_ball()

    def remove_owner(self, owner: str):
        self._menu_items = [i for i in self._menu_items if i.get("owner") != owner]
        self._skins = [s for s in self._skins if s.get("owner") != owner]
        self._click_actions = [a for a in self._click_actions
                               if a.get("owner") != owner]
        self._sync_ball()

    def position(self):
        """悬浮球当前屏幕坐标 (x, y, size)；无球时返回 None。"""
        if self._ball is None:
            return None
        try:
            win = self._ball.win
            return win.winfo_x(), win.winfo_y(), self._ball.size
        except Exception:
            return None

    def hide(self):
        if self._ball is not None:
            self._ball.hide()

    def redraw(self):
        if self._ball is not None:
            self._ball.refresh_skins()

    def set_skin_name(self, name: str) -> bool:
        if self._ball is None:
            return False
        return self._ball.set_skin_name(name)

    def open_score(self, readonly: bool = False):
        if self._ball is not None:
            return self._ball.open_score(readonly=readonly)
        return None


# ===================== 插件作用域代理 =====================
class _ScopedProxy:
    """把插件注册项自动打上归属标记，禁用时可精确移除。"""

    def __init__(self, target, owner):
        self._target = target
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._target, name)


class ScopedUI(_ScopedProxy):
    def add_main_menu(self, label, callback, order=100):
        return self._target.add_main_menu(label, callback, order, self._owner)

    def add_score_menu(self, label, callback, order=100, readonly_ok=True):
        return self._target.add_score_menu(label, callback, order,
                                           readonly_ok, self._owner)

    def add_top_button(self, text, callback, order=100):
        return self._target.add_top_button(text, callback, order, self._owner)


class ScopedBall(_ScopedProxy):
    def add_menu(self, label, callback, order=100):
        return self._target.add_menu(label, callback, order, self._owner)

    def register_skin(self, name, image_path, default=False, order=100):
        return self._target.register_skin(name, image_path, default,
                                          order, self._owner)

    def set_click_action(self, callback):
        return self._target.set_click_action(callback, self._owner)


class ScopedScores(_ScopedProxy):
    def set_parser(self, parser, order=100):
        return self._target.set_parser(parser, order, self._owner)

    def set_hint(self, text):
        return self._target.set_hint(text, self._owner)


class ScopedEvents(_ScopedProxy):
    def __init__(self, target, owner):
        super().__init__(target, owner)
        self._subs: list[tuple] = []

    def on(self, event, callback):
        self._subs.append((event, callback))
        return self._target.on(event, callback)

    def off(self, event, callback):
        try:
            self._subs.remove((event, callback))
        except ValueError:
            pass
        return self._target.off(event, callback)

    def emit(self, event, payload=None):
        return self._target.emit(event, payload)

    def detach(self):
        for event, callback in list(self._subs):
            self._target.off(event, callback)
        self._subs.clear()


# ===================== 插件上下文 =====================
class PluginContext:
    def __init__(self, manager, plugin_id, manifest, module):
        self.manager = manager
        self.id = plugin_id
        self.manifest = manifest
        self.module = module
        self.app = manager.app
        self.backend = manager.backend
        self.data = manager.data
        self.ui = ScopedUI(manager.ui, plugin_id)
        self.ball = ScopedBall(manager.ball, plugin_id)
        self.events = ScopedEvents(manager.events, plugin_id)
        self.scores = ScopedScores(manager.scores, plugin_id)
        self.settings = PluginSettings(plugin_id)
        self.api_version = API_VERSION

    @property
    def plugin_dir(self) -> Path:
        return Path(self.module.__file__).parent

    @property
    def host(self):
        """主界面对象（ScheduleUI）；拿不到时退回 app，兼容旧插件的 ctx.host 用法。"""
        app = self.app
        return getattr(app, "_schedule_ui", app)

    def log(self, message: str):
        _log(f"[{self.id}] {message}")

    def detach(self):
        """禁用插件时撤掉它注册的事件监听与分值解析能力。"""
        self.events.detach()
        self.manager.ui.remove_owner(self.id)
        self.manager.ball.remove_owner(self.id)
        self.manager.scores.remove_owner(self.id)


class PluginRecord:
    def __init__(self, plugin_id, path, manifest):
        self.id = plugin_id
        self.path = path
        self.manifest = manifest
        self.module = None
        self.ok = False
        self.error = ""


# ===================== 插件管理器 =====================
class PluginManager:
    def __init__(self, app=None, backend=None, ball=None, plugin_dir: Path | None = None):
        self.app = app
        self.backend = backend
        self.plugin_dir = Path(plugin_dir) if plugin_dir else PLUGIN_DIR
        self.data = DataAPI()
        self.events = EventBus()
        self.scores = ScoreBridge(self)
        self.ui = UIBridge(app, self)
        self.ball = BallBridge(ball, self)
        self.records: list[PluginRecord] = []
        self.contexts: dict[str, PluginContext] = {}
        self._loaded = False

    # ---- 启用 / 禁用 ----
    def is_enabled(self, plugin_id) -> bool:
        return bool(_load_enabled().get(str(plugin_id), True))

    def set_enabled(self, plugin_id, enabled: bool) -> bool:
        record = next((r for r in self.records if r.id == str(plugin_id)), None)
        if record is None:
            return False
        enabled = bool(enabled)
        if self.is_enabled(record.id) == enabled:
            return True
        _store_enabled(record.id, enabled)
        if enabled:
            self._register(record)
        else:
            self._unregister(record.id)
        _log(f"插件 {record.id} 已{'启用' if enabled else '禁用'}")
        return True

    def sync_enabled_states(self):
        """跨进程共享开关：悬浮球进程定时调用，跟上主界面的启停操作。"""
        states = _load_enabled()
        for record in list(self.records):
            want = bool(states.get(record.id, True))
            active = record.id in self.contexts
            if want and not active:
                self._register(record)
            elif not want and (active or record.ok):
                self._unregister(record.id)

    def _unregister(self, plugin_id: str):
        ctx = self.contexts.pop(plugin_id, None)
        if ctx is not None:
            ctx.events.detach()
        self.ui.remove_owner(plugin_id)
        self.ball.remove_owner(plugin_id)
        self.scores.remove_owner(plugin_id)
        record = next((r for r in self.records if r.id == plugin_id), None)
        if record is not None:
            record.ok = False
            record.error = ""

    # ---- 发现 ----
    def discover(self) -> list:
        self.records.clear()
        if not self.plugin_dir.exists():
            _log(f"插件目录不存在：{self.plugin_dir}")
            return []
        seen = set()
        # 单文件插件：plugins/xxx.py
        candidates = [(p, None) for p in sorted(self.plugin_dir.glob("*.py"))
                      if not p.name.startswith("_")]
        # 目录插件：plugins/xxx/plugin.py（支持相对导入，兼容老式插件）
        for child in sorted(self.plugin_dir.iterdir()):
            if (child.is_dir() and not child.name.startswith((".", "_"))
                    and (child / "plugin.py").exists()):
                candidates.append((child / "plugin.py", child))
        for path, package in candidates:
            record = self._load_module(path, package)
            if record is None:
                continue
            if record.id in seen:
                _log(f"跳过重复插件 id：{record.id}（{path.name}）")
                continue
            seen.add(record.id)
            self.records.append(record)
        self.records.sort(key=lambda r: (int(r.manifest.get("priority", 100)), r.id))
        return self.records

    def _load_module(self, path: Path, package: Path | None = None):
        module_name = f"trae_plugin_{package.name if package else path.stem}"
        try:
            if package is not None:
                spec = importlib.util.spec_from_file_location(
                    module_name, path, submodule_search_locations=[str(package)])
            else:
                spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError("无法创建模块 spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            _log(f"加载插件文件失败 {path.name}：\n{traceback.format_exc()}")
            return None

        manifest = getattr(module, "PLUGIN", None)
        if not isinstance(manifest, dict):
            _log(f"插件 {path.name} 缺少 PLUGIN 字典，已跳过")
            return None
        pid = str(manifest.get("id") or (package.name if package else path.stem)).strip()
        if not pid:
            _log(f"插件 {path.name} 的 id 为空，已跳过")
            return None
        api_version = manifest.get("api_version", 1)
        try:
            api_version = int(api_version)
        except (TypeError, ValueError):
            api_version = 1
        if api_version > API_VERSION:
            _log(f"插件 {pid} 需要 API v{api_version}，当前框架 v{API_VERSION}，已跳过")
            return None
        if not callable(getattr(module, "register", None)):
            _log(f"插件 {pid} 缺少 register(ctx) 函数，已跳过")
            return None
        manifest.setdefault("name", pid)
        manifest.setdefault("version", "1.0.0")
        manifest.setdefault("priority", 100)
        record = PluginRecord(pid, path, manifest)
        record.module = module
        return record

    # ---- 加载（依赖排序 + 异常隔离） ----
    def load_all(self):
        if self._loaded:
            self.sync_enabled_states()
            return self.records
        if not self.records:
            self.discover()
        pending = list(self.records)
        loaded_ids = set()
        while pending:
            progressed = False
            for record in list(pending):
                requires = record.manifest.get("requires") or []
                if not isinstance(requires, (list, tuple)):
                    requires = []
                missing = [r for r in requires if str(r) not in loaded_ids]
                if missing:
                    # 依赖还没加载：等下一轮；若依赖根本不存在则本轮结束后报错
                    available = {r.id for r in self.records}
                    if any(str(m) not in available for m in missing):
                        record.error = f"缺少依赖插件：{', '.join(map(str, missing))}"
                        _log(f"插件 {record.id} 加载失败：{record.error}")
                        pending.remove(record)
                        progressed = True
                    continue
                self._register(record)
                loaded_ids.add(record.id)
                pending.remove(record)
                progressed = True
            if not progressed:
                for record in pending:
                    record.error = "依赖解析失败（可能存在循环依赖）"
                    _log(f"插件 {record.id} 加载失败：{record.error}")
                break

        self._loaded = True
        ok = [r for r in self.records if r.ok]
        _log(f"插件加载完成：成功 {len(ok)} 个，失败 {len(self.records) - len(ok)} 个")
        try:
            self.events.emit("app_ready", {"manager": self})
            if self.ball.available:
                self.events.emit("ball_ready", {"manager": self})
                self.ball.redraw()
        except Exception:
            pass
        return self.records

    def _register(self, record: PluginRecord):
        if not self.is_enabled(record.id):
            record.ok = False
            record.error = ""
            return False
        if record.id in self.contexts:
            return True
        ctx = PluginContext(self, record.id, record.manifest, record.module)
        try:
            record.module.register(ctx)
            record.ok = True
            record.error = ""
            self.contexts[record.id] = ctx
            _log(f"已加载插件 {record.id} {record.manifest.get('version', '')}")
            return True
        except Exception:
            ctx.detach()
            record.ok = False
            record.error = traceback.format_exc()
            _log(f"插件 {record.id} 注册失败：\n{record.error}")
            return False

    # ---- 诊断 ----
    def summary(self) -> str:
        if not self.records:
            return "未发现插件。"
        lines = []
        for record in self.records:
            name = record.manifest.get("name", record.id)
            version = record.manifest.get("version", "")
            if not self.is_enabled(record.id):
                state = "◌ 已禁用"
            else:
                state = "✓ 已启用" if record.ok else "✗ 未启用"
            lines.append(f"{state}  {name}  v{version}  ({record.id})")
            desc = record.manifest.get("description")
            if desc:
                lines.append(f"    {desc}")
            if not record.ok and record.error:
                first = record.error.strip().splitlines()[-1]
                lines.append(f"    错误：{first}")
        return "\n".join(lines)

    def shutdown(self):
        self.events.emit("app_shutdown", None)


# ===================== 全局入口 =====================
_manager: PluginManager | None = None


def init(app=None, backend=None, ball=None, plugin_dir=None) -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager(app=app, backend=backend, ball=ball,
                                 plugin_dir=plugin_dir)
    else:
        if app is not None:
            _manager.app = app
            _manager.ui.app = app
        if backend is not None:
            _manager.backend = backend
        if ball is not None:
            _manager.ball.attach(ball)
    return _manager


def load_all():
    if _manager is None:
        init()
    return _manager.load_all()


def get_manager() -> PluginManager | None:
    return _manager


def emit(event: str, payload=None):
    if _manager is not None:
        _manager.events.emit(event, payload)


def main_menu_items() -> list:
    return _manager.ui.main_menu_items() if _manager else []


def score_menu_items(readonly: bool = False) -> list:
    return _manager.ui.score_menu_items(readonly) if _manager else []


def top_button_items() -> list:
    return _manager.ui.top_button_items() if _manager else []


def get_score_window_api():
    return _manager.ui.get_score_window_api() if _manager else None


def plugin_summary() -> str:
    return _manager.summary() if _manager else "插件框架未初始化。"


def plugin_infos() -> list:
    """给主界面插件菜单用：[{id, name, version, description, enabled, ok}]。"""
    if _manager is None:
        return []
    return [{
        "id": r.id,
        "name": r.manifest.get("name", r.id),
        "version": r.manifest.get("version", ""),
        "description": r.manifest.get("description", ""),
        "enabled": _manager.is_enabled(r.id),
        "ok": r.ok,
        "error": r.error,
    } for r in _manager.records]


def is_plugin_enabled(plugin_id: str) -> bool:
    return bool(_load_enabled().get(str(plugin_id), True))


def set_plugin_enabled(plugin_id: str, enabled: bool) -> bool:
    if _manager is not None:
        return _manager.set_enabled(plugin_id, enabled)
    return _store_enabled(plugin_id, enabled)


def refresh_enabled_states():
    if _manager is not None:
        _manager.sync_enabled_states()


def parse_score(text) -> tuple:
    """分值解析入口：默认整数，启用相应插件后可支持小数。"""
    if _manager is not None:
        return _manager.scores.parse(text)
    return _parse_int_score(text)


def score_hint() -> str:
    return _manager.scores.hint() if _manager is not None else ""


def shutdown():
    if _manager is not None:
        _manager.shutdown()
