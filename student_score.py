"""
学生积分模块（由 740.6.py 修正后嵌入课程表）
- 配色 / 字体与 ui.py 保持一致
- 数据文件沿用 740.6.py 的格式，可直接复用已有数据
- 修正：窗口参数写错、Configure 绑定泄漏、动画回调作用于已销毁控件、
  归档浅拷贝、批量导入无法多行输入、底部按钮绝对定位、初始列数失效、周次 W00
"""

import json
import random
import sys
import time
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import charts
import score_records as store
from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
    FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_DANGER, FG_OK,
    center_window,
    fit_geometry,
    dpi_scale,
)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
CLASS_FILE = APP_DIR / "class_data.txt"
STUDENT_FILE = APP_DIR / "student_data.txt"
GROUP_FILE = APP_DIR / "group_data.txt"
WEEKLY_ARCHIVE = APP_DIR / "weekly_score_archive.txt"
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_DIR = APP_DIR / "logs"
OP_LOG = LOG_DIR / "score_operations.log"

FONT = "Microsoft YaHei UI"
CARD_BG = BG_CELL
CARD_SELECT = "#2f5f8f"      # 选中：与强调色 FG_ACCENT 同系的深蓝
CHECK_BG = "#2f5f8f"         # 评价打分里勾选行的蓝色高亮底色
CARD_FLASH = "#d4a017"       # 随机点名滚动/定格时的金色高亮
CARD_W = 128                 # 卡片宽度 + 间距，用于计算列数
LOW_SCORE_LIMIT = 60         # 默认预警阈值，可在 settings.json 里覆盖


def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return default


def _save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_settings() -> dict:
    """读取 settings.json；缺失时写入默认值，方便老师直接改阈值。"""
    data = None
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = None
    if not isinstance(data, dict):
        data = {"low_score_limit": LOW_SCORE_LIMIT}
        try:
            _save_json(SETTINGS_FILE, data)
        except OSError:
            pass
    data.setdefault("low_score_limit", LOW_SCORE_LIMIT)
    return data


def low_score_limit() -> int:
    try:
        return int(load_settings()["low_score_limit"])
    except (TypeError, ValueError, KeyError):
        return LOW_SCORE_LIMIT


def custom_reasons() -> list:
    """老师自己输入过的理由（保存在 settings.json，之后可直接选用）。"""
    vals = load_settings().get("custom_reasons", [])
    return [str(v) for v in vals] if isinstance(vals, list) else []


def add_custom_reason(reason: str):
    reason = reason.strip()
    if not reason:
        return
    data = load_settings()
    vals = data.get("custom_reasons", [])
    if not isinstance(vals, list):
        vals = []
    if reason not in vals:
        vals.append(reason)
        data["custom_reasons"] = vals
        try:
            _save_json(SETTINGS_FILE, data)
        except OSError:
            pass


# ===================== 分类奖惩理由 =====================
reason_categories = {
    # 放在第一位：打分窗口默认选中「常用」，常用理由直接置顶
    "常用": [
        "积极发言", "作业未交", "早读表扬", "帮助同学",
        "认真听讲", "主动提问", "作业优秀", "课堂纪律好",
        "迟到早退", "上课讲话", "作业抄袭", "值日敷衍",
    ],
    "课堂表现": [
        "积极发言", "认真听讲", "勤于思考", "专注课堂", "主动提问",
        "思路清晰", "配合互动", "笔记工整", "踊跃作答", "紧跟思路",
        "安静听课", "坐姿端正", "不开小差", "用心聆听", "大胆发言",
        "参与讨论", "表达流畅", "理解迅速", "勤于动笔", "态度认真",
        "扰乱课堂", "随意讲话", "低头走神", "东张西望", "交头接耳",
        "玩弄物品", "趴在桌面", "拒绝互动", "沉默不语", "大声喧哗",
        "打断发言", "坐姿散漫", "课本乱放", "眼神游离", "敷衍听课",
        "私下打闹", "故意捣乱", "嘲笑他人", "无视纪律", "低头玩耍",
        "抢答起哄", "沉默抵触", "摆弄文具", "望向窗外", "闭目休憩",
        "课堂插话", "动作过多", "心态浮躁", "消极参与", "不愿思考",
        "书写潦草", "笔记缺失", "课本空白", "练习拖延", "态度散漫",
        "顶撞师长", "不服管教", "故作姿态", "敷衍应付", "注意力散"
    ],
    "日常纪律": [
        "按时到校", "遵守作息", "路队整齐", "行走有序", "严守班规",
        "准时进班", "列队规范", "慢行靠右", "遵守秩序", "自律自觉",
        "迟到早退", "无故缺勤", "路队打闹", "奔跑追逐", "插队拥挤",
        "擅自离队", "拖沓慢行", "无视队列", "大声吵闹", "四处游荡",
        "佩戴红领巾", "校服整洁", "仪容得体", "穿戴规范", "仪表大方",
        "未戴领巾", "校服凌乱", "衣冠不整", "配饰杂乱", "造型怪异",
        "自习安静", "静心自学", "合理作息", "午休安稳", "恪守时间",
        "自习喧哗", "随意走动", "午休打闹", "熬夜犯困", "作息混乱",
        "严守门禁", "出入合规", "听从管理", "行为规范", "举止文明",
        "擅自外出", "翻越围栏", "不听劝阻", "行为放纵", "举止粗鲁"
    ],
    "卫生劳动": [
        "认真值日", "清扫彻底", "捡拾垃圾", "桌面整洁", "摆放整齐",
        "擦拭干净", "整理桌椅", "维护卫生", "主动劳动", "任劳任怨",
        "值日敷衍", "垃圾乱扔", "桌面脏乱", "杂物堆积", "地面脏乱",
        "逃避值日", "偷懒耍滑", "随地丢纸", "污水乱洒", "工具乱摆",
        "爱护公物", "轻拿轻放", "细心呵护", "维护设施", "珍惜物品",
        "损坏桌椅", "刻画桌面", "乱涂乱画", "破坏教具", "损毁公物",
        "节约用水", "节约用电", "爱惜粮食", "合理用餐", "垃圾分类",
        "浪费水源", "长灯不熄", "剩饭剩菜", "挑食厌食", "垃圾混放",
        "养护绿植", "打理角落", "清理窗台", "清扫走廊", "整理书柜",
        "踩踏绿植", "污损墙面", "窗台积灰", "走廊乱堆", "书籍乱摆"
    ],
    "文明礼仪": [
        "主动问好", "礼貌待人", "用语文明", "友善相处", "懂得谦让",
        "尊重他人", "心怀感恩", "举止谦和", "谈吐得体", "热心助人",
        "出言不逊", "言语粗俗", "顶撞同学", "斤斤计较", "恶意嘲讽",
        "目中无人", "态度傲慢", "恶语相向", "挑拨离间", "孤立他人",
        "团结同学", "互帮互助", "化解矛盾", "包容他人", "和睦相处",
        "发生争执", "动手打闹", "拉帮结派", "排挤同伴", "恶意争执",
        "升旗肃立", "庄严肃穆", "心怀敬畏", "行止规范", "注目行礼",
        "升旗乱动", "嬉笑打闹", "站姿歪斜", "东倒西歪", "态度轻慢",
        "遵守礼规", "公共守礼", "轻声慢行", "顾及他人", "文明就餐",
        "就餐喧哗", "敲碗打闹", "大声说笑", "影响他人", "举止失礼"
    ],
    "学业任务": [
        "作业准时", "书写工整", "错题订正", "勤于阅读", "练习认真",
        "预习新知", "复习巩固", "答题规范", "卷面整洁", "按时上交",
        "迟交作业", "漏做作业", "作业抄袭", "书写潦草", "错题不改",
        "拒绝阅读", "练习空白", "格式混乱", "拖延上交", "敷衍作答",
        "勤学苦练", "坚持打卡", "主动拓展", "钻研难题", "查漏补缺",
        "畏惧难题", "半途而废", "拒绝拓展", "不愿练习", "学习懈怠",
        "笔记完整", "资料齐全", "规划学习", "稳步进步", "态度端正",
        "笔记残缺", "资料丢失", "毫无规划", "成绩下滑", "厌学弃学",
        "积极参赛", "认真创作", "用心书写", "总结反思", "查漏补强",
        "逃避竞赛", "创作敷衍", "书写应付", "拒绝反思", "不求上进"
    ]
}


