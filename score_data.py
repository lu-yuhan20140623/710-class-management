"""学生积分：数据文件路径、设置读写与分类奖惩理由（共享数据层）。"""
import json
import sys
from pathlib import Path

import score_records as store
from ui_theme import BG_CELL

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
    store.atomic_write_json(path, data)


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
