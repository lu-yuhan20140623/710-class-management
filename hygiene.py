"""
卫生管理模块
- 卫生扣分记到每个学生头上，数据单独存放在 hygiene_data.txt（不进学生积分）
- 统计按小组汇总，点击小组可查看组员明细与每条记录
- 条形图单向（只有扣分），饼图统计扣分理由分布
- 每天中午 12:00 由后台进程自动归档并重置；每天第一次开机全屏展示
- 周一上午同时展示“上周积分（按小组）”与“卫生（按小组）”，一左一右
"""

import json
import sys
import tkinter as tk
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, ttk

import charts
import score_records as store
from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
    FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_DANGER, FG_OK,
    center_window, fit_geometry,
)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
HYGIENE_FILE = APP_DIR / "hygiene_data.txt"
GROUP_FILE = APP_DIR / "group_data.txt"
STUDENT_FILE = APP_DIR / "student_data.txt"
BOOT_STATE = APP_DIR / "boot_state.json"
FONT = "Microsoft YaHei UI"
DEFAULT_CLASS = "七年级10班"

# 首次使用时的默认卫生扣分理由；之后以历史输入为准
DEFAULT_REASONS = [
    "地面有纸屑", "桌椅摆放不齐", "垃圾桶未倒", "讲台杂乱",
    "卫生角不整洁", "黑板未擦", "窗台有灰", "包干区未打扫",
]


# ===================== 数据读写 =====================
def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return default


def save_data(data: dict):
    store.atomic_write_json(HYGIENE_FILE, data)


def load_data() -> dict:
    data = _load_json(HYGIENE_FILE, {})
    return data if isinstance(data, dict) else {}


def class_block(data: dict, cls: str) -> dict:
    block = data.setdefault(cls, {})
    block.setdefault("reasons", [])
    block.setdefault("records", [])
    return block


def class_names() -> list:
    """卫生数据 / 分组 / 学生数据里出现过的班级，保证下拉框有值。"""
    names = list(load_data())
    for path in (GROUP_FILE, STUDENT_FILE):
        data = _load_json(path, {})
        if isinstance(data, dict):
            for name in data:
                if name not in names:
                    names.append(name)
    return names or [DEFAULT_CLASS]


def group_names(cls: str) -> list:
    groups = _load_json(GROUP_FILE, {}).get(cls, {})
    return list(groups) if isinstance(groups, dict) else []


def preset_reasons(cls: str) -> list:
    """理由预设：历史输入 > 默认理由；最近用过的排在前面。"""
    block = class_block(load_data(), cls)
    seen, result = set(), []
    history = list(block.get("reasons", []))
    history += [r.get("reason", "") for r in reversed(block.get("records", []))]
    for reason in history + DEFAULT_REASONS:
        reason = str(reason).strip()
        if reason and reason not in seen:
            seen.add(reason)
            result.append(reason)
    return result


def _operator_label(operator) -> tuple:
    """把操作人参数规范成 (显示名, 学号)。兼容字符串和 dict 两种写法。"""
    if isinstance(operator, dict):
        name = str(operator.get("name") or "").strip()
        sid = str(operator.get("sid") or "").strip()
        role = str(operator.get("role") or "").strip()
    else:
        name, sid, role = str(operator or "").strip(), "", ""
    label = name
    if role and role != name:
        label = f"{role} {name}".strip()
    return label or "未记录", sid


def add_record(cls: str, sids: list, reason: str, score: int, note: str = "",
               operator=None) -> int:
    """给选中的学生记卫生扣分，返回实际记录人数。"""
    data = load_data()
    block = class_block(data, cls)
    students = store.load_students().get(cls, {})
    gmap = store.student_group_map(store.load_groups().get(cls, {}), students)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d%H%M%S%f")
    by, by_sid = _operator_label(operator)
    count = 0
    for sid in sids:
        info = students.get(sid)
        if not isinstance(info, dict):
            continue
        block["records"].append({
            "id": f"{stamp}-{sid}",
            "sid": sid,
            "name": info.get("name", ""),
            "group": gmap.get(sid, "未分组"),
            "reason": reason,
            "score": abs(int(score)),
            "note": note,
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "by": by,
            "by_sid": by_sid,
        })
        count += 1
    if reason and reason not in block["reasons"]:
        block["reasons"].append(reason)
    save_data(data)
    return count


