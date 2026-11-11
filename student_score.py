"""
学生积分模块（由 740.6.py 修正后嵌入课程表）
- 配色 / 字体与 ui.py 保持一致
- 数据文件沿用 740.6.py 的格式，可直接复用已有数据
- 修正：窗口参数写错、Configure 绑定泄漏、动画回调作用于已销毁控件、
  归档浅拷贝、批量导入无法多行输入、底部按钮绝对定位、初始列数失效、周次 W00
"""

import copy
import json
import random
import sys
import time
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from ui import (
    BG_MAIN, BG_PANEL, BG_CELL, BG_CELL_ALT, BG_IN_CLASS,
    FG_TEXT, FG_DIM, FG_ACCENT, FG_WARN, FG_DANGER, FG_OK,
)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).parent.resolve()
CLASS_FILE = APP_DIR / "class_data.txt"
STUDENT_FILE = APP_DIR / "student_data.txt"
WEEKLY_ARCHIVE = APP_DIR / "weekly_score_archive.txt"

FONT = "Microsoft YaHei UI"
CARD_BG = BG_CELL
CARD_SELECT = "#2f5f8f"      # 选中：与强调色 FG_ACCENT 同系的深蓝
CARD_W = 128                 # 卡片宽度 + 间距，用于计算列数
LOW_SCORE_LIMIT = 60


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


