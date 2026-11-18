"""
独立的倒计时窗口（可缩放，有标题栏）
- 状态驱动：自己每秒 tick 刷新 schedule 状态
- 退出条件：进入上课时 / 离开倒计时窗口 / 禁用期 / 已放学 / 周末
- 与 backend_service.py 配合：backend 决定何时 spawn/kill overlay
  （状态变化→kill；倒计时窗口内没 overlay→spawn）
"""
import sys
import tkinter as tk
from datetime import datetime

import schedule_core as sch
from ui import enable_high_dpi, dpi_scale, work_area

BG = "#1a1a2e"
BG_CARD = "#16213e"
FG_COUNT = "#ffffff"
FG_SUBJECT = "#7ab8ff"
FG_LABEL = "#888899"
FG_PREBELL = "#ff6644"
FG_IN_CLASS = "#66cc88"


class CountdownWindow:
    def __init__(self):
        # 进程级 DPI 感知必须在创建窗口之前设置，否则高分屏上整窗发虚
        enable_high_dpi()
        self.root = tk.Tk()
        enable_high_dpi(self.root)
        self.root.title("课程表 · 倒计时")
        self.root.configure(bg=BG)

        # 窗口尺寸随 DPI 放大，并钳制到任务栏之外的可用区域
        k = dpi_scale(self.root)
        wl, wt, wr, wb = work_area(self.root)
        w = min(int(520 * k), int((wr - wl) * 0.95))
        h = min(int(420 * k), int((wb - wt) * 0.92))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(min(int(380 * k), w), min(int(320 * k), h))
        wrap = int(460 * k)

        # 关闭即退出
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Escape>", lambda e: self._close())

        # 标题栏提示
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill=tk.X, padx=20, pady=(18, 4))
        self.lbl_title = tk.Label(top, text="", font=("Microsoft YaHei UI", 13),
                                   bg=BG, fg=FG_LABEL)
        self.lbl_title.pack(anchor=tk.W)

        # 中间大号倒计时
        mid = tk.Frame(self.root, bg=BG)
        mid.pack(expand=True, fill=tk.BOTH, padx=20, pady=4)

        self.lbl_countdown = tk.Label(mid, text="", font=("Consolas", 90, "bold"),
                                       bg=BG, fg=FG_COUNT)
        self.lbl_countdown.pack(pady=(8, 4))

        # 科目
        self.lbl_subject = tk.Label(mid, text="", font=("Microsoft YaHei UI", 30, "bold"),
                                     bg=BG, fg=FG_SUBJECT)
        self.lbl_subject.pack(pady=2)

        # 提示文字
        self.lbl_hint = tk.Label(mid, text="", font=("Microsoft YaHei UI", 14),
                                  bg=BG, fg=FG_LABEL, wraplength=wrap, justify=tk.CENTER)
        self.lbl_hint.pack(pady=(8, 4))

        # 底部状态卡
        bottom = tk.Frame(self.root, bg=BG_CARD)
        bottom.pack(fill=tk.X, padx=20, pady=(4, 16))
        self.lbl_bottom = tk.Label(bottom, text="", font=("Microsoft YaHei UI", 10),
                                    bg=BG_CARD, fg=FG_LABEL, justify=tk.LEFT)
        self.lbl_bottom.pack(anchor=tk.W, padx=14, pady=10)

        self._tick()
        self.root.mainloop()

    def _close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _tick(self):
        try:
            info = sch.find_current_period()
            should_continue = self._render(info)
        except Exception as e:
            print(f"[overlay] tick error: {e}", flush=True)
            should_continue = True

        if should_continue:
            self.root.after(500, self._tick)
        else:
            self._close()

    def _render(self, info: dict) -> bool:
        """
        渲染当前状态，返回 True 继续运行，False 退出窗口。
        """
        day = info["day"]
        weekday = sch.WEEKDAY_NAMES[day] if day >= 0 else "周末"
        state = info["state"]

        # ========== 退出条件 ==========
        # 禁用期 / 周末 / 已放学 → 退出
        if info.get("disabled") or day < 0 or state == "after_school":
            return False

        # 进入上课 → 退出（backend 负责 kill 也 OK，这里自己主动退）
        if state == "in_class":
            return False

        # 不在倒计时窗口也不在预备铃 → 退出
        is_counting = info.get("is_counting", False)
        is_prebell = info.get("is_prebell", False)
        if not (is_counting or is_prebell):
            return False

        # ========== 显示 ==========
        next_period = info.get("next_period") or info.get("current_period") or "?"
        next_subject = info.get("next_subject") or sch.get_subject(day, next_period) or "?"
        # 正课显示「第N节」，午间小练 / 晚辅直接显示名称
        next_name = info.get("next_name") or (
            f"第{next_period}节" if isinstance(next_period, int) else "?")

        title = f"{weekday} · {next_name}"
        if next_subject and next_subject != next_name:
            title += f" · {next_subject}"
        self.lbl_title.config(text=title)

        if is_prebell:
            # 预备铃阶段：显示科目 + 提示
            self.lbl_countdown.config(text="准备上课", fg=FG_PREBELL, font=("Microsoft YaHei UI", 44, "bold"))
            self.lbl_subject.config(text=f"📚 {next_subject}")
            self.lbl_hint.config(text="🔔 预备铃已响 · 请回到座位 · 关闭电子设备")
            self.lbl_bottom.config(text=f"上课时间：{(info.get('next_start') or '').strftime('%H:%M') if info.get('next_start') else ''}  课程：{next_subject}")
            return True

        if is_counting:
            mm, ss = divmod(max(info.get("seconds_to_prebell", 0), 0), 60)
            self.lbl_countdown.config(text=f"{mm:02d}:{ss:02d}", fg=FG_COUNT, font=("Consolas", 90, "bold"))
            self.lbl_subject.config(text=next_subject)
            self.lbl_hint.config(text="⏰ 距离预备铃还有")
            start = info.get("next_start")
            self.lbl_bottom.config(text=f"上课时间：{start.strftime('%H:%M') if start else ''}  课程：{next_subject}")
            return True

        return False


if __name__ == "__main__":
    try:
        CountdownWindow()
    except KeyboardInterrupt:
        sys.exit(0)
