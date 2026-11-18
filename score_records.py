"""
积分 / 卫生的统一数据层
- 积分按“人”记录：记录存放在 student_data.txt 的学生对象里（records / total_score）
- 卫生按“人”记录：记录存放在 hygiene_data.txt（含 sid / name / group，兼容旧的小组记录）
- 统计时按小组汇总，可再下钻到组员明细
- 定时重置：卫生每天中午 12:00，积分每周一中午 12:00（由后台常驻进程驱动）
- 重置前自动归档到 XLSX：每次新建 sheet，另维护 total sheet 保存历史总分
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()

STUDENT_FILE = APP_DIR / "student_data.txt"
GROUP_FILE = APP_DIR / "group_data.txt"
HYGIENE_FILE = APP_DIR / "hygiene_data.txt"
STATE_FILE = APP_DIR / "archive_state.json"
LOCK_FILE = APP_DIR / ".archive.lock"
POINTS_BOOK = APP_DIR / "积分记录.xlsx"
HYGIENE_BOOK = APP_DIR / "卫生记录.xlsx"
LOG_DIR = APP_DIR / "logs"
ARCHIVE_LOG = LOG_DIR / "archive.log"

NOON = dtime(12, 0)
TIME_FMT = "%Y-%m-%d %H:%M:%S"


# ===================== 通用读写 =====================
_DATA_LOCK = threading.RLock()


def _load_json(path: Path, default):
    with _DATA_LOCK:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return default


def atomic_write_json(path: Path, data):
    """加锁 + 临时文件替换，避免手机端读数据时读到半截 JSON。"""
    with _DATA_LOCK:
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise


def _save_json(path: Path, data):
    atomic_write_json(path, data)


def load_students() -> dict:
    data = _load_json(STUDENT_FILE, {})
    return data if isinstance(data, dict) else {}


def save_students(data: dict):
    _save_json(STUDENT_FILE, data)


def load_groups() -> dict:
    data = _load_json(GROUP_FILE, {})
    return data if isinstance(data, dict) else {}


def save_groups(data: dict):
    _save_json(GROUP_FILE, data)


def load_hygiene() -> dict:
    data = _load_json(HYGIENE_FILE, {})
    return data if isinstance(data, dict) else {}


def save_hygiene(data: dict):
    _save_json(HYGIENE_FILE, data)


def log(msg: str):
    """归档/重置日志，失败不影响主流程。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime(TIME_FMT)
        with open(ARCHIVE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


# ===================== 积分（按人） =====================
def record_delta(rec: dict) -> int:
    """单条记录对总分的贡献（加分正、扣分负）。"""
    try:
        score = abs(int(rec.get("score", 0) or 0))
    except (TypeError, ValueError):
        score = 0
    return -score if rec.get("operate") == "扣分" else score


def student_total(info: dict) -> int:
    if not isinstance(info, dict):
        return 0
    return sum(record_delta(r) for r in info.get("records", []) if isinstance(r, dict))


def student_records(info: dict) -> list:
    return info.get("records", []) if isinstance(info, dict) else []


def group_legacy_total(group: dict) -> int:
    """旧版按小组保存的记录（迁移后一般已清空，留作兜底）。"""
    return sum(record_delta(r) for r in group.get("record", []) if isinstance(r, dict))


def group_total(group: dict, stu: dict) -> int:
    total = group_legacy_total(group)
    for sid in group.get("members", []):
        info = stu.get(sid)
        if info:
            total += student_total(info)
    return total


def student_group_map(groups: dict, stu: dict) -> dict:
    """学号 → 小组名。"""
    result = {}
    for gname, group in groups.items():
        for sid in group.get("members", []):
            if sid in stu and sid not in result:
                result[sid] = gname
    return result


def sync_group_totals(students: dict, groups: dict) -> bool:
    """把小组总分同步为组员积分之和（保持与旧版字段兼容）。"""
    changed = False
    for cls, class_groups in groups.items():
        stu = students.get(cls, {})
        for gname, group in class_groups.items():
            if not isinstance(group, dict):
                continue
            total = group_total(group, stu)
            if int(group.get("total_score", 0)) != total:
                group["total_score"] = total
                changed = True
    return changed


def migrate_group_records(students: dict, groups: dict) -> bool:
    """把旧版“按小组”的加减分记录迁移到组长名下，保证小组总分不变。"""
    changed = False
    for cls, class_groups in groups.items():
        stu = students.get(cls, {})
        if not isinstance(stu, dict):
            continue
        for gname, group in class_groups.items():
            if not isinstance(group, dict):
                continue
            legacy = [r for r in group.get("record", []) if isinstance(r, dict)]
            if not legacy:
                continue
            members = [s for s in group.get("members", []) if s in stu]
            leader = group.get("leader")
            target = leader if leader in members else (members[0] if members else None)
            if target is None:
                # 组内没有成员，无法归属到个人，保留旧记录继续计入小组总分
                continue
            info = stu.setdefault(target, {})
            if not isinstance(info.get("records"), list):
                info["records"] = []
            for rec in legacy:
                item = dict(rec)
                item["from_group"] = gname
                info["records"].append(item)
            group["record"] = []
            changed = True
    return changed


def add_point_records(students: dict, groups: dict, cls: str,
                      sids: list, reason: str, delta: int) -> int:
    """按人写入加减分记录，返回实际写入人数。"""
    stu = students.setdefault(cls, {})
    now = time.strftime(TIME_FMT)
    week = time.strftime("%G-W%V")
    mode = "加分" if delta > 0 else "扣分"
    score = abs(int(delta))
    count = 0
    for sid in sids:
        info = stu.get(sid)
        if not isinstance(info, dict):
            continue
        if not isinstance(info.get("records"), list):
            info["records"] = []
        info["records"].append({
            "operate": mode, "score": score, "reason": reason,
            "time": now, "week": week,
        })
        info["total_score"] = student_total(info)
        count += 1
    if count:
        sync_group_totals(students, groups)
        payload = {"cls": cls, "sids": list(sids),
                   "delta": int(delta), "reason": reason}
        # 旧事件总线（plugin_events）与新插件框架各发一份，两边插件都能收到
        try:
            import plugin_events
            plugin_events.emit("points_added", **payload)
        except Exception:
            pass
        try:
            import plugin_api
            plugin_api.emit("points_added", payload)
            plugin_api.emit("score_changed", payload)
        except Exception:
            pass
    return count


def iter_point_records(students: dict, groups: dict, cls: str):
    """遍历某班所有个人积分记录：yield (小组, 学号, 姓名, 记录)。"""
    stu = students.get(cls, {})
    gmap = student_group_map(groups.get(cls, {}), stu)
    for sid, info in stu.items():
        if not isinstance(info, dict):
            continue
        gname = gmap.get(sid, "未分组")
        for rec in info.get("records", []):
            if isinstance(rec, dict):
                yield gname, sid, info.get("name", ""), rec


def points_group_rows(students: dict, groups: dict, cls: str) -> list:
    """[(小组, 人数, 总分)]，总分高的在前。"""
    stu = students.get(cls, {})
    rows = []
    for gname, group in groups.get(cls, {}).items():
        members = [s for s in group.get("members", []) if s in stu]
        rows.append((gname, len(members), group_total(group, stu)))
    rows.sort(key=lambda r: -r[2])
    return rows


def points_member_rows(students: dict, groups: dict, cls: str, gname: str) -> list:
    """[(学号, 姓名, 积分, 是否组长)]。"""
    stu = students.get(cls, {})
    group = groups.get(cls, {}).get(gname, {})
    leader = group.get("leader", "")
    rows = []
    for sid in group.get("members", []):
        info = stu.get(sid)
        if not info:
            continue
        rows.append((sid, info.get("name", ""), student_total(info), sid == leader))
    return rows


def points_member_records(students: dict, cls: str, sid: str) -> list:
    info = students.get(cls, {}).get(sid, {})
    return [r for r in student_records(info) if isinstance(r, dict)]


def point_record_count(students: dict) -> int:
    return sum(len([r for r in student_records(info) if isinstance(r, dict)])
               for stu in students.values() if isinstance(stu, dict)
               for info in stu.values())


# ===================== 卫生（按人） =====================
def hygiene_block(data: dict, cls: str) -> dict:
    block = data.setdefault(cls, {})
    block.setdefault("reasons", [])
    block.setdefault("records", [])
    return block


def hygiene_group_rows(data: dict, cls: str) -> list:
    """某班级卫生扣分按小组汇总：[(小组, 合计扣分, 记录数)]。"""
    rows = []
    block = hygiene_block(data, cls)
    totals = {}
    counts = {}
    for rec in block.get("records", []):
        gname = rec.get("group") or "未分组"
        try:
            score = abs(int(rec.get("score", 0) or 0))
        except (TypeError, ValueError):
            score = 0
        totals[gname] = totals.get(gname, 0) + score
        counts[gname] = counts.get(gname, 0) + 1
    for gname, total in totals.items():
        rows.append((gname, total, counts.get(gname, 0)))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


def hygiene_member_rows(data: dict, students: dict, cls: str, gname: str) -> list:
    """[(学号, 姓名, 扣分)]；旧的小组记录（无学号）不归属到个人。"""
    stu = students.get(cls, {})
    block = hygiene_block(data, cls)
    totals = {}
    for rec in block.get("records", []):
        if (rec.get("group") or "未分组") != gname:
            continue
        sid = rec.get("sid", "")
        if not sid:
            continue
        try:
            score = abs(int(rec.get("score", 0) or 0))
        except (TypeError, ValueError):
            score = 0
        totals[sid] = totals.get(sid, 0) + score
    # 组员顺序按分组名单；没有扣分的组员也列出来
    group = load_groups().get(cls, {}).get(gname)
    from_group = [s for s in (group or {}).get("members", []) if s in stu]
    sids = list(dict.fromkeys(from_group + list(totals)))
    return [(sid, stu.get(sid, {}).get("name", ""), totals.get(sid, 0)) for sid in sids]


def hygiene_records_for_group(data: dict, cls: str, gname: str) -> list:
    block = hygiene_block(data, cls)
    return [r for r in block.get("records", [])
            if (r.get("group") or "未分组") == gname]


def hygiene_group_total(data: dict, cls: str, gname: str) -> int:
    total = 0
    for rec in hygiene_records_for_group(data, cls, gname):
        try:
            total += abs(int(rec.get("score", 0) or 0))
        except (TypeError, ValueError):
            pass
    return total


def hygiene_has_records(data: dict, day: str | None = None) -> bool:
    for block in data.values():
        for rec in block.get("records", []):
            if day is None or rec.get("date") == day:
                return True
    return False


# ===================== XLSX 归档 =====================
def _unique_sheet_name(wb, base: str) -> str:
    base = base[:31]
    if base not in wb.sheetnames:
        return base
    for i in range(2, 100):
        suffix = f"-{i}"
        cand = base[:31 - len(suffix)] + suffix
        if cand not in wb.sheetnames:
            return cand
    return base[:28] + str(int(time.time()))[-3:]


def _open_workbook(path: Path):
    from openpyxl import Workbook, load_workbook
    if path.exists():
        try:
            return load_workbook(path)
        except Exception as exc:
            backup = path.with_name(
                f"{path.stem}_损坏_{time.strftime('%Y%m%d%H%M%S')}{path.suffix}")
            try:
                path.replace(backup)
                log(f"{path.name} 读取失败（{exc}），已备份为 {backup.name}")
            except OSError:
                pass
    return Workbook()


def _write_detail_sheet(ws, title: str, period_text: str,
                        person_rows: list, group_rows: list, value_label: str):
    from openpyxl.styles import Alignment, Font, PatternFill

    dark = "1F3864"
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor=dark)
    title_font = Font(bold=True, size=14)
    section_font = Font(bold=True, size=12, color=dark)

    ws["A1"] = title
    ws["A1"].font = title_font
    ws.merge_cells("A1:G1")
    ws["A2"] = f"周期：{period_text}"
    ws.merge_cells("A2:G2")
    ws["A3"] = "个人统计"
    ws["A3"].font = section_font

    headers = ["班级", "学号", "姓名", "小组", value_label, "记录数"]
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col, value=text)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center")

    row = 5
    for item in person_rows:
        values = [item["cls"], item["sid"], item["name"], item["group"],
                  item["value"], item["count"]]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
        row += 1
    if not person_rows:
        ws.cell(row=row, column=1, value="（本期无个人记录）")
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="小组统计").font = section_font
    row += 1
    group_headers = ["班级", "小组", "人数", value_label, "人均"]
    for col, text in enumerate(group_headers, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center")
    row += 1
    for item in group_rows:
        avg = round(item["value"] / item["count"], 2) if item["count"] else 0
        values = [item["cls"], item["name"], item["count"], item["value"], avg]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
        row += 1
    if not group_rows:
        ws.cell(row=row, column=1, value="（本期无小组记录）")

    widths = {"A": 16, "B": 10, "C": 12, "D": 16, "E": 12, "F": 10, "G": 12}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _update_total_sheet(wb, period_text: str, kind: str,
                        person_rows: list, group_rows: list):
    from openpyxl.styles import Alignment, Font, PatternFill

    headers = ["归档时间", "周期", "类型", "班级", "编号", "名称", "小组", "本期", "累计"]
    if "total" in wb.sheetnames:
        ws = wb["total"]
    else:
        ws = wb.create_sheet("total")
        for col, text in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col, value=text)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F3864")
            cell.alignment = Alignment(horizontal="center")
        for col, width in {"A": 20, "B": 12, "C": 8, "D": 16,
                           "E": 12, "F": 14, "G": 16, "H": 10, "I": 10}.items():
            ws.column_dimensions[col].width = width

    cumulative = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 9:
            continue
        typ, cls, key, _name, _group, _value, total = (
            row[2], row[3], row[4], row[5], row[6], row[7], row[8])
        if typ and cls and key:
            try:
                cumulative[(str(typ), str(cls), str(key))] = int(total or 0)
            except (TypeError, ValueError):
                cumulative[(str(typ), str(cls), str(key))] = 0

    now_text = datetime.now().strftime(TIME_FMT)

    def append(typ, cls, key, name, group, value):
        k = (typ, cls, str(key))
        prev = cumulative.get(k, 0)
        new_total = prev + int(value)
        cumulative[k] = new_total
        ws.append([now_text, period_text, typ, cls, str(key), name, group,
                   int(value), new_total])

    for item in person_rows:
        if not item["value"]:
            continue
        append("个人", item["cls"], item["sid"], item["name"],
               item["group"], item["value"])
    for item in group_rows:
        if not item["value"]:
            continue
        append("小组", item["cls"], item["name"], item["name"],
               item["name"], item["value"])