def revoke_record(cls: str, record: dict) -> bool:
    """撤销一条卫生记录。新记录按 id 匹配，旧记录按内容匹配。"""
    data = load_data()
    block = class_block(data, cls)
    records = block.get("records", [])
    idx = None
    rid = record.get("id")
    if rid:
        idx = next((i for i, r in enumerate(records) if r.get("id") == rid), None)
    if idx is None:
        idx = next((i for i, r in enumerate(records) if r == record), None)
    if idx is None:
        return False
    records.pop(idx)
    save_data(data)
    return True



def totals_by_group(cls: str) -> list:
    """[(小组, 累计扣分)]，扣分多的排前面。"""
    block = class_block(load_data(), cls)
    totals = {name: 0 for name in group_names(cls)}
    for rec in block.get("records", []):
        gname = rec.get("group", "未分组")
        totals[gname] = totals.get(gname, 0) + int(rec.get("score", 0))
    return sorted(totals.items(), key=lambda kv: -kv[1])


def group_summary(cls: str) -> list:
    """[(小组, 累计扣分, 记录数)]，扣分多的排前面。"""
    block = class_block(load_data(), cls)
    totals, counts = {name: 0 for name in group_names(cls)}, defaultdict(int)
    for rec in block.get("records", []):
        gname = rec.get("group", "未分组")
        totals[gname] = totals.get(gname, 0) + int(rec.get("score", 0))
        counts[gname] += 1
    rows = [(g, v, counts.get(g, 0)) for g, v in totals.items()]
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows


def member_totals(cls: str, gname: str) -> list:
    """[(学号, 姓名, 扣分)]：组员明细，无扣分的组员也会列出。"""
    data = load_data()
    return store.hygiene_member_rows(data, store.load_students(), cls, gname)


def group_records(cls: str, gname: str) -> list:
    return store.hygiene_records_for_group(load_data(), cls, gname)


def counts_by_reason(cls: str) -> list:
    block = class_block(load_data(), cls)
    counter = defaultdict(int)
    for rec in block.get("records", []):
        counter[rec.get("reason", "未填写")] += 1
    return sorted(counter.items(), key=lambda kv: -kv[1])


def records_on(day_str: str) -> list:
    """某一天（YYYY-MM-DD）全班的卫生扣分记录：[(班级, 记录)]。"""
    rows = []
    for cls, block in load_data().items():
        for rec in block.get("records", []):
            if rec.get("date") == day_str:
                rows.append((cls, rec))
    rows.sort(key=lambda item: (item[1].get("group", ""), item[1].get("time", "")))
    return rows


# ===================== 全屏展示（卫生 / 积分） =====================
REPORT_BG = "#141422"
REPORT_ROW = "#1e1e34"


def _report_items(day: str | None = None) -> list:
    """[(班级, 小组, 扣分, 记录数)]；day 为空表示当前未重置的全部记录。"""
    agg = {}
    for cls, block in load_data().items():
        for rec in block.get("records", []):
            if day and rec.get("date") != day:
                continue
            gname = rec.get("group") or "未分组"
            key = (cls, gname)
            total, count = agg.get(key, (0, 0))
            try:
                score = abs(int(rec.get("score", 0) or 0))
            except (TypeError, ValueError):
                score = 0
            agg[key] = (total + score, count + 1)
    rows = [(cls, gname, total, count)
            for (cls, gname), (total, count) in agg.items()]
    rows.sort(key=lambda item: -item[2])
    return rows