# ===================== 分类奖惩理由 =====================
reason_categories = {
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

    def __init__(self, parent, default_class: str = "七年级10班"):
        self.win = tk.Toplevel(parent)
        self.win.title("学生积分 · 课程表")
        self.win.geometry("1000x640")
        self.win.minsize(820, 560)
        self.win.configure(bg=BG_MAIN)

        # ---- 数据 ----
        self.class_list = _load_json(CLASS_FILE, []) or []
        self.all_students = _load_json(STUDENT_FILE, {}) or {}
        self.week_archive = defaultdict(list, _load_json(WEEKLY_ARCHIVE, {}) or {})

        if default_class not in self.class_list:
            self.class_list.append(default_class)
        for c in self.class_list:
            self.all_students.setdefault(c, {})

        self.current_class = default_class
        self.selected_ids = set()
        self._cards = {}
        self._anim_jobs = {}
        self._layout_job = None
        self._score_win = None

        self._build()
        self._render_cards()
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

        self._btn(top, "+ 新建班级", self._create_class).pack(side=tk.RIGHT)

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
        self._btn(bar, "全选", self._select_all).pack(side=tk.LEFT, padx=8)
        self._btn(bar, "反选", self._invert_select).pack(side=tk.LEFT)
        self._btn(bar, "评价打分", self._open_score, primary=True).pack(side=tk.RIGHT)
        self._btn(bar, "随机点名", self._random_call).pack(side=tk.RIGHT, padx=8)

    def _btn(self, parent, text, cmd, primary=False):
        bg = BG_IN_CLASS if primary else BG_CELL
        active = "#4b7b4b" if primary else BG_CELL_ALT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=FG_TEXT,
                         activebackground=active, activeforeground=FG_TEXT,
                         relief=tk.FLAT, font=(FONT, 10, "bold" if primary else "normal"),
                         padx=14, pady=6, cursor="hand2")

    # ========== 卡片渲染 / 布局 ==========
    def _card_text(self, sid, info):
        return f"{sid}\n{info['name']}\n{info['total_score']} 分"

    def _render_cards(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self._cards.clear()
        self._anim_jobs.clear()

        for sid, info in self.all_students.get(self.current_class, {}).items():
            card = tk.Button(self.inner, text=self._card_text(sid, info),
                             font=(FONT, 10), bg=CARD_BG, fg=FG_TEXT,
                             activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                             relief=tk.FLAT, width=13, height=4, cursor="hand2",
                             command=lambda s=sid: self._toggle_select(s))
            card.bind("<MouseWheel>", self._on_wheel)
            self._cards[sid] = card

        # 选中集合里可能残留已删除的学生
        self.selected_ids &= set(self._cards)
        for sid in self.selected_ids:
            self._cards[sid].config(bg=CARD_SELECT)

        self._update_count()
        self._schedule_layout()

    def _schedule_layout(self):
        if self._layout_job:
            try:
                self.win.after_cancel(self._layout_job)
            except Exception:
                pass
        self._layout_job = self.win.after(60, self._apply_layout)

    def _apply_layout(self):
        self._layout_job = None
        if not self.win.winfo_exists():
            return
        cols = max(1, (self.canvas.winfo_width() - 16) // CARD_W)
        for idx, card in enumerate(self._cards.values()):
            if not card.winfo_exists():
                continue
            card.grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="nsew")
        for c in range(cols):
            self.inner.grid_columnconfigure(c, weight=1)
        for c in range(cols, self.inner.grid_size()[0]):
            self.inner.grid_columnconfigure(c, weight=0)
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
        n = len(stu)
        avg = round(sum(int(s["total_score"]) for s in stu.values()) / n) if n else 0
        self.count_label.config(text=f"共 {n} 人 · 均分 {avg}")
        self.sel_label.config(text=f"已选 {len(self.selected_ids)} 人" if self.selected_ids else "")

    def _set_status(self, text, color=FG_DIM):
        self.status_label.config(text=text, fg=color)

    def _center_on(self, sid):
        card = self._cards.get(sid)
        if not card or not card.winfo_exists():
            return
        self.inner.update_idletasks()
        total = max(1, self.inner.winfo_height())
        frac = max(0.0, min(1.0, (card.winfo_y() - 60) / total))
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
        if not self._cards:
            self._set_status("班级暂无学生", FG_WARN)
            return
        sid = random.choice(list(self._cards))
        info = self.all_students[self.current_class][sid]
        self.selected_ids = {sid}
        for s, card in self._cards.items():
            self._animate(card, CARD_SELECT if s == sid else CARD_BG)
        self._update_count()
        self._center_on(sid)
        self._set_status(f"🎲 随机点名：{sid} {info['name']}（{info['total_score']} 分）", FG_ACCENT)

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
        name = simpledialog.askstring("新建班级", "请输入班级名称：", parent=self.win)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.class_list:
            self._set_status("班级已存在", FG_DANGER)
            return
        self.class_list.append(name)
        self.all_students[name] = {}
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
        _save_json(WEEKLY_ARCHIVE, dict(self.week_archive))

    # ========== 通用小部件 ==========
    def _dialog(self, title, w, h):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.geometry(f"{w}x{h}")
        win.configure(bg=BG_MAIN)
        win.transient(self.win)
        win.grab_set()
        win.resizable(False, False)
        return win

    def _entry(self, parent, width=18):
        return tk.Entry(parent, width=width, font=(FONT, 11), bg=BG_CELL,
                        fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT)

    def _hint(self, parent, text):
        return tk.Label(parent, text=text, font=(FONT, 9), bg=BG_MAIN,
                        fg=FG_DIM, justify=tk.LEFT, wraplength=380)

    # ========== 学生管理 ==========
    def _add_student(self):
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
            stu[sid] = {"stu_id": sid, "name": name, "total_score": 0, "record": []}
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
                stu[sid] = {"stu_id": sid, "name": name, "total_score": 0, "record": []}
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
        if not self._selected_or_warn():
            return
        stu = self.all_students.get(self.current_class, {})
        names = [f"{sid} {stu[sid]['name']}" for sid in sorted(self.selected_ids) if sid in stu]
        if not messagebox.askyesno("确认删除", "确定删除以下学生？\n\n" + "\n".join(names),
                                   parent=self.win):
            return
        for sid in list(self.selected_ids):
            stu.pop(sid, None)
        self.selected_ids.clear()
        self._save_all()
        self._render_cards()
        self._set_status("已删除选中学生", FG_OK)

    def _edit_student(self):
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
    def _open_score(self):
        if self._score_win and self._score_win.winfo_exists():
            self._score_win.lift()
            return
        if not self._selected_or_warn():
            return

        win = self._dialog("评价打分", 500, 360)
        self._score_win = win
        tk.Label(win, text="评价打分", font=(FONT, 14, "bold"),
                 bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(14, 2))
        tk.Label(win, text=f"将作用于选中的 {len(self.selected_ids)} 名学生",
                 font=(FONT, 9), bg=BG_MAIN, fg=FG_DIM).pack()

        form = tk.Frame(win, bg=BG_MAIN)
        form.pack(padx=24, pady=10, fill=tk.X)
        form.columnconfigure(1, weight=1)

        # 加分 / 扣分
        tk.Label(form, text="类型", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=0, column=0, sticky="w", pady=6)
        op_var = tk.StringVar(value="加分")
        op_frame = tk.Frame(form, bg=BG_MAIN)
        op_frame.grid(row=0, column=1, sticky="w", pady=6)
        for txt in ("加分", "扣分"):
            tk.Radiobutton(op_frame, text=txt, variable=op_var, value=txt,
                           bg=BG_MAIN, fg=FG_TEXT, selectcolor=BG_CELL,
                           activebackground=BG_MAIN, activeforeground=FG_TEXT,
                           font=(FONT, 10)).pack(side=tk.LEFT, padx=(0, 16))

        # 分类
        tk.Label(form, text="分类", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=1, column=0, sticky="w", pady=6)
        cat_box = ttk.Combobox(form, values=list(reason_categories), state="readonly",
                               width=22, font=(FONT, 10))
        cat_box.current(0)
        cat_box.grid(row=1, column=1, sticky="w", pady=6)

        # 具体理由
        tk.Label(form, text="理由", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=2, column=0, sticky="w", pady=6)
        reason_box = ttk.Combobox(form, values=reason_categories["课堂表现"],
                                  state="readonly", width=26, font=(FONT, 10))
        reason_box.current(0)
        reason_box.grid(row=2, column=1, sticky="w", pady=6)

        def change_cat(_event=None):
            reason_box["values"] = reason_categories[cat_box.get()]
            reason_box.current(0)
        cat_box.bind("<<ComboboxSelected>>", change_cat)

        # 分值
        tk.Label(form, text="分值", font=(FONT, 10), bg=BG_MAIN, fg=FG_DIM)\
            .grid(row=3, column=0, sticky="w", pady=6)
        score_entry = self._entry(form, width=10)
        score_entry.grid(row=3, column=1, sticky="w", pady=6)
        score_entry.focus_set()

        err = tk.Label(win, text="", font=(FONT, 9), bg=BG_MAIN, fg=FG_DANGER)
        err.pack()

        def submit():
            mode = op_var.get()
            reason = reason_box.get().strip()
            score_str = score_entry.get().strip()
            if not score_str:
                err.config(text="分值不能为空")
                return
            try:
                score = int(score_str)
            except ValueError:
                err.config(text="分值必须是整数")
                return
            if score <= 0:
                err.config(text="分值必须大于 0")
                return
            if score > 10 and not messagebox.askyesno(
                    "提醒", f"分值 {score} 超过 10，确定提交？", parent=win):
                return

            now = time.strftime("%Y-%m-%d %H:%M:%S")
            week = time.strftime("%G-W%V")      # ISO 周次，避免出现 W00
            class_stu = self.all_students.get(self.current_class, {})
            changed = 0
            for sid in list(self.selected_ids):
                stu = class_stu.get(sid)
                if not stu:
                    continue
                stu["total_score"] += score if mode == "加分" else -score
                stu["record"].append({
                    "operate": mode, "score": score, "reason": reason,
                    "time": now, "week": week,
                })
                changed += 1
            self._save_all()
            win.destroy()
            self._score_win = None
            self._render_cards()
            self._set_status(f"已为 {changed} 名学生{mode} {score} 分 · {reason}", FG_OK)

        row = tk.Frame(win, bg=BG_MAIN)
        row.pack(pady=(6, 14))
        self._btn(row, "提交", submit, primary=True).pack(side=tk.LEFT, padx=6)
        self._btn(row, "取消", win.destroy).pack(side=tk.LEFT, padx=6)
        win.bind("<Return>", lambda e: submit())

    # ========== 撤回积分记录 ==========
    def _revoke_record(self):
        if not self._selected_or_warn():
            return
        sid = sorted(self.selected_ids)[0]
        stu = self.all_students[self.current_class][sid]
        if not stu["record"]:
            messagebox.showinfo("提示", f"{sid} {stu['name']} 暂无操作记录", parent=self.win)
            return

        lines = [f"{sid} {stu['name']} —— 请输入要撤回的序号：", ""]
        for idx, r in enumerate(stu["record"]):
            lines.append(f"{idx} | {r['time']} | {r['operate']}{r['score']}分 | {r['reason']}")
        num = simpledialog.askstring("撤回积分记录", "\n".join(lines), parent=self.win)
        if num is None:
            return
        try:
            idx = int(num.strip())
        except ValueError:
            messagebox.showerror("错误", "请输入合法数字", parent=self.win)
            return
        if idx < 0 or idx >= len(stu["record"]):
            messagebox.showerror("错误", "序号超出范围", parent=self.win)
            return

        rec = stu["record"].pop(idx)
        stu["total_score"] += -rec["score"] if rec["operate"] == "加分" else rec["score"]
        self._save_all()
        self._render_cards()
        self._set_status(f"已撤回：{rec['operate']}{rec['score']}分 {rec['reason']}", FG_OK)

    # ========== 积分明细 ==========
    def _query_detail(self):
        if not self._selected_or_warn():
            return
        parts = []
        for sid in sorted(self.selected_ids):
            stu = self.all_students[self.current_class][sid]
            parts.append(f"学号：{sid}    姓名：{stu['name']}    当前积分：{stu['total_score']}")
            if stu["record"]:
                for r in stu["record"]:
                    parts.append(f"    {r['time']}    {r['operate']}{r['score']}    {r['reason']}")
            else:
                parts.append("    （暂无记录）")
            parts.append("-" * 56)
        self._text_window("积分明细", "\n".join(parts))

    def _text_window(self, title, content):
        win = tk.Toplevel(self.win)
        win.title(title)
        win.geometry("720x480")
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
        return win, txt

    # ========== 周度统计 ==========
    def _week_chart(self):
        if not self._selected_or_warn():
            return
        sid = sorted(self.selected_ids)[0]
        stu = self.all_students[self.current_class][sid]

        week_data = defaultdict(lambda: {"add": 0, "sub": 0})
        for r in stu["record"]:
            d = week_data[r.get("week", "未知")]
            if r["operate"] == "加分":
                d["add"] += r["score"]
            else:
                d["sub"] += r["score"]
        if not week_data:
            messagebox.showinfo("提示", "暂无周度数据", parent=self.win)
            return

        win, txt = self._text_window(f"周度积分统计 · {stu['name']}", "")
        txt.config(state=tk.NORMAL)
        txt.tag_configure("dim", foreground=FG_DIM)
        txt.tag_configure("add", foreground=FG_OK)
        txt.tag_configure("sub", foreground=FG_DANGER)
        for w, d in sorted(week_data.items()):
            txt.insert(tk.END, f"{w:>9}  加分 {d['add']:>3}  ", "dim")
            txt.insert(tk.END, "■" * min(d["add"] // 2, 40) + "\n", "add")
            txt.insert(tk.END, f"{'':>9}  扣分 {d['sub']:>3}  ", "dim")
            txt.insert(tk.END, "□" * min(d["sub"] // 2, 40) + "\n\n", "sub")
        txt.config(state=tk.DISABLED)

    # ========== 低积分预警 ==========
    def _low_score_warn(self):
        class_stu = self.all_students.get(self.current_class, {})
        warn = [f"{sid}  {stu['name']}：{stu['total_score']} 分"
                for sid, stu in sorted(class_stu.items())
                if stu["total_score"] < LOW_SCORE_LIMIT]
        if warn:
            self._text_window(f"低积分预警（低于 {LOW_SCORE_LIMIT} 分）",
                              "\n".join(warn))
            self._set_status(f"{len(warn)} 名学生积分偏低", FG_WARN)
        else:
            messagebox.showinfo("低积分预警", "所有学生积分正常", parent=self.win)

    # ========== 手动修改积分 ==========
    def _manual_score(self):
        if not self._selected_or_warn():
            return
        num = simpledialog.askstring(
            "手动修改积分",
            f"为选中的 {len(self.selected_ids)} 名学生设置新积分：",
            parent=self.win,
        )
        if num is None:
            return
        try:
            new_score = int(num.strip())
        except ValueError:
            messagebox.showerror("错误", "请输入整数", parent=self.win)
            return
        class_stu = self.all_students[self.current_class]
        for sid in self.selected_ids:
            if sid in class_stu:
                class_stu[sid]["total_score"] = new_score
        self._save_all()
        self._render_cards()
        self._set_status(f"已将 {len(self.selected_ids)} 名学生积分设为 {new_score}", FG_OK)

    # ========== 本周归档 ==========
    def _archive_week(self):
        wk = time.strftime("%G-W%V")
        self.week_archive[wk].append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "class": self.current_class,
            "data": copy.deepcopy(self.all_students.get(self.current_class, {})),
        })
        self._save_all()
        self._set_status(f"{self.current_class} · {wk} 数据已归档", FG_OK)

    # ========== 更多功能（下拉菜单） ==========
    def _open_more_menu(self):
        menu = tk.Menu(self.win, tearoff=0, bg=BG_PANEL, fg=FG_TEXT,
                       activebackground=BG_CELL_ALT, activeforeground=FG_TEXT,
                       bd=0, font=(FONT, 10))
        groups = [
            [("新增学生", self._add_student),
             ("批量导入学生", self._batch_import),
             ("删除选中学生", self._delete_students),
             ("编辑学生资料", self._edit_student)],
            [("撤回积分记录", self._revoke_record),
             ("查询积分明细", self._query_detail),
             ("周度积分统计图", self._week_chart),
             ("低积分预警", self._low_score_warn)],
            [("手动修改积分", self._manual_score),
             ("本周数据归档", self._archive_week)],
        ]
        for i, group in enumerate(groups):
            if i:
                menu.add_separator()
            for text, cmd in group:
                menu.add_command(label=text, command=cmd)

        btn = self._more_btn
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()