def _save_workbook(wb, path: Path) -> bool:
    try:
        wb.save(path)
        return True
    except Exception as exc:
        log(f"保存 {path.name} 失败：{exc}")
        return False


def _collect_points(students: dict, groups: dict):
    person_rows, group_rows = [], []
    for cls in list(dict.fromkeys(list(groups) + list(students))):
        stu = students.get(cls, {})
        gmap = student_group_map(groups.get(cls, {}), stu)
        for sid, info in stu.items():
            if not isinstance(info, dict):
                continue
            records = [r for r in student_records(info) if isinstance(r, dict)]
            total = student_total(info)
            if not records and not total:
                continue
            person_rows.append({
                "cls": cls, "sid": sid, "name": info.get("name", ""),
                "group": gmap.get(sid, "未分组"), "value": total,
                "count": len(records),
            })
        for gname, count, total in points_group_rows(students, groups, cls):
            if count and total:
                group_rows.append({"cls": cls, "name": gname,
                                   "count": count, "value": total})
    return person_rows, group_rows


def _collect_hygiene(students: dict, data: dict):
    person_rows, group_rows = [], []
    groups = load_groups()
    for cls, block in data.items():
        stu = students.get(cls, {})
        gmap = student_group_map(groups.get(cls, {}), stu)
        totals, counts = {}, {}
        for rec in block.get("records", []):
            sid = rec.get("sid", "")
            if not sid:
                continue
            try:
                score = abs(int(rec.get("score", 0) or 0))
            except (TypeError, ValueError):
                score = 0
            totals[sid] = totals.get(sid, 0) + score
            counts[sid] = counts.get(sid, 0) + 1
        for sid, total in totals.items():
            if not total:
                continue
            person_rows.append({
                "cls": cls, "sid": sid,
                "name": stu.get(sid, {}).get("name", ""),
                "group": gmap.get(sid, "未分组"), "value": total,
                "count": counts.get(sid, 0),
            })
        for gname, total, cnt in hygiene_group_rows(data, cls):
            if total:
                group_rows.append({"cls": cls, "name": gname,
                                   "count": cnt, "value": total})
    return person_rows, group_rows


