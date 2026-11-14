"""积分台账导出（XLSX，openpyxl）。

- export_class：班级台账（总榜 / 个人明细 / 分项统计 / 岗位履职）
- export_student：个人台账（明细 / 分项汇总 / 履职）
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import store


def _style_header(ws, headers):
    from openpyxl.styles import Font, PatternFill
    ws.append(headers)
    fill = PatternFill("solid", fgColor="DCE6F1")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
    for i, title in enumerate(headers, start=1):
        width = 20 if title in ("事由", "评语") else 12
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width


def _student_totals(rows: list) -> dict:
    totals = defaultdict(lambda: {"add": 0, "sub": 0, "name": "", "group": ""})
    for r in rows:
        key = r.get("sid", "")
        item = totals[key]
        item["name"] = r.get("name", item["name"])
        item["group"] = r.get("group", item["group"])
        delta = int(r.get("delta", 0))
        if delta >= 0:
            item["add"] += delta
        else:
            item["sub"] += delta
    return totals


def _category_totals(rows: list) -> dict:
    """{学生: {分项: 分值}}"""
    data = defaultdict(lambda: defaultdict(int))
    for r in rows:
        data[r.get("name", "")][r.get("category", "其他")] += int(r.get("delta", 0))
    return data


def export_class(cls: str, path) -> str:
    import openpyxl

    rows = store.points(cls)
    duties = store.duties(cls)
    wb = openpyxl.Workbook()

    # 1) 班级总榜
    ws = wb.active
    ws.title = "班级总榜"
    _style_header(ws, ["排名", "学号", "姓名", "小组", "累计加分", "累计扣分", "总分"])
    totals = _student_totals(rows)
    ranking = sorted(totals.items(), key=lambda kv: kv[1]["add"] + kv[1]["sub"], reverse=True)
    for i, (sid, item) in enumerate(ranking, start=1):
        ws.append([i, sid, item["name"], item["group"], item["add"], item["sub"],
                   item["add"] + item["sub"]])

    # 2) 个人明细
    ws = wb.create_sheet("个人明细")
    _style_header(ws, ["时间", "周次", "学号", "姓名", "小组", "分值", "事由", "分项"])
    for r in sorted(rows, key=lambda x: x.get("ts", "")):
        ws.append([r.get("ts", ""), r.get("week", ""), r.get("sid", ""), r.get("name", ""),
                   r.get("group", ""), int(r.get("delta", 0)), r.get("reason", ""),
                   r.get("category", "其他")])

    # 3) 分项统计
    ws = wb.create_sheet("分项统计")
    cats = sorted({r.get("category", "其他") for r in rows} or {"其他"})
    _style_header(ws, ["学号", "姓名"] + cats + ["合计"])
    cat_data = _category_totals(rows)
    sid_of = {r.get("name", ""): r.get("sid", "") for r in rows}
    for sid, item in ranking:
        counts = cat_data.get(item["name"], {})
        values = [counts.get(c, 0) for c in cats]
        ws.append([sid, item["name"]] + values + [sum(values)])

    # 4) 岗位履职
    ws = wb.create_sheet("岗位履职")
    _style_header(ws, ["时间", "姓名", "岗位", "类型", "评分", "评语", "评价人"])
    for r in duties:
        ws.append([r.get("ts", ""), r.get("name", ""), r.get("duty", ""),
                   r.get("kind", ""), int(r.get("score", 0)),
                   r.get("comment", ""), r.get("evaluator", "")])

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return str(out)


def export_student(cls: str, sid: str, path) -> str:
    import openpyxl

    rows = [r for r in store.points(cls) if r.get("sid") == sid]
    duties = [r for r in store.duties(cls) if r.get("sid") == sid]
    name = rows[0].get("name", sid) if rows else sid

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "个人明细"
    _style_header(ws, ["时间", "周次", "分值", "事由", "分项", "合计"])
    running = 0
    for r in sorted(rows, key=lambda x: x.get("ts", "")):
        running += int(r.get("delta", 0))
        ws.append([r.get("ts", ""), r.get("week", ""), int(r.get("delta", 0)),
                   r.get("reason", ""), r.get("category", "其他"), running])

    ws = wb.create_sheet("分项汇总")
    _style_header(ws, ["分项", "累计得分"])
    for cat, value in sorted(_category_totals(rows).get(name, {}).items(),
                             key=lambda kv: kv[1], reverse=True):
        ws.append([cat, value])
    ws.append(["合计", running])

    ws = wb.create_sheet("岗位履职")
    _style_header(ws, ["时间", "岗位", "类型", "评分", "评语", "评价人"])
    for r in duties:
        ws.append([r.get("ts", ""), r.get("duty", ""), r.get("kind", ""),
                   int(r.get("score", 0)), r.get("comment", ""), r.get("evaluator", "")])

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return str(out)


def default_name(cls: str, prefix: str = "积分台账") -> str:
    return f"{cls}_{prefix}_{datetime.now():%Y%m%d_%H%M}.xlsx"
