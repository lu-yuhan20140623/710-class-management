"""
课程表数据层
- 时间表、课程安排
- 调课（单节课替换）持久化
- 禁用（时间段内整个程序暂停）持久化
- 课节判断逻辑（含当前是否处于禁用时间段）
"""

import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

# ---------- 数据路径 ----------
if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).parent.resolve()
else:
    DATA_DIR = Path(__file__).parent.resolve()
OVERRIDES_FILE = DATA_DIR / "overrides.json"
DISABLED_FILE  = DATA_DIR / "disabled_ranges.json"   # 时间段禁用

# ---------- 星期枚举 ----------
WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ---------- 时间表 ----------
PERIODS = {
    1: (time(8, 0),   time(8, 45)),
    2: (time(9, 0),   time(9, 45)),
    3: (time(10, 15), time(11, 0)),
    4: (time(11, 10), time(11, 50)),
    5: (time(13, 45), time(14, 30)),
    6: (time(14, 45), time(15, 30)),
    7: (time(15, 45), time(16, 30)),
}

# 倒计时窗口 = 上课前 4 分钟 ~ 上课前 2 分钟（共 2 分钟）
# 预备铃 = 上课前 2 分钟（倒计时在此刻结束）
REMIND_AHEAD_MINUTES = 4
PREBELL_AHEAD_MINUTES = 2

# ---------- 课程表 ----------
DEFAULT_SCHEDULE = {
    0: {1: "语文", 2: "数学", 3: "生物", 4: "英语", 5: "体育", 6: "道法", 7: "地理"},
    1: {1: "历史", 2: "语文", 3: "英语", 4: "信息", 5: "英语/心理", 6: "数学", 7: "班会"},
    2: {1: "数学", 2: "英语", 3: "音乐", 4: "生物", 5: "体育", 6: "语文", 7: "选修课"},
    3: {1: "英语", 2: "语文", 3: "数学", 4: "地理", 5: "历史", 6: "语文", 7: "劳动"},
    4: {1: "语文", 2: "英语", 3: "体育", 4: "道法", 5: "数学", 6: "数学", 7: "美术"},
}


# ---------- 持久化辅助 ----------
def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- 调课（单节课替换） ----------
def _load_overrides() -> dict:
    return _load_json(OVERRIDES_FILE, {})


def _save_overrides(overrides: dict):
    _save_json(OVERRIDES_FILE, overrides)


def get_subject(day: int, period: int) -> str:
    """获取某节课实际科目（应用调课后）。"""
    if day not in DEFAULT_SCHEDULE or period not in DEFAULT_SCHEDULE[day]:
        return ""
    overrides = _load_overrides()
    k = f"{day}-{period}"
    return overrides.get(k, DEFAULT_SCHEDULE[day][period])


def set_override(day: int, period: int, subject: str):
    overrides = _load_overrides()
    k = f"{day}-{period}"
    if subject:
        overrides[k] = subject
    else:
        overrides.pop(k, None)
    _save_overrides(overrides)


def get_all_overrides() -> dict:
    return _load_overrides()


# ---------- 禁用（时间段） ----------
# 持久化结构:
#   [ {"start": "2026-11-15T08:00", "end": "2026-11-17T17:00", "note": "期中考试"}, ... ]

_dt_fmt = "%Y-%m-%dT%H:%M"


def _load_disabled_ranges() -> list:
    raw = _load_json(DISABLED_FILE, [])
    # normalize
    out = []
    for item in raw:
        try:
            start = datetime.strptime(item["start"], _dt_fmt)
            end = datetime.strptime(item["end"], _dt_fmt)
            if end > start:
                out.append({"start": start, "end": end, "note": item.get("note", "")})
        except Exception:
            continue
    out.sort(key=lambda r: r["start"])
    return out


def _save_disabled_ranges(ranges: list):
    serializable = [
        {"start": r["start"].strftime(_dt_fmt),
         "end":   r["end"].strftime(_dt_fmt),
         "note":  r.get("note", "")}
        for r in ranges
    ]
    _save_json(DISABLED_FILE, serializable)


def add_disabled_range(start: datetime, end: datetime, note: str = "") -> bool:
    """新增一个禁用时间段。返回是否成功。"""
    if end <= start:
        return False
    ranges = _load_disabled_ranges()
    # 去重叠：合并有重叠或相邻的范围
    ranges.append({"start": start, "end": end, "note": note})
    ranges.sort(key=lambda r: r["start"])
    merged = [ranges[0]]
    for r in ranges[1:]:
        last = merged[-1]
        if r["start"] <= last["end"]:
            last["end"] = max(last["end"], r["end"])
            if r["note"] and r["note"] != last.get("note"):
                last["note"] = (last.get("note") or r["note"])
        else:
            merged.append(r)
    _save_disabled_ranges(merged)
    return True


def remove_disabled_range(index: int) -> bool:
    ranges = _load_disabled_ranges()
    if 0 <= index < len(ranges):
        del ranges[index]
        _save_disabled_ranges(ranges)
        return True
    return False


def get_all_disabled_ranges() -> list:
    return _load_disabled_ranges()


def is_in_disabled_period(dt: datetime = None) -> tuple[bool, str]:
    """
    检查 dt 是否处于某个禁用时间段内。
    返回 (是否在禁用期内, 相关备注)
    """
    dt = dt or datetime.now()
    for r in _load_disabled_ranges():
        if r["start"] <= dt <= r["end"]:
            return True, r.get("note", "禁用中")
    return False, ""


# ---------- 课节判断 ----------
def now() -> datetime:
    return datetime.now()


def get_day_index(dt: datetime = None) -> int:
    dt = dt or now()
    wd = dt.weekday()
    return wd if wd <= 4 else -1


def find_current_period(dt: datetime = None):
    """
    根据当前时间判断当前处于哪个课节阶段。
    """
    dt = dt or now()
    day = get_day_index(dt)
    base_date = dt.date()

    # 先检查是否处于禁用时间段
    disabled, disabled_note = is_in_disabled_period(dt)

    result = {
        "state": "weekend" if day < 0 else "after_school",
        "current_period": None,
        "next_period": None,
        "day": day,
        "seconds_to_next": 0,
        "next_subject": "",
        "next_start": None,
        "is_counting": False,
        "is_prebell": False,
        "seconds_to_prebell": 0,
        "disabled": disabled,
        "disabled_note": disabled_note,
    }

    if disabled:
        result["state"] = "disabled"
        return result

    if day < 0:
        return result

    today_periods = []
    for p, (s, e) in PERIODS.items():
        start_dt = datetime.combine(base_date, s)
        end_dt = datetime.combine(base_date, e)
        today_periods.append((p, start_dt, end_dt))

    for idx, (p, start_dt, end_dt) in enumerate(today_periods):
        if start_dt <= dt < end_dt:
            result["state"] = "in_class"
            result["current_period"] = p
            break

        if dt < start_dt:
            result["state"] = "before_class" if idx == 0 else "between_class"
            result["next_period"] = p
            result["next_start"] = start_dt
            result["seconds_to_next"] = int((start_dt - dt).total_seconds())
            result["next_subject"] = get_subject(day, p)

            start_remind = start_dt - timedelta(minutes=REMIND_AHEAD_MINUTES)
            prebell_time = start_dt - timedelta(minutes=PREBELL_AHEAD_MINUTES)
            result["is_counting"] = start_remind <= dt < prebell_time
            result["is_prebell"] = prebell_time <= dt < start_dt
            result["seconds_to_prebell"] = int((prebell_time - dt).total_seconds())
            break

    return result