def archive_points(students: dict, groups: dict, period_dt: datetime) -> bool:
    wb = _open_workbook(POINTS_BOOK)
    label = period_dt.strftime("%Y-%m-%d")
    week = period_dt.strftime("%G-W%V")
    period_text = f"{label}（{week}）"
    name = _unique_sheet_name(wb, "积分" + period_dt.strftime("%Y%m%d"))
    ws = wb.create_sheet(name)
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        try:
            wb.remove(wb["Sheet"])
        except Exception:
            pass
    person_rows, group_rows = _collect_points(students, groups)
    _write_detail_sheet(ws, f"积分归档 · {period_text}", period_text,
                        person_rows, group_rows, "本期得分")
    _update_total_sheet(wb, period_text, "积分", person_rows, group_rows)
    return _save_workbook(wb, POINTS_BOOK)


def archive_hygiene(students: dict, data: dict, period_dt: datetime) -> bool:
    wb = _open_workbook(HYGIENE_BOOK)
    label = period_dt.strftime("%Y-%m-%d")
    name = _unique_sheet_name(wb, "卫生" + period_dt.strftime("%Y%m%d"))
    ws = wb.create_sheet(name)
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        try:
            wb.remove(wb["Sheet"])
        except Exception:
            pass
    person_rows, group_rows = _collect_hygiene(students, data)
    _write_detail_sheet(ws, f"卫生归档 · {label}", label,
                        person_rows, group_rows, "本期扣分")
    _update_total_sheet(wb, label, "卫生", person_rows, group_rows)
    return _save_workbook(wb, HYGIENE_BOOK)


