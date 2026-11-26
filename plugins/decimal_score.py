"""小数积分（插件）

启用后，评价打分与手动改分可以录入最多两位小数的积分（如 1.5 / -0.5）；
禁用后自动恢复为只允许整数。开关在教师端「🧩 插件」菜单中随时切换。
"""

import math

PLUGIN = {
    "id": "decimal_score",
    "name": "小数积分",
    "version": "1.0.0",
    "api_version": 1,
    "description": "允许录入小数积分（最多两位小数），可在插件菜单随时启停",
    "author": "710",
    "requires": [],
    "priority": 5,
}

HINT = "已启用小数积分：支持最多两位小数，如 1.5 或 -0.5"


def _parse_decimal(text):
    raw = str(text).strip()
    if not raw:
        return None, "分值不能为空"
    if "e" in raw.lower():
        return None, "分值格式不正确（最多两位小数）"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, "分值必须是数字（正数加分，负数扣分）"
    if not math.isfinite(value):
        return None, "分值必须是有限数字"
    if "." in raw and len(raw.split(".", 1)[1]) > 2:
        return None, "分值最多保留两位小数"
    value = round(value, 2)
    return int(value) if value.is_integer() else value, ""


def register(ctx):
    ctx.scores.set_parser(_parse_decimal, order=10)
    ctx.scores.set_hint(HINT)
    ctx.log(HINT)