# ===================== 学生积分窗口 =====================
class StudentScoreWindow:
    """嵌入课程表的“学生积分”窗口：班级切换 + 学生卡片 + 评价打分 + 更多功能。"""

    def __init__(self, parent, default_class: str = "七年级10班", readonly: bool = False):
        self.readonly = readonly
        self.win = tk.Toplevel(parent)
        self.win.title("学生积分（只读）· 课程表" if readonly else "学生积分 · 课程表")
        fit_geometry(self.win, 1000, 640, 820, 560)
        self.win.configure(bg=BG_MAIN)
        self.win._readonly = readonly      # 供悬浮球判断是否需要切换模式

        # ---- 数据 ----
        self.class_list = _load_json(CLASS_FILE, []) or []
        self.all_students = _load_json(STUDENT_FILE, {}) or {}
        self.group_data = _load_json(GROUP_FILE, {}) or {}
        self.week_archive = defaultdict(list, _load_json(WEEKLY_ARCHIVE, {}) or {})

        if default_class not in self.class_list:
            self.class_list.append(default_class)

        self.current_class = default_class
        for c in self.class_list:
            self.all_students.setdefault(c, {})
            self.group_data.setdefault(c, {})
            for info in self.all_students.get(c, {}).values():
                if isinstance(info, dict):
                    info.setdefault("records", [])

        # 积分按“人”记录：把旧版按小组的记录迁移到组长名下（只读模式只在内存里迁移）
        migrated = store.migrate_group_records(self.all_students, self.group_data)
        changed = store.sync_group_totals(self.all_students, self.group_data)
        if not readonly and (migrated or changed):
            self._save_all()

        self.view_mode = "group"          # 默认按小组展示
        self.selected_ids = set()
        self._cards = {}
        self._group_cards = {}
        self._anim_jobs = {}
        self._layout_job = None
        self._score_win = None
        self._charts = []        # 已打开的统计图表窗口，数据变化时实时重绘

        self._build()
        self._sync_view_ui()
        self._render_cards()
        if readonly:
            self._set_status("只读模式：可查看小组积分与记录，无法修改", FG_WARN)
        self.win.bind("<Escape>", lambda e: self.win.destroy())

    # ========== 界面构建 ==========
    def _build(self):
        # 顶部：标题 + 班级切换 + 人数
        top = tk.Frame(self.win, bg=BG_MAIN)
        top.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(top, text="学生积分", font=(FONT, 20, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(side=tk.LEFT)
        tk.Label(top, text="班级", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .pack(side=tk.LEFT, padx=(18, 6))
        self.class_box = ttk.Combobox(top, values=self.class_list, state="readonly",
                                      width=16, font=(FONT, 10))
        self.class_box.set(self.current_class)
        self.class_box.pack(side=tk.LEFT)
        self.class_box.bind("<<ComboboxSelected>>", self._on_class_change)

        self.count_label = tk.Label(top, text="", font=(FONT, 10),
                                    bg=BG_MAIN, fg=FG_DIM)
        self.count_label.pack(side=tk.LEFT, padx=14)

        self._new_class_btn = self._btn(top, "+ 新建班级", self._create_class)
        self._new_class_btn.pack(side=tk.RIGHT)
        self.view_student_btn = self._btn(top, "按学生", lambda: self._switch_view("student"))
        self.view_student_btn.pack(side=tk.RIGHT, padx=(4, 8))
        self.view_group_btn = self._btn(top, "按小组", lambda: self._switch_view("group"))
        self.view_group_btn.pack(side=tk.RIGHT)
        if self.readonly:
            self._new_class_btn.config(state=tk.DISABLED)

        # 中部：可滚动卡片区
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
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        # 状态栏
        status_bar = tk.Frame(self.win, bg=BG_MAIN)
        status_bar.pack(fill=tk.X, padx=16)
        self.status_label = tk.Label(status_bar, text="就绪", font=(FONT, 9),
                                     bg=BG_MAIN, fg=FG_DIM, anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.sel_label = tk.Label(status_bar, text="", font=(FONT, 9),
                                  bg=BG_MAIN, fg=FG_ACCENT)
        self.sel_label.pack(side=tk.RIGHT)

        # 底部操作栏（pack 布局，窗口缩放不会丢按钮）
        bar = tk.Frame(self.win, bg=BG_MAIN)
        bar.pack(fill=tk.X, padx=16, pady=(6, 14))
        self._more_btn = self._btn(bar, "更多功能 ▾", self._open_more_menu)
        self._more_btn.pack(side=tk.LEFT)
        self._select_all_btn = self._btn(bar, "全选", self._select_all)
        self._invert_btn = self._btn(bar, "反选", self._invert_select)
        self.score_btn = self._btn(bar, "评价打分", self._open_score, primary=True)
        self.score_btn.pack(side=tk.RIGHT)
        self._btn(bar, "随机点名", self._random_call).pack(side=tk.RIGHT, padx=8)

    def _btn(self, parent, text, cmd, primary=False):
        bg = BG_IN_CLASS if primary else BG_CELL
        active = "#4b7b4b" if primary else BG_CELL_ALT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=FG_TEXT,
                         activebackground=active, activeforeground=FG_TEXT,
                         relief=tk.FLAT, font=(FONT, 10, "bold" if primary else "normal"),
                         padx=14, pady=6, cursor="hand2")

    # ========== 卡片渲染 / 布局 ==========
    def _card_text(self, sid, info, group=None):
        # 分成 4 行，避免「组名 + 积分」太长被卡片宽度裁掉
        if group:
            gname, is_leader, total = group
            return f"{sid}\n{info['name']}\n{'★' if is_leader else ''}{gname}\n{total}分"
        return f"{sid}\n{info['name']}\n未分组\n—"

    def _groups(self):
        return self.group_data.setdefault(self.current_class, {})

    def _group_map(self):
        """当前班级：学号 → (小组名, 是否组长, 个人积分)。"""
        stu = self.all_students.get(self.current_class, {})
        result = {}
        for gname, group in self._groups().items():
            for sid in group.get("members", []):
                if sid in stu and sid not in result:
                    result[sid] = (gname, group.get("leader") == sid,
                                   store.student_total(stu[sid]))
        return result

    def _selected_groups(self):
        """选中学生对应的小组（按小组顺序去重）。"""
        stu = self.all_students.get(self.current_class, {})
        chosen = {sid for sid in self.selected_ids if sid in stu}
        return [gname for gname, group in self._groups().items()
                if chosen & set(group.get("members", []))]

    def _iter_records(self):
        """遍历当前班级所有个人积分记录：(小组, 学号, 姓名, 记录)。"""
        return store.iter_point_records(self.all_students, self.group_data,
                                        self.current_class)

    def _switch_view(self, mode):
        if mode == self.view_mode:
            return
        self.view_mode = mode
        self.selected_ids.clear()
        self._sync_view_ui()
        self._render_cards()

    def _sync_view_ui(self):
        active, normal = BG_IN_CLASS, BG_CELL
        self.view_group_btn.config(
            bg=active if self.view_mode == "group" else normal)
        self.view_student_btn.config(
            bg=active if self.view_mode == "student" else normal)
        if self.view_mode == "group":
            self._select_all_btn.pack_forget()
            self._invert_btn.pack_forget()
            self.score_btn.config(state=tk.DISABLED if self.readonly else tk.NORMAL)
        else:
            self._select_all_btn.pack(side=tk.LEFT, padx=8)
            self._invert_btn.pack(side=tk.LEFT)
            self.score_btn.config(state=tk.DISABLED if self.readonly else tk.NORMAL)

    def _can_write(self) -> bool:
        if self.readonly:
            self._set_status("只读模式：无法修改积分数据", FG_WARN)
            return False
        return True

    def _render_cards(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self._cards.clear()
        self._group_cards.clear()
        self._anim_jobs.clear()

        if self.view_mode == "group":
            self._render_group_cards()
        else:
            group_map = self._group_map()
            for sid, info in self.all_students.get(self.current_class, {}).items():
                card = tk.Button(self.inner, text=self._card_text(sid, info, group_map.get(sid)),
                                 font=(FONT, 10), bg=CARD_BG, fg=FG_TEXT,
                                 activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                                 relief=tk.FLAT, cursor="hand2", justify=tk.CENTER,
                                 wraplength=120, padx=6, pady=6,
                                 command=lambda s=sid: self._toggle_select(s))
                card.bind("<MouseWheel>", self._on_wheel)
                self._cards[sid] = card

            # 选中集合里可能残留已删除的学生
            self.selected_ids &= set(self._cards)
            for sid in self.selected_ids:
                self._cards[sid].config(bg=CARD_SELECT)

        self._update_count()
        self._schedule_layout()
        self._refresh_charts()

    def _render_group_cards(self):
        groups = self._groups()
        if not groups:
            tk.Label(self.inner, text="暂未分组", font=(FONT, 12),
                     bg=BG_PANEL, fg=FG_DIM).grid(row=0, column=0,
                                                  padx=24, pady=24, sticky="w")
            return

        stu = self.all_students.get(self.current_class, {})
        for gname, group in groups.items():
            members = [s for s in group.get("members", []) if s in stu]
            leader = group.get("leader", "")
            leader_name = stu[leader]["name"] if leader in stu else "未指定"
            total = store.group_total(group, stu)
            text = f"{gname}\n{len(members)}人 · {total}分\n组长 {leader_name}"
            card = tk.Button(self.inner, text=text, font=(FONT, 11),
                             bg=CARD_BG, fg=FG_TEXT,
                             activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                             relief=tk.FLAT, cursor="hand2", justify=tk.CENTER,
                             wraplength=140, padx=8, pady=6,
                             command=lambda g=gname: self._open_group_detail(g))
            card.bind("<MouseWheel>", self._on_wheel)
            self._group_cards[gname] = card

    def _refresh_scores(self):
        """只刷新卡片上的积分文本，不重建控件（实时生效、不闪屏）。"""
        stu = self.all_students.get(self.current_class, {})
        if self.view_mode == "group":
            groups = self._groups()
            for gname, card in self._group_cards.items():
                if not card.winfo_exists():
                    continue
                group = groups.get(gname)
                if not group:
                    continue
                members = [s for s in group.get("members", []) if s in stu]
                leader = group.get("leader", "")
                leader_name = stu[leader]["name"] if leader in stu else "未指定"
                total = store.group_total(group, stu)
                card.config(text=f"{gname}\n{len(members)}人 · {total}分\n组长 {leader_name}")
        else:
            group_map = self._group_map()
            for sid, card in self._cards.items():
                info = stu.get(sid)
                if not info or not card.winfo_exists():
                    continue
                card.config(text=self._card_text(sid, info, group_map.get(sid)))
        self._update_count()
        self._refresh_charts()

    def _open_group_detail(self, gname):
        """查看小组：组员各自的积分与每次得失记录。"""
        group = self._groups().get(gname)
        if not group:
            return
        stu = self.all_students.get(self.current_class, {})
        members = [s for s in group.get("members", []) if s in stu]
        leader = group.get("leader", "")
        leader_text = f"{leader} {stu[leader]['name']}" if leader in stu else "未指定"
        total = store.group_total(group, stu)

        win = self._dialog(f"小组详情 · {gname}", 680, 620)
        tk.Label(win, text=gname, font=(FONT, 16, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text=f"组长：{leader_text}    人数：{len(members)}    小组积分：{total} 分",
                 font=(FONT, 10), bg=BG_MAIN, fg=FG_TEXT).pack()
        tk.Label(win, text="积分记在个人名下，小组积分 = 组员积分之和",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack(pady=(2, 0))

        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=10)
        txt = tk.Text(body, font=("Consolas", 10), bg=BG_PANEL, fg=FG_TEXT,
                      relief=tk.FLAT, padx=10, pady=8, wrap=tk.WORD)
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        if not members:
            txt.insert(tk.END, "（无成员）")
        for sid in members:
            info = stu[sid]
            mark = "（组长）" if sid == leader else ""
            txt.insert(tk.END, f"{sid}  {info['name']}{mark}    "
                               f"{store.student_total(info)} 分\n")
            records = store.student_records(info)
            if not records:
                txt.insert(tk.END, "    （暂无记录）\n")
            for r in reversed(records):
                sign = "+" if store.record_delta(r) >= 0 else "-"
                txt.insert(tk.END,
                           f"    {r.get('time', '')}    {sign}{abs(int(r.get('score', 0)))} 分"
                           f"    {r.get('reason', '')}\n")
            txt.insert(tk.END, "\n")
        txt.config(state=tk.DISABLED)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(fill=tk.X, padx=18, pady=12)
        if not self.readonly:
            self._btn(row, "为本组学生打分",
                      lambda: (win.destroy(), self._open_score(target_students=members)),
                      primary=True).pack(side=tk.LEFT)
        self._btn(row, "关闭", win.destroy).pack(side=tk.RIGHT)

    def _schedule_layout(self):
        if self._layout_job:
            try:
                self.win.after_cancel(self._layout_job)
            except Exception:
                pass
        self._layout_job = self.win.after(60, self._apply_layout)

    def _ideal_card_width(self) -> int:
        """按最长文本估算卡片宽度：组名/姓名越长卡片越宽，避免被裁切。"""
        import tkinter.font as tkfont
        try:
            if self.view_mode == "group":
                font = tkfont.Font(font=(FONT, 11))
                texts = list(self._groups()) or ["暂未分组"]
            else:
                font = tkfont.Font(font=(FONT, 10))
                stu = self.all_students.get(self.current_class, {})
                gmap = self._group_map()
                texts = [info.get("name", "") for info in stu.values()]
                texts += [item[0] for item in gmap.values()]
                texts = texts or ["未分组"]
            widest = max(font.measure(t) for t in texts)
            return max(110, min(260, widest + 46))
        except Exception:
            return int(CARD_W)

    def _apply_layout(self):
        self._layout_job = None
        if not self.win.winfo_exists():
            return
        avail = max(120, self.canvas.winfo_width() - 16)
        ideal = max(1, int(self._ideal_card_width()))
        cols = max(1, avail // ideal)
        cell_w = max(96, avail // cols - 14)
        cards = (self._group_cards if self.view_mode == "group" else self._cards)
        for idx, card in enumerate(cards.values()):
            if not card.winfo_exists():
                continue
            # 卡片跟着列宽走，组名过长时自动换行而不是被截断
            card.configure(wraplength=max(70, cell_w - 14))
            card.grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="nsew")
        # 列数变化时把旧的列权重清掉，否则窗口放大后再缩小会残留空白列
        previous = getattr(self, "_grid_cols", 0)
        for c in range(max(cols, previous)):
            if c < cols:
                self.inner.grid_columnconfigure(c, weight=1, minsize=0, uniform="card")
            else:
                self.inner.grid_columnconfigure(c, weight=0, minsize=0, uniform="")
        self._grid_cols = cols
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._inner_window, width=event.width)
        self._schedule_layout()

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _update_count(self):
        stu = self.all_students.get(self.current_class, {})
        groups = self._groups()
        if self.view_mode == "group":
            self.count_label.config(text=f"共 {len(groups)} 组 · {len(stu)} 人")
            self.sel_label.config(text="")
        else:
            self.count_label.config(text=f"共 {len(stu)} 人 · {len(groups)} 组")
            self.sel_label.config(text=f"已选 {len(self.selected_ids)} 人" if self.selected_ids else "")

    def _set_status(self, text, color=FG_DIM):
        self.status_label.config(text=text, fg=color)

    def _center_on(self, sid):
        card = self._cards.get(sid)
        if not card or not card.winfo_exists():
            return
        self.inner.update_idletasks()
        total = max(1, self.inner.winfo_height())
        # 顶部偏移按 DPI 放大，否则高 DPI 下会滚不到位
        offset = int(60 * dpi_scale(self.win))
        frac = max(0.0, min(1.0, (card.winfo_y() - offset) / total))
        self.canvas.yview_moveto(frac)

    # ========== 选择 / 随机点名 ==========
    def _toggle_select(self, sid):
        card = self._cards.get(sid)
        if card is None:
            return
        if sid in self.selected_ids:
            self.selected_ids.discard(sid)
            self._animate(card, CARD_BG)
        else:
            self.selected_ids.add(sid)
            self._animate(card, CARD_SELECT)
        self._update_count()

    def _animate(self, card, end_color):
        """颜色过渡动画；控件销毁后回调自动失效，不再抛异常。"""
        if not card.winfo_exists():
            return
        job = self._anim_jobs.pop(card, None)
        if job:
            try:
                self.win.after_cancel(job)
            except Exception:
                pass
        start = card.cget("bg")
        if start == end_color:
            return
        r1, g1, b1 = (v // 256 for v in self.win.winfo_rgb(start))
        r2, g2, b2 = (v // 256 for v in self.win.winfo_rgb(end_color))
        steps = 8

        def step(i):
            self._anim_jobs.pop(card, None)
            if not card.winfo_exists():
                return
            if i >= steps:
                card.config(bg=end_color)
                return
            color = "#%02x%02x%02x" % (
                int(r1 + (r2 - r1) * i / steps),
                int(g1 + (g2 - g1) * i / steps),
                int(b1 + (b2 - b1) * i / steps),
            )
            card.config(bg=color)
            self._anim_jobs[card] = self.win.after(12, lambda: step(i + 1))

        step(1)

    def _select_all(self):
        self.selected_ids = set(self._cards)
        for card in self._cards.values():
            self._animate(card, CARD_SELECT)
        self._update_count()

    def _invert_select(self):
        self.selected_ids = set(self._cards) - self.selected_ids
        for sid, card in self._cards.items():
            self._animate(card, CARD_SELECT if sid in self.selected_ids else CARD_BG)
        self._update_count()

    def _random_call(self):
        """随机点名：先快速滚动高亮，再定格并弹出带彩带的结果窗口。"""
        if self.view_mode == "group":
            self._switch_view("student")
        if not self._cards:
            self._set_status("班级暂无学生", FG_WARN)
            return

        sids = list(self._cards)
        stu = self.all_students[self.current_class]
        self._call_seq = getattr(self, "_call_seq", 0) + 1
        seq = self._call_seq
        steps = 20

        def paint():
            for s, card in self._cards.items():
                if card.winfo_exists():
                    card.config(bg=CARD_SELECT if s in self.selected_ids else CARD_BG)

        def roll(step):
            if seq != self._call_seq or not self.win.winfo_exists():
                return
            s = random.choice(sids)
            paint()
            card = self._cards.get(s)
            if card and card.winfo_exists():
                card.config(bg=CARD_FLASH)
            self._set_status(f"🎲 抽取中… {stu[s]['name']}", FG_ACCENT)
            if step >= steps:
                self.win.after(180, finish)
            else:
                # 越到后面滚动越慢，制造"减速"效果
                self.win.after(40 + step * 7, lambda: roll(step + 1))

        def finish():
            if seq != self._call_seq or not self.win.winfo_exists():
                return
            sid = random.choice(sids)
            info = stu[sid]
            self.selected_ids = {sid}
            paint()
            self._update_count()
            self._center_on(sid)
            self._flash_card(sid, 6)
            group = self._group_map().get(sid)
            extra = f"（{group[0]} {group[2]} 分）" if group else "（未分组）"
            self._set_status(f"🎲 随机点名：{sid} {info['name']}{extra}", FG_ACCENT)
            self._show_call_result(sid, info, group)

        roll(0)

    def _flash_card(self, sid, times=6):
        """定格后让卡片金色闪烁几次。"""
        card = self._cards.get(sid)
        if card is None:
            return

        def step(n):
            if not card.winfo_exists():
                return
            if n <= 0:
                self._animate(card, CARD_SELECT)
                return
            card.config(bg=CARD_FLASH if n % 2 else CARD_BG)
            self.win.after(140, lambda: step(n - 1))

        step(times)

    def _show_call_result(self, sid, info, group):
        """随机点名结果窗口：大字名字 + 彩带下落 + 颜色/字号脉冲。"""
        k = dpi_scale(self.win)
        w, h = int(440 * k), int(280 * k)
        win = tk.Toplevel(self.win)
        win.title("随机点名")
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.attributes("-topmost", True)
        cv = tk.Canvas(win, width=w, height=h, bg=BG_MAIN, highlightthickness=0)
        cv.pack(fill=tk.BOTH, expand=True)

        colors = ["#ffd166", "#06d6a0", "#ef476f", "#4cc9f0", "#f8961e"]
        particles = []
        for _ in range(36):
            x = random.randint(0, w)
            y = random.randint(-h, 0)
            size = random.randint(3, 7)
            item = cv.create_oval(x, y, x + size, y + size,
                                  fill=random.choice(colors), outline="")
            particles.append([item, random.uniform(2.0, 5.0) * k,
                              random.uniform(-0.6, 0.6)])

        name_id = cv.create_text(w // 2, int(h * 0.42), text=info["name"],
                                 font=(FONT, int(30 * k), "bold"), fill=FG_WARN)
        sub = sid
        if group:
            sub += f" · {group[0]}" + (" · 组长" if group[1] else "")
        cv.create_text(w // 2, int(h * 0.64), text=sub,
                       font=(FONT, int(11 * k)), fill=FG_TEXT)
        cv.create_text(w // 2, h - int(14 * k), text="点击关闭",
                       font=(FONT, int(8 * k)), fill=FG_DIM)

        state = {"seq": getattr(self, "_call_seq", 0), "frame": 0}

        def tick():
            if not win.winfo_exists() or state["seq"] != getattr(self, "_call_seq", 0):
                return
            for p in particles:
                cv.move(p[0], p[2], p[1])
                box = cv.coords(p[0])
                if box and box[1] > h:
                    cv.move(p[0], 0, -h - 20)
            n = state["frame"]
            if n < 90:
                size = 30 + int(2 * abs((n % 20) - 10))
                cv.itemconfig(name_id, font=(FONT, int(size * k), "bold"),
                              fill=colors[(n // 5) % len(colors)])
                state["frame"] = n + 1
                win.after(45, tick)
            else:
                cv.itemconfig(name_id, font=(FONT, int(32 * k), "bold"), fill=FG_WARN)

        def close(_event=None):
            if win.winfo_exists():
                win.destroy()

        win.bind("<Button-1>", close)
        cv.bind("<Button-1>", close)
        win.protocol("WM_DELETE_WINDOW", close)
        win.after(4500, close)
        center_window(win, self.win, w, h, auto=False)
        tick()

    def _selected_or_warn(self) -> bool:
        if self.selected_ids:
            return True
        messagebox.showwarning("提示", "请先选择学生", parent=self.win)
        return False

    # ========== 班级 ==========
    def _on_class_change(self, _event=None):
        name = self.class_box.get()
        if not name:
            return
        self.current_class = name
        self.selected_ids.clear()
        self._render_cards()
        self._set_status(f"已切换到 {name}", FG_ACCENT)

    def _create_class(self):
        if not self._can_write():
            return
        name = simpledialog.askstring("新建班级", "请输入班级名称：", parent=self.win)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.class_list:
            self._set_status("班级已存在", FG_DANGER)
            return
        self.class_list.append(name)
        self.all_students[name] = {}
        self.group_data[name] = {}
        self._save_all()
        self.class_box.config(values=self.class_list)
        self.class_box.set(name)
        self.current_class = name
        self.selected_ids.clear()
        self._render_cards()
        self._set_status(f"已创建班级 {name}", FG_OK)

    # ========== 持久化 ==========
    def _save_all(self):
        _save_json(CLASS_FILE, self.class_list)
        _save_json(STUDENT_FILE, self.all_students)
        _save_json(GROUP_FILE, self.group_data)
        _save_json(WEEKLY_ARCHIVE, dict(self.week_archive))
        try:
            import plugin_api
            plugin_api.emit("score_changed", {"cls": self.current_class})
        except Exception:
            pass

    def _log_ops(self, lines):
        """把加减分操作追加到 logs/score_operations.log（失败不影响业务）。"""
        if not lines:
            return
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(OP_LOG, "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
        except OSError:
            pass

    # ========== 通用小部件 ==========
    def _dialog(self, title, w, h):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.grab_set()
        win.resizable(False, False)
        # 内容由调用方添加，等布局完成后再按实际需要居中
        win.after_idle(
            lambda: center_window(win, self.win, w, h) if win.winfo_exists() else None)
        return win

    def _entry(self, parent, width=18):
        return tk.Entry(parent, width=width, font=(FONT, 11), bg=BG_CELL,
                        fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)

    def _hint(self, parent, text):
        return tk.Label(parent, text=text, font=(FONT, 9), bg=BG_MAIN,
                        fg=FG_DIM, justify=tk.LEFT, wraplength=380)

    # ========== 学生管理 ==========
    def _add_student(self):
        if not self._can_write():
            return
        win = self._dialog("新增学生", 360, 240)
        tk.Label(win, text="新增学生", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(16, 10))

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack()
        tk.Label(form, text="学号", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        e_id = self._entry(form)
        e_id.grid(row=0, column=1, pady=6)
        tk.Label(form, text="姓名", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=6)
        e_name = self._entry(form)
        e_name.grid(row=1, column=1, pady=6)
        e_id.focus_set()

        def submit():
            sid, name = e_id.get().strip(), e_name.get().strip()
            if not sid or not name:
                messagebox.showwarning("提示", "学号姓名不能为空", parent=win)
                return
            stu = self.all_students.setdefault(self.current_class, {})
            if sid in stu:
                messagebox.showerror("错误", "学号已存在", parent=win)
                return
            stu[sid] = {"stu_id": sid, "name": name}
            self._save_all()
            win.destroy()
            self._render_cards()
            self._center_on(sid)
            self._set_status(f"已添加 {sid} {name}", FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=16)
        self._btn(row, "确定", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: submit())

    def _batch_import(self):
        if not self._can_write():
            return
        win = self._dialog("批量导入学生", 460, 430)
        tk.Label(win, text="批量导入", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        self._hint(win, "每行一条：学号,姓名（支持中文逗号；重复学号自动跳过）\n"
                        "例如：01,张三   /   02,李四")\
            .pack(fill=tk.X, padx=18)

        txt = tk.Text(win, height=12, font=(FONT, 10), bg=BG_CELL, fg=FG_TEXT,
                      insertbackground=FG_TEXT, relief=tk.FLAT, padx=8, pady=6)
        txt.pack(fill=tk.BOTH, expand=True, padx=18, pady=8)
        txt.focus_set()

        def submit():
            stu = self.all_students.setdefault(self.current_class, {})
            count = skipped = 0
            for line in txt.get("1.0", tk.END).splitlines():
                line = line.strip().replace("，", ",")
                if not line:
                    continue
                parts = line.split(",", 1)
                if len(parts) != 2:
                    skipped += 1
                    continue
                sid, name = parts[0].strip(), parts[1].strip()
                if not sid or not name or sid in stu:
                    skipped += 1
                    continue
                stu[sid] = {"stu_id": sid, "name": name}
                count += 1
            self._save_all()
            win.destroy()
            self._render_cards()
            msg = f"成功导入 {count} 名学生"
            if skipped:
                msg += f"，跳过 {skipped} 条"
            self._set_status(msg, FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=(0, 14))
        self._btn(row, "导入", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)

    def _delete_students(self):
        if not self._can_write():
            return
        if not self._selected_or_warn():
            return
        stu = self.all_students.get(self.current_class, {})
        names = [f"{sid} {stu[sid]['name']}" for sid in sorted(self.selected_ids) if sid in stu]
        if not messagebox.askyesno("确认删除", "确定删除以下学生？\n\n" + "\n".join(names),
                                   parent=self.win):
            return
        for sid in list(self.selected_ids):
            stu.pop(sid, None)
        # 同步清理小组中的成员与组长
        removed = set(self.selected_ids)
        for group in self.group_data.get(self.current_class, {}).values():
            group["members"] = [s for s in group.get("members", []) if s not in removed]
            if group.get("leader") not in group["members"]:
                group["leader"] = ""
        self.selected_ids.clear()
        self._save_all()
        self._render_cards()
        self._set_status("已删除选中学生", FG_OK)

    def _edit_student(self):
        if not self._can_write():
            return
        if not self._selected_or_warn():
            return
        sid = sorted(self.selected_ids)[0]
        stu = self.all_students[self.current_class][sid]

        win = self._dialog("编辑学生资料", 360, 200)
        tk.Label(win, text=f"{sid} · 编辑资料", font=(FONT, 13, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(18, 12))
        form = tk.Frame(win, bg=BG_MAIN)
        form.pack()
        tk.Label(form, text="姓名", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        e_name = self._entry(form)
        e_name.insert(0, stu["name"])
        e_name.grid(row=0, column=1, pady=6)
        e_name.focus_set()

        def save():
            new_name = e_name.get().strip()
            if not new_name:
                messagebox.showwarning("提示", "姓名不能为空", parent=win)
                return
            stu["name"] = new_name
            self._save_all()
            win.destroy()
            self._render_cards()
            self._set_status("学生资料已更新", FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=16)
        self._btn(row, "保存", save, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)

    # ========== 评价打分 ==========
    def _open_score(self, target_groups=None, target_students=None):
        if not self._can_write():
            return
        if self._score_win and self._score_win.winfo_exists():
            self._score_win.lift()
            return
        stu = self.all_students.get(self.current_class, {})
        groups = self._groups()

        sids = list(target_students or [])
        if not sids:
            if target_groups:
                for gname in target_groups:
                    group = groups.get(gname)
                    if group:
                        sids += [s for s in group.get("members", []) if s in stu]
            elif self.view_mode == "group":
                gname = self._pick_group("评价打分")
                if not gname:
                    return
                sids = [s for s in groups[gname].get("members", []) if s in stu]
            else:
                if not self._selected_or_warn():
                    return
                sids = [s for s in sorted(self.selected_ids) if s in stu]
        sids = list(dict.fromkeys(sids))
        if not sids:
            messagebox.showinfo("提示", "所选范围内没有学生", parent=self.win)
            return

        gmap = store.student_group_map(groups, stu)
        win = self._dialog("评价打分", 560, 590)
        self._score_win = win
        tk.Label(win, text="评价打分", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text="积分记在每位学生名下，可只勾选本次涉及的学生",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack()

        pick_body = tk.Frame(win, bg=BG_PANEL,
                             highlightbackground=BG_CELL, highlightthickness=1)
        pick_body.pack(fill=tk.BOTH, expand=True, padx=22, pady=(8, 6))
        cv = tk.Canvas(pick_body, bg=BG_PANEL, height=150, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(pick_body, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pick_inner = tk.Frame(cv, bg=BG_PANEL)
        cv.create_window((0, 0), window=pick_inner, anchor="nw")
        pick_inner.bind("<Configure>",
                        lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<MouseWheel>",
                lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))

        vars_ = {}
        for sid in sids:
            info = stu[sid]
            var = tk.BooleanVar(value=True)
            vars_[sid] = var
            gname = gmap.get(sid, "未分组")
            base_text = f"{sid}  {info['name']}（{gname}）"
            # indicatoron=False：整行就是勾选按钮，选中时整行蓝色高亮
            cb = tk.Checkbutton(pick_inner, text="✔ " + base_text, variable=var,
                                font=(FONT, 10), bg=BG_PANEL, fg="#ffffff",
                                activebackground=CHECK_BG, activeforeground="#ffffff",
                                selectcolor=CHECK_BG, relief="flat", bd=0,
                                highlightthickness=0, padx=10, pady=4,
                                anchor="w", cursor="hand2", indicatoron=False)
            cb.pack(fill=tk.X, padx=6, pady=1)

            def sync(w=cb, v=var, text=base_text):
                on = v.get()
                w.config(text=("✔ " if on else "   ") + text,
                         fg="#ffffff" if on else FG_DIM)
            var.trace_add("write", lambda *a, f=sync: f())

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack(padx=24, pady=4, fill=tk.X)
        form.columnconfigure(1, weight=1)

        # 分类
        tk.Label(form, text="分类", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=5)
        cat_box = ttk.Combobox(form, values=list(reason_categories), state="readonly",
                               width=22, font=(FONT, 10))
        cat_box.current(0)
        cat_box.grid(row=0, column=1, sticky="w", pady=5)

        # 具体理由：可直接输入自定义理由
        tk.Label(form, text="理由", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=5)
        reason_box = ttk.Combobox(
            form, values=reason_categories["常用"] + custom_reasons(),
            width=26, font=(FONT, 10))
        reason_box.current(0)
        reason_box.grid(row=1, column=1, sticky="w", pady=5)

        def change_cat(_event=None):
            reason_box["values"] = reason_categories[cat_box.get()] + custom_reasons()
            reason_box.current(0)
        cat_box.bind("<<ComboboxSelected>>", change_cat)

        # 分值：正数加分、负数扣分
        tk.Label(form, text="分值", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=2, column=0, sticky="w", pady=5)
        score_entry = self._entry(form, width=10)
        score_entry.grid(row=2, column=1, sticky="w", pady=5)

        tk.Label(win, text="分值填正数加分、负数扣分（如 3 或 -2）；理由可直接输入新内容，会保存为预设",
                 font=(FONT, 8), bg=BG_MAIN, fg=FG_DIM,
                 wraplength=480, justify=tk.CENTER).pack()
        score_entry.focus_set()

        err = tk.Label(win, text="", font=(FONT, 9), bg=BG_MAIN, fg=FG_DANGER)
        err.pack()

        def submit():
            chosen = [sid for sid in sids if vars_[sid].get()]
            reason = reason_box.get().strip()
            score_str = score_entry.get().strip()
            if not chosen:
                err.config(text="请至少勾选一名学生")
                return
            if not reason:
                err.config(text="请填写理由")
                return
            if not score_str:
                err.config(text="分值不能为空")
                return
            try:
                delta = int(score_str)
            except ValueError:
                err.config(text="分值必须是整数（正数加分，负数扣分）")
                return
            if delta == 0:
                err.config(text="分值不能为 0（正数加分，负数扣分）")
                return
            if abs(delta) > 10 and not messagebox.askyesno(
                    "提醒", f"分值 {delta:+d} 超过 10，确定提交？", parent=win):
                return

            mode = "加分" if delta > 0 else "扣分"
            score = abs(delta)
            # 自定义理由：保存下来，下次可直接选用
            if reason not in reason_categories.get(cat_box.get(), []) \
                    and reason not in custom_reasons():
                add_custom_reason(reason)

            count = store.add_point_records(self.all_students, self.group_data,
                                            self.current_class, chosen, reason, delta)
            self._save_all()
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            log_lines = []
            for sid in chosen:
                info = stu.get(sid, {})
                log_lines.append(
                    f"{now} | {self.current_class} | {sid} {info.get('name', '')} | "
                    f"{mode} {score} 分 | {reason} | 余额 {store.student_total(info)}")
            self._log_ops(log_lines)
            win.destroy()
            self._score_win = None
            # 只刷新数字，不重建卡片：积分即时变化，不会闪屏
            self._refresh_scores()
            self._set_status(f"已为 {count} 名学生{mode} {score} 分 · {reason}", FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=(6, 14))
        self._btn(row, "提交", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: submit())

    # ========== 撤回积分记录 ==========
    def _revoke_record(self):
        if not self._can_write():
            return
        stu = self.all_students.get(self.current_class, {})
        gmap = store.student_group_map(self._groups(), stu)

        win = self._dialog("撤回积分记录", 760, 560)
        tk.Label(win, text="撤回积分记录", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text="积分记在个人名下；撤回后该学生积分立即回退",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack()

        body = tk.Frame(win, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)
        tree = ttk.Treeview(body, columns=("time", "student", "group", "delta", "reason"),
                            show="headings", selectmode="browse")
        for col, text, width in (("time", "时间", 150), ("student", "学生", 130),
                                 ("group", "小组", 110), ("delta", "分值", 70),
                                 ("reason", "理由", 220)):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w" if col in ("student", "group", "reason")
                        else "center")
        sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def fill():
            tree.delete(*tree.get_children())
            rows = []
            for sid, info in stu.items():
                for idx, rec in enumerate(store.student_records(info)):
                    if isinstance(rec, dict):
                        rows.append((sid, info.get("name", ""), idx, rec))
            rows.sort(key=lambda item: item[3].get("time", ""), reverse=True)
            for sid, name, idx, rec in rows:
                delta = store.record_delta(rec)
                tree.insert("", tk.END, iid=f"{sid}|{idx}", values=(
                    rec.get("time", ""), f"{sid} {name}",
                    gmap.get(sid, "未分组"),
                    f"{delta:+d}", rec.get("reason", "")))
            return bool(rows)

        def revoke():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择一条记录", parent=win)
                return
            sid, idx_text = sel[0].rsplit("|", 1)
            info = stu.get(sid)
            if not info:
                return
            records = store.student_records(info)
            try:
                idx = int(idx_text)
                rec = records[idx]
            except (ValueError, IndexError):
                return
            if not messagebox.askyesno(
                    "确认撤回",
                    f"撤回 {sid} {info.get('name', '')} 的这条记录？\n\n"
                    f"{rec.get('time', '')}  {rec.get('reason', '')}  "
                    f"{store.record_delta(rec):+d} 分",
                    parent=win):
                return
            records.pop(idx)
            info["total_score"] = store.student_total(info)
            store.sync_group_totals(self.all_students, self.group_data)
            self._save_all()
            self._log_ops([f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {self.current_class} | "
                           f"{sid} {info.get('name', '')} | 撤回 {rec.get('reason', '')} | "
                           f"原记录 {rec.get('time', '')}"])
            self._refresh_scores()
            if not fill():
                win.destroy()
            self._set_status(f"已撤回 {sid} {info.get('name', '')} 的积分记录", FG_OK)

        if not fill():
            win.destroy()
            messagebox.showinfo("提示", "当前班级暂无积分记录", parent=self.win)
            return

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(fill=tk.X, padx=16, pady=(0, 12))
        self._btn(row, "撤回选中记录", revoke, primary=True).pack(side=tk.LEFT)
        self._btn(row, "关闭", win.destroy).pack(side=tk.RIGHT)

    def _pick_group(self, title, prefer=None):
        """弹出小组选择框，返回小组名或 None。"""
        groups = self._groups()
        if not groups:
            return None
        names = list(groups)
        if prefer and len(prefer) == 1 and prefer[0] in groups:
            return prefer[0]
        win = self._dialog(title, 340, 160)
        tk.Label(win, text="选择小组", font=(FONT, 12, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))
        box = ttk.Combobox(win, values=names, state="readonly",
                           width=22, font=(FONT, 10))
        box.set(prefer[0] if prefer and prefer[0] in groups else names[0])
        box.pack()
        result = {}

        def ok():
            result["name"] = box.get()
            win.destroy()

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=14)
        self._btn(row, "确定", ok, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        self.win.wait_window(win)
        return result.get("name")

    # ========== 积分明细 ==========
    def _query_detail(self):
        groups = self._groups()
        if not groups:
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return
        stu = self.all_students.get(self.current_class, {})
        parts = []
        for gname, group in groups.items():
            leader = group.get("leader", "")
            leader_text = f"{leader} {stu[leader]['name']}" if leader in stu else "未指定"
            members = [s for s in group.get("members", []) if s in stu]
            total = store.group_total(group, stu)
            parts.append(f"小组：{gname}    组长：{leader_text}    "
                         f"人数：{len(members)}    小组积分：{total}")
            for sid in members:
                info = stu[sid]
                records = store.student_records(info)
                parts.append(f"  {sid} {info['name']}    {store.student_total(info)} 分")
                if not records:
                    parts.append("      （暂无记录）")
                for r in reversed(records):
                    delta = store.record_delta(r)
                    parts.append(f"      {r.get('time', '')}    {delta:+d}    "
                                 f"{r.get('reason', '')}")
            parts.append("-" * 56)
        self._text_window("积分明细（按小组 → 组员）", "\n".join(parts))

    def _text_window(self, title, content):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        tk.Label(win, text=title, font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(12, 6))
        body = tk.Frame(win, bg=BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        txt = tk.Text(body, font=("Consolas", 11), bg=BG_PANEL, fg=FG_TEXT,
                      relief=tk.FLAT, padx=12, pady=10, wrap=tk.WORD)
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        txt.insert(tk.END, content)
        txt.config(state=tk.DISABLED)
        # 按 DPI 放大并居中，和其余弹窗保持一致
        k = dpi_scale(self.win)
        center_window(win, self.win, int(720 * k), int(480 * k))
        return win, txt

    # ========== 图表窗口 ==========
    def _chart_window(self, title, width=780, height=500, draw=None):
        """统一的图表窗口；内容放进可滚动区域，行数多或屏幕小时不会被裁掉。"""
        win = tk.Toplevel(self.win)
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
        body.bind("<Configure>",
                  lambda e: cv.configure(scrollregion=cv.bbox("all")))

        self._btn(win, "关闭", win.destroy).pack(pady=(0, 12))
        if draw is not None:
            draw(body)
            self._charts.append((win, body, draw))
            win.bind("<Destroy>",
                     lambda e, w=win: self._charts.__setitem__(
                         slice(None), [c for c in self._charts if c[0] is not w]))
        # 图表内容已绘制，等布局完成后再按 DPI 缩放并居中
        k = dpi_scale(self.win)
        win.after_idle(
            lambda: center_window(win, self.win, int(width * k), int(height * k))
            if win.winfo_exists() else None)
        return body

    def _refresh_charts(self):
        """积分变化后重绘所有仍打开的统计图表。"""
        for win, body, draw in list(self._charts):
            if not win.winfo_exists():
                continue
            for child in body.winfo_children():
                child.destroy()
            try:
                draw(body)
            except tk.TclError:
                pass

    def _week_chart(self):
        """周度统计：按周次画双向条形图（加分向右，扣分向左）。"""
        if not self._groups():
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return

        def collect():
            week_data = defaultdict(lambda: {"add": 0, "sub": 0})
            for _gname, _sid, _name, r in self._iter_records():
                d = week_data[r.get("week", "未知")]
                if store.record_delta(r) >= 0:
                    d["add"] += abs(int(r.get("score", 0)))
                else:
                    d["sub"] += abs(int(r.get("score", 0)))
            return [(w, d["add"], d["sub"]) for w, d in sorted(week_data.items())]

        rows = collect()
        if not rows:
            messagebox.showinfo("提示", "暂无周度数据", parent=self.win)
            return

        def draw(body):
            charts.bar_chart(body, collect(), width=720).pack(fill=tk.BOTH, expand=True)

        self._chart_window(f"周度积分统计 · {self.current_class}", 760,
                           120 + 34 * len(rows), draw)

    def _group_bar(self):
        """小组双向条形图：加分向右（绿），扣分向左（红）。"""
        if not self._groups():
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return

        def collect():
            rows = []
            for gname, group in self._groups().items():
                add = sub = 0
                stu = self.all_students.get(self.current_class, {})
                for sid in group.get("members", []):
                    info = stu.get(sid)
                    if not info:
                        continue
                    for r in store.student_records(info):
                        if store.record_delta(r) >= 0:
                            add += abs(int(r.get("score", 0)))
                        else:
                            sub += abs(int(r.get("score", 0)))
                rows.append((gname, add, sub))
            # 净得分高的排在上面，更直观
            rows.sort(key=lambda x: -(x[1] - x[2]))
            return rows

        rows = collect()
        if not any(a or b for _, a, b in rows):
            messagebox.showinfo("提示", "暂无加减分记录", parent=self.win)
            return

        def draw(body):
            charts.bar_chart(body, collect(), width=740).pack(fill=tk.BOTH, expand=True)

        self._chart_window(f"小组加减分对比 · {self.current_class}", 780,
                           140 + 34 * len(rows), draw)

    def _reason_pie(self):
        """理由分布饼图：统计每个理由出现的次数与占比。"""
        def collect():
            counter = defaultdict(int)
            for _gname, _sid, _name, r in self._iter_records():
                counter[r.get("reason", "未填写")] += 1
            return sorted(counter.items(), key=lambda kv: -kv[1])

        if not collect():
            messagebox.showinfo("提示", "暂无加减分记录", parent=self.win)
            return

        def draw(body):
            charts.pie_chart(body, collect()).pack(fill=tk.BOTH, expand=True)

        self._chart_window(f"理由分布 · {self.current_class}", 780, 480, draw)

    # ========== 操作日志 ==========
    def _view_op_log(self):
        if not OP_LOG.exists():
            messagebox.showinfo("操作日志", "暂无操作日志", parent=self.win)
            return
        try:
            lines = OP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            messagebox.showerror("操作日志", f"读取失败：{exc}", parent=self.win)
            return
        tail = lines[-800:]
        self._text_window(f"操作日志（最近 {len(tail)} 条）", "\n".join(tail))

    # ========== 低积分预警 ==========
    def _low_score_warn(self):
        groups = self._groups()
        if not groups:
            messagebox.showinfo("提示", "当前班级还没有小组", parent=self.win)
            return
        limit = low_score_limit()          # settings.json 可配置，默认 60
        stu = self.all_students.get(self.current_class, {})
        warn = []
        for gname, group in groups.items():
            total = store.group_total(group, stu)
            if total >= limit:
                continue
            leader = group.get("leader", "")
            leader_text = f"组长 {leader} {stu[leader]['name']}" if leader in stu else "未指定组长"
            warn.append(f"{gname}（{leader_text}）：{total} 分")
        if warn:
            self._text_window(f"低积分预警（低于 {limit} 分）", "\n".join(warn))
            self._set_status(f"{len(warn)} 个小组积分偏低", FG_WARN)
        else:
            messagebox.showinfo("低积分预警", "所有小组积分正常", parent=self.win)

    # ========== 手动修改积分 ==========
    def _manual_score(self):
        if not self._can_write():
            return
        stu = self.all_students.get(self.current_class, {})
        sids = [s for s in sorted(self.selected_ids) if s in stu]
        if not sids and self.view_mode == "group":
            gname = self._pick_group("手动修改积分")
            if not gname:
                return
            sids = [s for s in self._groups()[gname].get("members", []) if s in stu]
        if not sids:
            messagebox.showinfo("提示", "请先选择学生（或切换到「按学生」视图）",
                                parent=self.win)
            return
        names = "、".join(f"{s} {stu[s]['name']}" for s in sids)
        num = simpledialog.askstring(
            "手动修改积分",
            f"把选中的 {len(sids)} 名学生积分设为：\n{names}",
            parent=self.win,
        )
        if num is None:
            return
        try:
            new_score = int(num.strip())
        except ValueError:
            messagebox.showerror("错误", "请输入整数", parent=self.win)
            return
        if not messagebox.askyesno(
                "确认修改",
                f"确定把这些学生的积分直接设为 {new_score} 分？\n\n"
                f"{names}\n\n"
                "（差额会写入一条「手动调整」记录）",
                parent=self.win):
            return
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        week = time.strftime("%G-W%V")
        log_lines = []
        for sid in sids:
            info = stu[sid]
            old = store.student_total(info)
            delta = new_score - old
            if delta == 0:
                continue
            info.setdefault("records", []).append({
                "operate": "加分" if delta > 0 else "扣分",
                "score": abs(delta), "reason": "手动调整",
                "time": now, "week": week,
            })
            info["total_score"] = store.student_total(info)
            log_lines.append(f"{now} | {self.current_class} | {sid} {info['name']} | "
                             f"手动改分 {old} → {new_score}")
        store.sync_group_totals(self.all_students, self.group_data)
        self._save_all()
        self._log_ops(log_lines)
        self._refresh_scores()
        self._set_status(f"已将 {len(sids)} 名学生积分设为 {new_score}", FG_OK)

    # ========== 本周归档 ==========
    def _archive_week(self):
        if not self._can_write():
            return
        wk = time.strftime("%G-W%V")
        store.sync_group_totals(self.all_students, self.group_data)
        # 用 JSON 序列化深拷贝，避免 deepcopy 在含循环引用时的性能/内存问题
        snapshot = json.loads(json.dumps(self._groups(), ensure_ascii=False))
        self.week_archive[wk].append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "class": self.current_class,
            "data": snapshot,
        })
        self._save_all()
        self._set_status(f"{self.current_class} · {wk} 小组数据已归档", FG_OK)

    # ========== 小组管理 ==========
    def _open_groups(self):
        if not self._can_write():
            return
        groups = self.group_data.setdefault(self.current_class, {})
        stu = self.all_students.get(self.current_class, {})
        win = self._dialog("小组管理", 720, 480)
        tk.Label(win, text=f"小组管理 · {self.current_class}", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))

        body = tk.Frame(win, bg=BG_MAIN)
        body.pack(fill=tk.BOTH, expand=True, padx=16)

        k = dpi_scale(self.win)
        style = ttk.Style()
        style.configure("Group.Treeview", background=BG_CELL, fieldbackground=BG_CELL,
                        foreground=FG_TEXT, rowheight=int(30 * k), borderwidth=0,
                        font=(FONT, 10))
        style.configure("Group.Treeview.Heading", background=BG_PANEL,
                        foreground=FG_ACCENT, relief=tk.FLAT,
                        font=(FONT, 10, "bold"))
        style.map("Group.Treeview", background=[("selected", CARD_SELECT)])

        tree = ttk.Treeview(body, columns=("name", "leader", "count", "score"),
                            show="headings", style="Group.Treeview",
                            selectmode="browse")
        tree.heading("name", text="小组")
        tree.heading("leader", text="组长")
        tree.heading("count", text="人数")
        tree.heading("score", text="积分")
        tree.column("name", width=int(240 * k), anchor="w")
        tree.column("leader", width=int(160 * k), anchor="center")
        tree.column("count", width=int(70 * k), anchor="center")
        tree.column("score", width=int(70 * k), anchor="center")
        sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def refresh(select=None):
            tree.delete(*tree.get_children())
            for gname, group in groups.items():
                members = [s for s in group.get("members", []) if s in stu]
                leader = group.get("leader", "")
                leader_text = f"{leader} {stu[leader]['name']}" if leader in stu else "未指定"
                tree.insert("", tk.END, iid=gname,
                            values=(gname, leader_text, len(members),
                                    store.group_total(group, stu)))
            if select and tree.exists(select):
                tree.selection_set(select)
                tree.see(select)

        def selected_group():
            sel = tree.selection()
            return sel[0] if sel else None

        def new_group():
            self._edit_group(None, groups, refresh)

        def edit_group(_event=None):
            gname = selected_group()
            if not gname:
                messagebox.showinfo("提示", "请先选择一个小小组", parent=win)
                return
            self._edit_group(gname, groups, refresh)

        def del_group():
            gname = selected_group()
            if not gname:
                messagebox.showinfo("提示", "请先选择一个小小组", parent=win)
                return
            if not messagebox.askyesno("确认删除", f"确定删除小组「{gname}」？\n组内学生不会被删除，该组积分记录会一并清除。",
                                       parent=win):
                return
            groups.pop(gname, None)
            self._save_all()
            self._render_cards()
            refresh()
            self._set_status(f"已删除小组 {gname}", FG_OK)

        btn_row = tk.Frame(win, bg=BG_MAIN)
        btn_row.pack(fill=tk.X, padx=16, pady=12)
        self._btn(btn_row, "新建小组", new_group, primary=True).pack(side=tk.LEFT)
        self._btn(btn_row, "编辑小组", edit_group).pack(side=tk.LEFT, padx=8)
        self._btn(btn_row, "删除小组", del_group).pack(side=tk.LEFT)
        self._btn(btn_row, "关闭", win.destroy).pack(side=tk.RIGHT)
        tree.bind("<Double-1>", edit_group)

        refresh()

    def _edit_group(self, name, groups, on_saved):
        """新建 / 编辑小组：填写组名、成员（多选）、组长。"""
        stu = self.all_students.get(self.current_class, {})
        editing = name is not None
        group = groups.get(name, {}) if editing else {}
        win = self._dialog("编辑小组" if editing else "新建小组", 520, 540)
        tk.Label(win, text=(f"编辑小组「{name}」" if editing else "新建小组"),
                 font=(FONT, 14, "bold"), bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 8))

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack(fill=tk.X, padx=18)
        tk.Label(form, text="小组名称", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        name_entry = self._entry(form, 22)
        name_entry.grid(row=0, column=1, sticky="w", padx=8)
        if editing:
            name_entry.insert(0, name)

        tk.Label(win, text="成员（Ctrl / Shift 多选）", font=(FONT, 10),
                 bg=BG_MAIN, fg=FG_DIM).pack(anchor="w", padx=18, pady=(8, 4))
        list_frame = tk.Frame(win, bg=BG_MAIN)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=18)
        lb = tk.Listbox(list_frame, selectmode=tk.EXTENDED, font=(FONT, 10),
                        bg=BG_CELL, fg=FG_TEXT, selectbackground=CARD_SELECT,
                        selectforeground=FG_TEXT, activestyle="none",
                        relief=tk.FLAT, highlightthickness=0, exportselection=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        sids = sorted(stu)
        for sid in sids:
            lb.insert(tk.END, f"{sid}  {stu[sid]['name']}")
        current = set(group.get("members", []))
        for idx, sid in enumerate(sids):
            if sid in current:
                lb.selection_set(idx)

        leader_row = tk.Frame(win, bg=BG_MAIN)
        leader_row.pack(fill=tk.X, padx=18, pady=10)
        tk.Label(leader_row, text="组长", font=(FONT, 10), bg=BG_MAIN,
                 fg=FG_DIM).pack(side=tk.LEFT)
        no_leader = "（未指定）"
        leader_box = ttk.Combobox(leader_row, state="readonly", width=24,
                                  font=(FONT, 10), values=[no_leader])
        leader_box.set(no_leader)
        leader_box.pack(side=tk.LEFT, padx=8)
        leader_map = {}

        def selected_sids():
            return [sids[i] for i in lb.curselection()]

        def sync_leader(_event=None):
            prev = leader_box.get()
            values = [no_leader]
            leader_map.clear()
            for sid in selected_sids():
                label = f"{sid} {stu[sid]['name']}"
                values.append(label)
                leader_map[label] = sid
            leader_box.config(values=values)
            if prev != no_leader and prev in values:
                leader_box.set(prev)
            elif len(values) > 1:
                leader_box.set(values[1])
            else:
                leader_box.set(no_leader)

        lb.bind("<<ListboxSelect>>", sync_leader)
        sync_leader()
        if editing and group.get("leader") in current and group["leader"] in stu:
            lid = group["leader"]
            label = f"{lid} {stu[lid]['name']}"
            if label in leader_map:
                leader_box.set(label)

        def save():
            gname = name_entry.get().strip()
            if not gname:
                messagebox.showwarning("提示", "请输入小组名称", parent=win)
                return
            if gname in groups and gname != name:
                messagebox.showwarning("提示", "小组名称已存在", parent=win)
                return
            members = selected_sids()
            if not members:
                messagebox.showwarning("提示", "请至少选择一名成员", parent=win)
                return
            leader = leader_map.get(leader_box.get(), "")
            if leader not in members:
                leader = ""

            moved = []
            for other_name, other in groups.items():
                if other_name in (name, gname):
                    continue
                before = list(other.get("members", []))
                kept = [s for s in before if s not in members]
                if len(kept) != len(before):
                    moved += [s for s in before if s in members]
                    other["members"] = kept
                    if other.get("leader") not in kept:
                        other["leader"] = ""

            old = groups.get(name if editing else gname, {})
            if editing and gname != name:
                groups.pop(name, None)
            groups[gname] = {
                "leader": leader,
                "members": members,
                "total_score": int(old.get("total_score", 0)),
                "record": list(old.get("record", [])),
            }
            # 成员调整后按个人积分重新汇总小组积分
            store.sync_group_totals(self.all_students, self.group_data)

            self._save_all()
            self._render_cards()
            on_saved(gname)
            win.destroy()
            if moved:
                self._set_status(f"已保存小组 {gname}（{len(moved)} 人从原小组移入）", FG_OK)
            else:
                self._set_status(f"已保存小组 {gname}", FG_OK)

        btns = tk.Frame(win, bg=BG_MAIN)
        btns.pack(fill=tk.X, padx=18, pady=12)
        self._btn(btns, "保存", save, primary=True).pack(side=tk.LEFT)
        self._btn(btns, "取消", win.destroy).pack(side=tk.LEFT, padx=8)

    # ========== 更多功能（下拉菜单） ==========
    def _open_more_menu(self):
        menu = tk.Menu(self.win, tearoff=0, bg=BG_PANEL, fg=FG_TEXT,
                       activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                       bd=0, font=(FONT, 10))
        groups = [
            [("新增学生", self._add_student),
             ("批量导入学生", self._batch_import),
             ("删除选中学生", self._delete_students),
             ("编辑学生资料", self._edit_student),
             ("小组管理", self._open_groups)],
            [("撤回积分记录", self._revoke_record),
             ("查询积分明细", self._query_detail),
             ("周度积分统计图", self._week_chart),
             ("理由分布饼图", self._reason_pie),
             ("小组加减分对比图", self._group_bar),
             ("低积分预警", self._low_score_warn)],
            [("查看操作日志", self._view_op_log),
             ("手动修改积分", self._manual_score),
             ("本周数据归档", self._archive_week)],
        ]
        if self.readonly:
            groups = [[("查询积分明细", self._query_detail),
                       ("周度积分统计图", self._week_chart),
                       ("理由分布饼图", self._reason_pie),
                       ("小组加减分对比图", self._group_bar),
                       ("低积分预警", self._low_score_warn),
                       ("查看操作日志", self._view_op_log)]]
        for i, group in enumerate(groups):
            if i:
                menu.add_separator()
            for text, cmd in group:
                menu.add_command(label=text, command=cmd)

        # 插件注册的扩展入口（积分分析中心 / 学生个人主页等）
        try:
            import plugin_api
            plugin_items = plugin_api.score_menu_items(readonly=self.readonly)
        except Exception:
            plugin_items = []
        if plugin_items:
            menu.add_separator()
            api = plugin_api.ScoreWindowAPI(self)
            for label, callback in plugin_items:
                menu.add_command(
                    label=label,
                    command=lambda cb=callback: self._run_plugin_item(cb, api))

        btn = self._more_btn
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def _run_plugin_item(self, callback, api):
        """执行插件注册的积分窗口菜单项，异常只提示不中断窗口。"""
        try:
            callback(api)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            messagebox.showerror("插件出错", str(exc), parent=self.win)