# ===================== 定时重置 =====================
def _parse_dt(text) -> datetime | None:
    try:
        return datetime.strptime(str(text), TIME_FMT)
    except (TypeError, ValueError):
        return None


def last_noon(now: datetime) -> datetime:
    """最近的“中午 12:00”边界（今天 12 点或昨天 12 点）。"""
    today_noon = datetime.combine(now.date(), NOON)
    return today_noon if now >= today_noon else today_noon - timedelta(days=1)


def last_monday_noon(now: datetime) -> datetime:
    """最近的“周一中午 12:00”边界。"""
    monday_noon = datetime.combine(now.date(), NOON) - timedelta(days=now.weekday())
    if now < monday_noon:
        monday_noon -= timedelta(days=7)
    return monday_noon


def reset_hygiene(period_dt: datetime) -> bool:
    """归档并清空卫生记录；归档失败时不清空，等下次重试。"""
    data = load_hygiene()
    students = load_students()
    if hygiene_has_records(data):
        if not archive_hygiene(students, data, period_dt):
            return False
    for cls, block in data.items():
        block["records"] = []
    save_hygiene(data)
    log(f"卫生已重置（周期 {period_dt.strftime('%Y-%m-%d %H:%M')}）")
    return True


def reset_points(period_dt: datetime) -> bool:
    """归档并清空积分记录；归档失败时不清空，等下次重试。"""
    students = load_students()
    groups = load_groups()
    if point_record_count(students) or any(
            group.get("record")
            for class_groups in groups.values()
            for group in class_groups.values()):
        if not archive_points(students, groups, period_dt):
            return False
    for stu in students.values():
        if not isinstance(stu, dict):
            continue
        for info in stu.values():
            if isinstance(info, dict):
                info["records"] = []
                info["total_score"] = 0
    for class_groups in groups.values():
        for group in class_groups.values():
            if isinstance(group, dict):
                group["record"] = []
                group["total_score"] = 0
    save_students(students)
    save_groups(groups)
    log(f"积分已重置（周期 {period_dt.strftime('%Y-%m-%d %H:%M')}）")
    return True