def _show_group_detail(parent, cls: str, gname: str, kind: str):
    """点击小组后查看组员明细与记录。kind: hygiene / points。"""
    win = tk.Toplevel(parent)
    win.title(f"小组详情 · {gname}")
    win.configure(bg=BG_MAIN)
    win.attributes("-topmost", True)
    tk.Label(win, text=f"{cls} · {gname}", font=(FONT, 14, "bold"),
             bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))

    body = tk.Frame(win, bg=BG_PANEL)
    body.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)
    txt = tk.Text(body, bg=BG_PANEL, fg=FG_TEXT, relief=tk.FLAT,
                  font=("Consolas", 10), wrap=tk.WORD, padx=10, pady=8)
    sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    lines = []
    if kind == "points":
        students = store.load_students()
        groups = store.load_groups()
        total = 0
        for sid, name, score, is_leader in store.points_member_rows(
                students, groups, cls, gname):
            total += score
            lines.append(f"{sid}  {name}{'（组长）' if is_leader else ''}    {score} 分")
            records = store.points_member_records(students, cls, sid)
            if not records:
                lines.append("    （暂无记录）")
            for rec in reversed(records):
                delta = store.record_delta(rec)
                lines.append(f"    {rec.get('time', '')}    {delta:+d}    "
                             f"{rec.get('reason', '')}")
            lines.append("")
        lines.insert(0, f"小组积分：{total} 分\n")
    else:
        members = member_totals(cls, gname)
        lines.append("组员扣分")
        for sid, name, score in members:
            lines.append(f"  {sid}  {name}    -{score} 分")
        if not members:
            lines.append("  （暂无组员）")
        lines.append("")
        lines.append("扣分记录")
        records = group_records(cls, gname)
        if not records:
            lines.append("  （暂无记录）")
        for rec in reversed(records):
            who = f"{rec.get('sid', '')} {rec.get('name', '')}".strip() or "（小组记录）"
            lines.append(f"  {rec.get('time', '')} | {who} | "
                         f"-{int(rec.get('score', 0))} 分 | {rec.get('reason', '')}")

    txt.insert("1.0", "\n".join(lines))
    txt.config(state=tk.DISABLED)
    tk.Button(win, text="关闭", command=win.destroy, bg=BG_IN_CLASS, fg=FG_TEXT,
              activebackground="#4b7b4b", relief=tk.FLAT,
              font=(FONT, 10, "bold"), padx=18, pady=6,
              cursor="hand2").pack(pady=(0, 12))
    win.after_idle(lambda: center_window(win, parent, 680, 520))


