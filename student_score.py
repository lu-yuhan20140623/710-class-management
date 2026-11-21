"""学生积分模块（2.1.0 起按职责拆分，本文件负责组合窗口并导出数据层符号）。

- 配色 / 字体与 ui.py 保持一致
- 数据文件沿用 740.6.py 的格式，可直接复用已有数据
- 窗口逻辑分布在 score_cards / score_students / score_scoring /
  score_reports / score_groups / score_menu 六个 mixin 中
"""

import sys
import tkinter as tk
from collections import defaultdict

import score_records as store
from score_data import (  # noqa: F401  —— 保持模块级符号仍可从 student_score 导入
    APP_DIR, CARD_BG, CARD_FLASH, CARD_SELECT, CARD_W, CHECK_BG, CLASS_FILE,
    FONT, GROUP_FILE, LOG_DIR, LOW_SCORE_LIMIT, OP_LOG, SETTINGS_FILE,
    STUDENT_FILE, WEEKLY_ARCHIVE, _load_json, _save_json, add_custom_reason,
    custom_reasons, load_settings, low_score_limit, reason_categories,
)
from score_cards import ScoreCardsMixin
from score_groups import ScoreGroupsMixin
from score_menu import ScoreMenuMixin
from score_reports import ScoreReportsMixin
from score_scoring import ScoreScoringMixin
from score_students import ScoreStudentsMixin
from ui import BG_MAIN, FG_WARN, fit_geometry


class StudentScoreWindow(
        ScoreCardsMixin, ScoreStudentsMixin, ScoreScoringMixin,
        ScoreReportsMixin, ScoreGroupsMixin, ScoreMenuMixin):
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
        self.sort_mode = "sid_asc"        # 学生卡片默认按学号升序
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