def _acquire_lock() -> bool:
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - LOCK_FILE.stat().st_mtime > 180:
                LOCK_FILE.unlink()
                return _acquire_lock()
        except OSError:
            pass
        return False
    except OSError:
        return True


def _release_lock():
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


def run_scheduled_resets(now: datetime | None = None) -> list:
    """检查并执行到期的重置，返回本次发生的提示文本列表。"""
    now = now or datetime.now()
    state = _load_json(STATE_FILE, {})
    if not isinstance(state, dict) or not state.get("hygiene_last_reset"):
        # 首次运行只记录基线，避免刚装好就把已有数据清掉
        _save_json(STATE_FILE, {
            "points_last_reset": now.strftime(TIME_FMT),
            "hygiene_last_reset": now.strftime(TIME_FMT),
        })
        return []
    if not _acquire_lock():
        return []
    messages = []
    try:
        state = _load_json(STATE_FILE, {}) or {}
        last_h = _parse_dt(state.get("hygiene_last_reset"))
        due_h = last_noon(now)
        if last_h is not None and due_h > last_h and reset_hygiene(due_h):
            state["hygiene_last_reset"] = due_h.strftime(TIME_FMT)
            _save_json(STATE_FILE, state)
            messages.append(f"卫生已重置并归档（{due_h.strftime('%m-%d %H:%M')}）")

        last_p = _parse_dt(state.get("points_last_reset"))
        due_p = last_monday_noon(now)
        if last_p is not None and due_p > last_p and reset_points(due_p):
            state["points_last_reset"] = due_p.strftime(TIME_FMT)
            _save_json(STATE_FILE, state)
            messages.append(f"积分已重置并归档（{due_p.strftime('%m-%d %H:%M')}）")
    finally:
        _release_lock()
    return messages


def next_reset_text(now: datetime | None = None) -> str:
    """给界面显示的下次重置时间说明。"""
    now = now or datetime.now()
    next_h = last_noon(now) + timedelta(days=1)
    next_p = last_monday_noon(now) + timedelta(days=7)
    return (f"卫生每天中午 12:00 重置（下次 {next_h.strftime('%m-%d %H:%M')}） · "
            f"积分每周一中午 12:00 重置（下次 {next_p.strftime('%m-%d %H:%M')}）")