def _build_report(parent, title: str, subtitle: str, items: list,
                  kind: str, geometry: str | None = None):
    """通用的全屏/半屏小组报表；点击小组行可下钻组员。"""
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=REPORT_BG)
    if geometry:
        win.geometry(geometry)
    else:
        win.attributes("-fullscreen", True)
    # 不设 -topmost：置顶窗口在 Win+D「显示桌面」后层级会错乱，
    # 再次启动时报表可能盖住主界面或无法正常恢复。
    win.bind("<Escape>", lambda e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)

    compact = bool(geometry)
    padx = 24 if compact else 60
    title_size = 22 if compact else 30
    sub_size = 11 if compact else 16
    row_size = 14 if compact else 18

    head = tk.Frame(win, bg=REPORT_BG)
    head.pack(fill=tk.X, padx=padx, pady=(24 if compact else 36, 8))
    tk.Label(head, text=title, font=(FONT, title_size, "bold"),
             bg=REPORT_BG, fg=FG_ACCENT).pack(side=tk.LEFT)
    tk.Label(head, text=subtitle, font=(FONT, sub_size),
             bg=REPORT_BG, fg=FG_DIM).pack(side=tk.LEFT, padx=18)

    body = tk.Frame(win, bg=REPORT_BG)
    body.pack(fill=tk.BOTH, expand=True, padx=padx, pady=8)
    canvas = tk.Canvas(body, bg=REPORT_BG, highlightthickness=0, bd=0)
    sb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    inner = tk.Frame(canvas, bg=REPORT_BG)
    canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win.bind("<MouseWheel>",
             lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

    if not items:
        empty_text = ("本周暂无卫生扣分记录，继续保持！" if kind == "hygiene"
                      else "本周暂无积分记录，快去给小组加分吧！")
        tk.Label(inner, text=empty_text, font=(FONT, row_size), bg=REPORT_BG,
                 fg=FG_DIM, wraplength=560, justify=tk.CENTER).pack(pady=60)

    multi_class = len({item[0] for item in items}) > 1
    for cls, gname, total, count in items:
        row = tk.Frame(inner, bg=REPORT_ROW, cursor="hand2")
        row.pack(fill=tk.X, pady=5)
        text = f"{cls} · {gname}" if multi_class else gname
        name_label = tk.Label(row, text=text, font=(FONT, row_size, "bold"),
                              bg=REPORT_ROW, fg=FG_TEXT, anchor="w", cursor="hand2")
        name_label.pack(side=tk.LEFT, padx=(18, 12), pady=(14 if not compact else 9))
        count_label = tk.Label(row, text=f"{count} 条", font=(FONT, sub_size),
                               bg=REPORT_ROW, fg=FG_DIM, cursor="hand2")
        count_label.pack(side=tk.LEFT)
        score_label = tk.Label(
            row, text=f"-{total} 分" if kind == "hygiene" else f"{total:+d} 分",
            font=(FONT, row_size, "bold"), bg=REPORT_ROW,
            fg=(FG_DANGER if total else FG_DIM) if kind == "hygiene"
            else (FG_OK if total > 0 else (FG_DANGER if total < 0 else FG_DIM)),
            cursor="hand2")
        score_label.pack(side=tk.RIGHT, padx=18)
        for widget in (row, name_label, count_label, score_label):
            widget.bind("<Button-1>",
                        lambda e, c=cls, g=gname: _show_group_detail(win, c, g, kind))

    foot = tk.Frame(win, bg=REPORT_BG)
    foot.pack(fill=tk.X, padx=padx, pady=(6, 22 if compact else 28))
    hint = "按 Esc 关闭" if not items else "点击小组可查看组员明细 · 按 Esc 关闭"
    tk.Label(foot, text=hint, font=(FONT, 10),
             bg=REPORT_BG, fg=FG_DIM).pack(side=tk.LEFT)
    tk.Button(foot, text="关闭", command=win.destroy,
              bg=BG_IN_CLASS, fg=FG_TEXT, activebackground="#4b7b4b",
              relief=tk.FLAT, font=(FONT, 12, "bold"),
              padx=28, pady=6, cursor="hand2").pack(side=tk.RIGHT)

    reports = getattr(parent, "_fullscreen_reports", None)
    if reports is None:
        reports = []
        setattr(parent, "_fullscreen_reports", reports)
    reports.append(win)

    def _forget(_event):
        if win in reports:
            reports.remove(win)
    win.bind("<Destroy>", lambda e: _forget(e) if e.widget is win else None)
    return win


def show_daily_report(parent, day: str | None = None, geometry: str | None = None):
    """展示卫生扣分（按小组）；无记录时仍弹窗并给出说明。"""
    items = _report_items(day)
    total = sum(item[2] for item in items)
    count = sum(item[3] for item in items)
    if day:
        try:
            day_text = date.fromisoformat(day).strftime("%m月%d日")
        except ValueError:
            day_text = day
        subtitle = (f"{day_text} · 暂无扣分记录" if not items
                    else f"{day_text} · 共 {count} 条 · 合计 -{total} 分")
    else:
        subtitle = (f"截至 {datetime.now().strftime('%m-%d %H:%M')} · "
                    + ("暂无扣分记录" if not items
                       else f"共 {count} 条 · 合计 -{total} 分"))
    return _build_report(parent, "🧹 卫生扣分", subtitle, items, "hygiene", geometry)


def show_points_report(parent, geometry: str | None = None):
    """周一开机展示上周积分（按小组）；无记录时仍弹窗并给出说明。"""
    students = store.load_students()
    groups = store.load_groups()
    items = []
    for cls in list(dict.fromkeys(list(groups) + list(students))):
        for gname, count, total in store.points_group_rows(students, groups, cls):
            items.append((cls, gname, total, count))
    items.sort(key=lambda item: -item[2])
    subtitle = ("按小组 · 暂无积分记录" if not items
                else "按小组 · 每周一中午 12:00 重置")
    return _build_report(parent, "⭐ 小组积分", subtitle, items, "points", geometry)


def maybe_show_first_boot_report(parent) -> None:
    """每天第一次开机展示卫生统计；周一开机同时展示上周积分，两者并排。

    没有数据时也会弹窗，并在报表里写明原因，避免用户以为没触发。
    """
    today = date.today().strftime("%Y-%m-%d")
    try:
        state = _load_json(BOOT_STATE, {})
        if not isinstance(state, dict):
            state = {}
        if state.get("last_boot_date") == today:
            return
        state["last_boot_date"] = today
        BOOT_STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

    if datetime.now().weekday() == 0:
        # 周一：积分统计（左）+ 卫生统计（右）并排
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        half = sw // 2
        show_points_report(parent, geometry=f"{half}x{sh}+0+0")
        show_daily_report(parent, geometry=f"{sw - half}x{sh}+{half}+0")
    else:
        # 其他日子：每天一次卫生统计
        show_daily_report(parent)


# ===================== 卫生管理窗口 =====================
class HygieneWindow:
    """卫生管理：只看卫生扣分，单独统计，不影响学生积分。"""

    def __init__(self, parent, default_class: str = DEFAULT_CLASS, readonly: bool = False,
                 operator=None):
        self.readonly = readonly
        self.operator = operator      # 记录人：{"name", "sid", "role"} 或 "教师"
        self.win = tk.Toplevel(parent)
        self.win.title("卫生管理（只读）· 课程表" if readonly else "卫生管理 · 课程表")
        fit_geometry(self.win, 820, 640, 680, 540)
        self.win.configure(bg=BG_MAIN)

        self.class_list = class_names()
        self.current_class = default_class if default_class in self.class_list else self.class_list[0]
        self._charts = []
        self._row_widgets = []

        self._build()
        self._refresh()
        self.win.bind("<Escape>", lambda e: self.win.destroy())

    # ---------- 界面 ----------
    def _build(self):
        top = tk.Frame(self.win, bg=BG_MAIN)
        top.pack(fill=tk.X, padx=16, pady=(14, 4))
        tk.Label(top, text="卫生管理", font=(FONT, 20, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        tk.Label(top, text="班级", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .pack(side=tk.LEFT, padx=(18, 6))
        self.class_box = ttk.Combobox(top, values=self.class_list, state="readonly",
                                      width=16, font=(FONT, 10))
        self.class_box.set(self.current_class)
        self.class_box.pack(side=tk.LEFT)
        self.class_box.bind("<<ComboboxSelected>>", self._on_class_change)
        self.total_label = tk.Label(top, text="", font=(FONT, 10),
                                    bg=BG_MAIN, fg=FG_DANGER)
        self.total_label.pack(side=tk.LEFT, padx=16)

        tk.Label(self.win, text="仅记录卫生扣分，不计入学生积分统计",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM)\
            .pack(anchor=tk.W, padx=18)

        # 小组累计扣分列表（可滚动）
        body = tk.Frame(self.win, bg=BG_PANEL,
                        highlightbackground=BG_CELL, highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        self.canvas = tk.Canvas(body, bg=BG_PANEL, highlightthickness=0, bd=0,
                                yscrollincrement=40)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG_PANEL)
        self._inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        # 底部按钮
        bar = tk.Frame(self.win, bg=BG_MAIN)
        bar.pack(fill=tk.X, padx=16, pady=(4, 6))
        if not self.readonly:
            self._btn(bar, "🧹 记录扣分", self._open_record, primary=True).pack(side=tk.RIGHT)
            self._btn(bar, "↩ 撤销记录", self._open_revoke).pack(side=tk.RIGHT, padx=8)
        self._btn(bar, "📋 扣分明细", self._show_details).pack(side=tk.RIGHT, padx=8)
        self._btn(bar, "📊 小组扣分图", self._group_chart).pack(side=tk.LEFT)
        self._btn(bar, "🥧 理由分布", self._reason_chart).pack(side=tk.LEFT, padx=8)

        self.status = tk.Label(self.win, text="就绪", font=(FONT, 9),
                               bg=BG_MAIN, fg=FG_DIM, anchor="w")
        self.status.pack(fill=tk.X, padx=18, pady=(0, 12))

    def _btn(self, parent, text, cmd, primary=False):
        bg = BG_IN_CLASS if primary else BG_CELL
        active = "#4b7b4b" if primary else BG_CELL_ALT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=FG_TEXT,
                         activebackground=active, activeforeground=FG_TEXT,
                         relief=tk.FLAT, font=(FONT, 10, "bold" if primary else "normal"),
                         padx=14, pady=6, cursor="hand2")

    def _set_status(self, text, color=FG_DIM):
        self.status.config(text=text, fg=color)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._inner_window, width=event.width)

    def _on_class_change(self, _event=None):
        self.current_class = self.class_box.get()
        self._refresh()

    # ---------- 列表 ----------
    def _refresh(self):
        for w in self._row_widgets:
            w.destroy()
        self._row_widgets = []

        totals = group_summary(self.current_class)
        grand = sum(item[1] for item in totals)
        self.total_label.config(text=f"累计扣分 -{grand} 分" if grand else "累计扣分 0 分")

        if not totals:
            empty = tk.Label(self.inner, text="当前班级还没有小组，请先在学生积分里设置小组",
                             font=(FONT, 10), bg=BG_PANEL, fg=FG_DIM)
            empty.pack(padx=18, pady=16)
            self._row_widgets.append(empty)
            return

        for gname, total, count in totals:
            row = tk.Frame(self.inner, bg=BG_CELL, cursor="hand2")
            row.pack(fill=tk.X, padx=10, pady=4)
            name_label = tk.Label(row, text=gname, font=(FONT, 12), bg=BG_CELL,
                                  fg=FG_TEXT, anchor="w", cursor="hand2")
            name_label.pack(side=tk.LEFT, padx=14, pady=10)
            count_label = tk.Label(row, text=f"{count} 条 · 点击查看组员",
                                   font=(FONT, 9), bg=BG_CELL, fg=FG_DIM,
                                   cursor="hand2")
            count_label.pack(side=tk.LEFT)
            score_label = tk.Label(row, text=f"-{total} 分" if total else "0 分",
                                   font=(FONT, 12, "bold"), bg=BG_CELL,
                                   fg=FG_DANGER if total else FG_DIM, cursor="hand2")
            score_label.pack(side=tk.RIGHT, padx=14)
            for widget in (row, name_label, count_label, score_label):
                widget.bind("<Button-1>",
                            lambda e, g=gname: self._open_member_detail(g))
            self._row_widgets.append(row)

    def _open_member_detail(self, gname):
        """点击小组：查看组员扣分明细。"""
        win = tk.Toplevel(self.win)
        win.title(f"组员明细 · {gname}")
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        tk.Label(win, text=f"{self.current_class} · {gname}", font=(FONT, 13, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 4))

        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)
        txt = tk.Text(body, bg=BG_PANEL, fg=FG_TEXT, relief=tk.FLAT,
                      font=("Consolas", 10), wrap=tk.WORD, padx=10, pady=8)
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lines = ["组员扣分"]
        members = member_totals(self.current_class, gname)
        for sid, name, score in members:
            lines.append(f"  {sid}  {name}    -{score} 分")
        if not members:
            lines.append("  （暂无组员）")
        lines.append("")
        lines.append("扣分记录")
        records = group_records(self.current_class, gname)
        if not records:
            lines.append("  （暂无记录）")
        for rec in reversed(records):
            who = f"{rec.get('sid', '')} {rec.get('name', '')}".strip() or "（小组记录）"
            lines.append(f"  {rec.get('time', '')} | {who} | "
                         f"-{int(rec.get('score', 0))} 分 | {rec.get('reason', '')} | "
                         f"记录人 {rec.get('by') or '未记录'}")
        txt.insert("1.0", "\n".join(lines))
        txt.config(state=tk.DISABLED)

        self._btn(win, "关闭", win.destroy).pack(pady=(0, 12))
        win.after_idle(lambda: center_window(win, self.win, 640, 520))

    # ---------- 撤销记录 ----------
    def _open_revoke(self):
        if self.readonly:
            return
        block = class_block(load_data(), self.current_class)
        records = list(reversed(block.get("records", [])))
        if not records:
            messagebox.showinfo("撤销记录", "当前班级暂无卫生扣分记录", parent=self.win)
            return

        win = tk.Toplevel(self.win)
        win.title("撤销卫生记录")
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.grab_set()
        tk.Label(win, text="撤销卫生记录", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text="选择一条记录后点「撤销」，小组累计扣分立即还原；撤销不可恢复",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack()

        body = tk.Frame(win, bg=BG_PANEL,
                        highlightbackground=BG_CELL, highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 4))
        lst = tk.Listbox(body, height=13, font=("Consolas", 9),
                         bg=BG_PANEL, fg=FG_TEXT, selectbackground="#2f5f8f",
                         selectforeground="#ffffff", relief=tk.FLAT,
                         activestyle="none", exportselection=False)
        sb = ttk.Scrollbar(body, orient="vertical", command=lst.yview)
        xb = ttk.Scrollbar(body, orient="horizontal", command=lst.xview)
        lst.configure(yscrollcommand=sb.set, xscrollcommand=xb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        xb.pack(side=tk.BOTTOM, fill=tk.X)
        lst.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        shown = records[:600]
        for rec in shown:
            who = f"{rec.get('sid', '')} {rec.get('name', '')}".strip() or "（小组记录）"
            lst.insert(tk.END, f"{rec.get('time', '')} | {rec.get('group', '—')} | {who} | "
                               f"-{int(rec.get('score', 0))} 分 | {rec.get('reason', '')} | "
                               f"记录人 {rec.get('by') or '未记录'}")

        err = tk.Label(win, text="", font=(FONT, 9), bg=BG_MAIN, fg=FG_DANGER)
        err.pack()

        def do_revoke():
            sel = lst.curselection()
            if not sel:
                err.config(text="请先选中一条记录")
                return
            rec = shown[sel[0]]
            who = f"{rec.get('sid', '')} {rec.get('name', '')}".strip() or "该记录"
            score = int(rec.get("score", 0))
            if not messagebox.askyesno(
                    "确认撤销",
                    f"确定撤销这条卫生记录？\n\n{rec.get('time', '')} · {who}\n"
                    f"-{score} 分 · {rec.get('reason', '')}\n"
                    f"记录人：{rec.get('by') or '未记录'}",
                    parent=win):
                return
            if revoke_record(self.current_class, rec):
                win.destroy()
                self._refresh()
                self._set_status(f"已撤销 {who} 的卫生扣分 -{score} 分", FG_OK)
            else:
                err.config(text="这条记录已不存在，可能已被撤销")

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=(2, 12))
        self._btn(row, "撤销选中记录", do_revoke, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "关闭", win.destroy).pack(side=tk.LEFT, padx=6)
        lst.bind("<Double-Button-1>", lambda e: do_revoke())
        win.bind("<Escape>", lambda e: win.destroy())
        win.after_idle(lambda: center_window(win, self.win, 760, 480))

    # ---------- 记录扣分 ----------
    def _open_record(self):
        groups = group_names(self.current_class)
        if not groups:
            messagebox.showinfo("提示", "当前班级还没有小组，请先在学生积分里设置小组",
                                parent=self.win)
            return
        students = store.load_students().get(self.current_class, {})
        groups_data = store.load_groups().get(self.current_class, {})

        win = tk.Toplevel(self.win)
        win.title("记录卫生扣分")
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.grab_set()
        tk.Label(win, text="记录卫生扣分", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text="扣分记到每位学生名下，可多选同组学生",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack()

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack(padx=22, pady=4, fill=tk.X)
        form.columnconfigure(1, weight=1)

        def row_label(text, row):
            tk.Label(form, text=text, font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
                .grid(row=row, column=0, sticky="w", pady=6)

        row_label("小组", 0)
        group_box = ttk.Combobox(form, values=groups, state="readonly",
                                 width=22, font=(FONT, 10))
        group_box.current(0)
        group_box.grid(row=0, column=1, sticky="w", pady=6)

        row_label("学生", 1)
        stu_frame = tk.Frame(form, bg=BG_PANEL,
                             highlightbackground=BG_CELL, highlightthickness=1)
        stu_frame.grid(row=1, column=1, sticky="we", pady=6)
        stu_list = tk.Listbox(stu_frame, height=6, selectmode=tk.EXTENDED,
                              font=(FONT, 10), bg=BG_PANEL, fg=FG_TEXT,
                              selectbackground="#2f5f8f", selectforeground=FG_TEXT,
                              relief=tk.FLAT, activestyle="none",
                              exportselection=False)
        stu_sb = ttk.Scrollbar(stu_frame, orient="vertical", command=stu_list.yview)
        stu_list.configure(yscrollcommand=stu_sb.set)
        stu_sb.pack(side=tk.RIGHT, fill=tk.Y)
        stu_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        stu_list._sids = []

        def fill_students(_event=None):
            stu_list.delete(0, tk.END)
            group = groups_data.get(group_box.get(), {})
            sids = [s for s in group.get("members", []) if s in students]
            stu_list._sids = sids
            for sid in sids:
                stu_list.insert(tk.END, f"{sid}  {students[sid]['name']}")
            if sids:
                stu_list.select_set(0, tk.END)

        group_box.bind("<<ComboboxSelected>>", fill_students)
        fill_students()

        row_label("理由", 2)
        reason_box = ttk.Combobox(form, values=preset_reasons(self.current_class),
                                  width=24, font=(FONT, 10))
        reason_box.current(0)
        reason_box.grid(row=2, column=1, sticky="w", pady=6)

        row_label("扣分", 3)
        score_entry = tk.Entry(form, width=10, font=(FONT, 10), bg=BG_CELL,
                               fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)
        score_entry.insert(0, "1")
        score_entry.grid(row=3, column=1, sticky="w", pady=6, ipady=3)

        tk.Label(win, text="理由可直接输入新内容，会保存为下次的预设",
                 font=(FONT, 8), bg=BG_MAIN, fg=FG_DIM).pack(pady=(4, 0))

        err = tk.Label(win, text="", font=(FONT, 9), bg=BG_MAIN, fg=FG_DANGER)
        err.pack(pady=4)

        def submit():
            reason = reason_box.get().strip()
            score_text = score_entry.get().strip()
            picked = [stu_list._sids[i] for i in stu_list.curselection()
                      if i < len(stu_list._sids)]
            if not picked:
                err.config(text="请选择至少一名学生")
                return
            if not reason:
                err.config(text="请填写扣分理由")
                return
            try:
                score = abs(int(score_text))
            except ValueError:
                err.config(text="扣分必须是整数")
                return
            if score <= 0:
                err.config(text="扣分必须大于 0")
                return
            count = add_record(self.current_class, picked, reason, score,
                               operator=self.operator)
            win.destroy()
            self._refresh()
            self._set_status(f"{count} 名学生卫生扣 {score} 分 · {reason}", FG_DANGER)

        rows = tk.Frame(win, bg=BG_MAIN)
        rows.pack(pady=(4, 14))
        self._btn(rows, "提交", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(rows, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: submit())
        win.after_idle(lambda: center_window(win, self.win, 500, 540))

    # ---------- 明细 ----------
    def _show_details(self):
        block = class_block(load_data(), self.current_class)
        records = list(reversed(block.get("records", [])))
        if not records:
            messagebox.showinfo("扣分明细", "当前班级暂无卫生扣分记录", parent=self.win)
            return
        lines = []
        for rec in records[:600]:
            who = f"{rec.get('sid', '')} {rec.get('name', '')}".strip() or "（小组记录）"
            lines.append(f"{rec.get('time', '')} | {rec.get('group', '—')} | {who} | "
                         f"-{int(rec.get('score', 0))} 分 | {rec.get('reason', '')} | "
                         f"记录人 {rec.get('by') or '未记录'}")
        self._text_window(f"卫生扣分明细 · {self.current_class}", "\n".join(lines))

    def _text_window(self, title, content):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        tk.Label(win, text=title, font=(FONT, 12, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(12, 6))
        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)
        txt = tk.Text(body, bg=BG_PANEL, fg=FG_TEXT, relief=tk.FLAT,
                      font=("Consolas", 10), wrap=tk.NONE)
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        txt.insert("1.0", content)
        txt.config(state=tk.DISABLED)
        self._btn(win, "关闭", win.destroy).pack(pady=(4, 12))
        win.after_idle(lambda: center_window(win, self.win, 720, 480))

    # ---------- 图表 ----------
    def _chart_window(self, title, width, height, draw):
        old = getattr(self, "_chart_win", None)
        if old is not None:
            try:
                if old.winfo_exists():
                    old.destroy()
            except tk.TclError:
                pass
        win = tk.Toplevel(self.win)
        self._chart_win = win
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        tk.Label(win, text=title, font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(12, 4))

        outer = tk.Frame(win, bg=BG_PANEL)
        outer.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        cv = tk.Canvas(outer, bg=BG_PANEL, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=cv.xview)
        cv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        cv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        body = tk.Frame(cv, bg=BG_PANEL)
        cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))

        self._btn(win, "关闭", win.destroy).pack(pady=(0, 12))
        draw(body)
        win.after_idle(lambda: center_window(win, self.win, width, height)
                       if win.winfo_exists() else None)

    def _group_chart(self):
        rows = totals_by_group(self.current_class)
        if not any(v for _, v in rows):
            messagebox.showinfo("提示", "当前班级暂无卫生扣分记录", parent=self.win)
            return
        title = f"卫生扣分 · 小组对比 · {self.current_class}"
        self._chart_window(title, 760, 120 + 34 * len(rows),
                           lambda body: charts.deduction_bar(
                               body, totals_by_group(self.current_class), width=720)
                           .pack(fill=tk.BOTH, expand=True))

    def _reason_chart(self):
        data = counts_by_reason(self.current_class)
        if not data:
            messagebox.showinfo("提示", "当前班级暂无卫生扣分记录", parent=self.win)
            return
        title = f"卫生扣分理由分布 · {self.current_class}"
        self._chart_window(title, 780, 480,
                           lambda body: charts.pie_chart(
                               body, counts_by_reason(self.current_class))
                           .pack(fill=tk.BOTH, expand=True))
