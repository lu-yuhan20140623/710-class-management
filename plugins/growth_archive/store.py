"""成长档案数据层：追加式永久记录（JSONL）。

- points.jsonl：每一条加分/扣分记录（跨重置永久保留）
- duty.jsonl：岗位履职自评 / 组内互评
行为与界面解耦，任何进程都能安全追加一行。
"""

import json
import time
from pathlib import Path

import score_records as store

PLUGIN_ID = "growth_archive"

_CATEGORY = None


# ---------- 基础读写 ----------
def _dir() -> Path:
    path = store.APP_DIR / "plugins_data" / PLUGIN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append(name: str, obj: dict):
    line = json.dumps(obj, ensure_ascii=False)
    with open(_dir() / name, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read(name: str) -> list:
    path = _dir() / name
    if not path.exists():
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def _day(ts: str) -> str:
    return (ts or "")[:10]


# ---------- 分项归类 ----------
def category_of(reason: str) -> str:
    """把打分理由归到「课堂表现 / 日常纪律 / 卫生 / 作业」等分项。"""
    global _CATEGORY
    if _CATEGORY is None:
        _CATEGORY = {}
        try:
            import student_score
            for cat, reasons in student_score.reason_categories.items():
                for r in reasons:
                    _CATEGORY.setdefault(str(r), cat)
        except Exception:
            _CATEGORY = {}
    if not reason:
        return "其他"
    return _CATEGORY.get(str(reason), "其他")


# ---------- 积分档案 ----------
def record_points(cls: str, sids: list, delta: int, reason: str):
    """把一次批量加减分拆成每个学生一条永久记录。"""
    students = store.load_students()
    groups = store.load_groups()
    stu = students.get(cls, {})
    gmap = store.student_group_map(groups.get(cls, {}), stu)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    week = time.strftime("%G-W%V")
    cat = category_of(reason)
    count = 0
    for sid in sids or []:
        info = stu.get(sid)
        if not isinstance(info, dict):
            continue
        _append("points.jsonl", {
            "ts": now, "week": week, "cls": cls, "sid": sid,
            "name": info.get("name", ""), "group": gmap.get(sid, "未分组"),
            "delta": int(delta), "reason": reason, "category": cat,
        })
        count += 1
    return count


def _point_key(row: dict) -> tuple:
    return (row.get("sid", ""), row.get("ts", ""), row.get("reason", ""),
            int(row.get("delta", 0)))


def seed_from_students() -> int:
    """把 student_data 里已有的积分记录补进档案，已存在的不重复写。

    每次打开档案窗口都会执行，因此即使之前只通过事件记录了部分数据，
    历史记录也会被补齐。
    """
    students = store.load_students()
    groups = store.load_groups()
    existing = {_point_key(r) for r in _read("points.jsonl")}
    count = 0
    for cls, stu in students.items():
        gmap = store.student_group_map(groups.get(cls, {}), stu)
        for sid, info in stu.items():
            if not isinstance(info, dict):
                continue
            for rec in info.get("records", []):
                if not isinstance(rec, dict):
                    continue
                row = {
                    "ts": rec.get("time", ""), "week": rec.get("week", ""),
                    "cls": cls, "sid": sid, "name": info.get("name", ""),
                    "group": gmap.get(sid, "未分组"),
                    "delta": store.record_delta(rec),
                    "reason": rec.get("reason", ""),
                    "category": category_of(rec.get("reason", "")),
                }
                key = _point_key(row)
                if key in existing:
                    continue
                _append("points.jsonl", row)
                existing.add(key)
                count += 1
    return count


def seed_history_from_archive() -> int:
    """把「积分记录.xlsx」里历次重置归档的汇总补进档案（每周一条）。

    归档表格只保留每人每期的汇总分值，没有逐条时间/事由，
    因此这里按「历史归档汇总」写入，保证榜单与成长曲线能看到历史。
    """
    book = store.POINTS_BOOK
    if not book.exists():
        return 0
    try:
        stat = book.stat()
        marker = _dir() / ".history_seed.json"
        sig = {"mtime": int(stat.st_mtime), "size": stat.st_size}
        if marker.exists():
            try:
                if json.loads(marker.read_text(encoding="utf-8")) == sig:
                    return 0
            except ValueError:
                pass
        import openpyxl
        wb = openpyxl.load_workbook(book, read_only=True, data_only=True)
    except Exception:
        return 0

    existing = {_point_key(r) for r in _read("points.jsonl")}
    count = 0
    for sheet in wb.sheetnames:
        if sheet.lower() == "total":
            continue
        rows = list(wb[sheet].iter_rows(values_only=True))
        period, week = "", ""
        for line in rows[:4]:
            for value in line:
                if isinstance(value, str) and value.startswith("周期："):
                    period = value[3:].strip()
        if not period:
            continue
        day = period[:10]
        week = period[period.find("（") + 1:period.find("）")] if "（" in period else ""
        for line in rows[4:]:
            if not line or not line[0]:
                continue
            first = str(line[0]).strip()
            if first == "小组统计":
                break
            cls, sid, name, group = line[0], line[1], line[2], line[3]
            if not sid:
                continue
            try:
                delta = int(line[4] or 0)
            except (TypeError, ValueError):
                continue
            if delta == 0:
                continue
            row = {
                "ts": f"{day} 12:00:00", "week": week, "cls": str(cls),
                "sid": str(sid), "name": str(name or ""), "group": str(group or "未分组"),
                "delta": delta, "reason": "历史归档汇总", "category": "历史归档",
            }
            key = _point_key(row)
            if key in existing:
                continue
            _append("points.jsonl", row)
            existing.add(key)
            count += 1
    try:
        (_dir() / ".history_seed.json").write_text(
            json.dumps(sig, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return count


def seed_all() -> int:
    """补齐当前记录 + 历史归档，返回新增条数。"""
    return seed_from_students() + seed_history_from_archive()


def points(cls: str | None = None) -> list:
    rows = _read("points.jsonl")
    if cls:
        rows = [r for r in rows if r.get("cls") == cls]
    return rows


def classes() -> list:
    return sorted({r.get("cls", "") for r in points() if r.get("cls")})


def students_brief(cls: str) -> list:
    """[(学号, 姓名, 小组)]，用于界面选择。"""
    students = store.load_students()
    groups = store.load_groups()
    stu = students.get(cls, {})
    gmap = store.student_group_map(groups.get(cls, {}), stu)
    return [(sid, info.get("name", ""), gmap.get(sid, "未分组"))
            for sid, info in stu.items() if isinstance(info, dict)]


# ---------- 岗位履职 ----------
def add_duty(cls: str, sid: str, name: str, duty: str, kind: str,
             score: int, comment: str, evaluator: str = ""):
    _append("duty.jsonl", {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cls": cls, "sid": sid, "name": name, "duty": duty,
        "kind": kind, "score": int(score), "comment": comment,
        "evaluator": evaluator,
    })


def duties(cls: str | None = None) -> list:
    rows = _read("duty.jsonl")
    if cls:
        rows = [r for r in rows if r.get("cls") == cls]
    return rows
