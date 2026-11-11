"""
后台状态机 + 唤起 overlay 事件
- 内部每 0.5s 刷新一次状态
- 跨状态变化时触发事件：进入倒计时窗口、预备铃响、进入上课、禁用期等
- UI 端订阅这些事件来显示 / 关闭 overlay
"""

import threading
import time
from typing import Callable, Optional

import schedule


class BackendService:
    """后台常驻：实时追踪课节状态，供 UI 查询和订阅事件。"""

    # 事件类型
    EVT_STATE_CHANGED   = "state_changed"     # 任意状态变化
    EVT_ENTER_COUNTING  = "enter_counting"    # 进入 2 分钟倒计时窗口（需要唤起 overlay）
    EVT_PREBELL         = "prebell"           # 预备铃响
    EVT_ENTER_CLASS     = "enter_class"       # 开始上课
    EVT_LEAVE_COUNTING  = "leave_counting"    # 离开倒计时窗口（倒计时结束）
    EVT_DISABLED        = "disabled"          # 进入禁用时间段
    EVT_LEAVE_DISABLED  = "leave_disabled"    # 离开禁用时间段

    def __init__(self, tick_interval: float = 0.5):
        self.tick_interval = tick_interval

        # 内部锁和状态
        self._state_lock = threading.Lock()
        self._state: Optional[dict] = None

        # 事件回调集合（支持多订阅者）
        self._listeners: dict[str, list[Callable[[dict], None]]] = {
            e: [] for e in [self.EVT_STATE_CHANGED, self.EVT_ENTER_COUNTING,
                            self.EVT_PREBELL, self.EVT_ENTER_CLASS,
                            self.EVT_LEAVE_COUNTING, self.EVT_DISABLED,
                            self.EVT_LEAVE_DISABLED]
        }

        # 上一次快照的关键字段（用于状态对比、触发事件）
        self._last_key: Optional[tuple] = None
        self._was_counting = False
        self._was_prebell = False
        self._was_in_class = False
        self._was_disabled = False

        # 线程控制
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ---- 事件订阅 ----
    def subscribe(self, event: str, cb: Callable[[dict], None]):
        if event in self._listeners:
            self._listeners[event].append(cb)

    def _emit(self, event: str, info: dict):
        for cb in self._listeners.get(event, []):
            try:
                cb(dict(info))
            except Exception as e:
                print(f"[Backend] emit {event} error: {e}")

    # ---- 启动/停止 ----
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    # ---- 主循环 ----
    def _loop(self):
        while self._running:
            info = schedule.find_current_period()

            # 快照
            with self._state_lock:
                self._state = info

            # 对比状态变化，触发事件
            key = (info["state"], info.get("current_period"),
                   info.get("next_period"), info.get("disabled"))

            if key != self._last_key:
                self._emit(self.EVT_STATE_CHANGED, info)
                self._last_key = key

            # 进入倒计时窗口
            now_counting = info.get("is_counting", False)
            if now_counting and not self._was_counting:
                self._emit(self.EVT_ENTER_COUNTING, info)
            # 离开倒计时窗口（不管什么原因：到预备铃、禁用、跳过）
            if self._was_counting and not now_counting:
                self._emit(self.EVT_LEAVE_COUNTING, info)
            self._was_counting = now_counting

            # 预备铃
            now_prebell = info.get("is_prebell", False)
            if now_prebell and not self._was_prebell:
                self._emit(self.EVT_PREBELL, info)
            self._was_prebell = now_prebell

            # 进入上课
            now_in_class = (info["state"] == "in_class")
            if now_in_class and not self._was_in_class:
                self._emit(self.EVT_ENTER_CLASS, info)
            self._was_in_class = now_in_class

            # 禁用时间段
            now_disabled = info.get("disabled", False)
            if now_disabled and not self._was_disabled:
                self._emit(self.EVT_DISABLED, info)
            elif self._was_disabled and not now_disabled:
                self._emit(self.EVT_LEAVE_DISABLED, info)
            self._was_disabled = now_disabled

            time.sleep(self.tick_interval)

    # ---- 对外查询 ----
    def get_state(self) -> dict:
        with self._state_lock:
            return dict(self._state) if self._state else schedule.find_current_period()

    # ---- 课表 / 时间段 API ----
    def override(self, day: int, period: int, subject: str):
        schedule.set_override(day, period, subject)

    def get_subject(self, day: int, period: int) -> str:
        return schedule.get_subject(day, period)

    def get_all_overrides(self) -> dict:
        return schedule.get_all_overrides()

    def add_disabled_range(self, start, end, note: str = "") -> bool:
        return schedule.add_disabled_range(start, end, note)

    def remove_disabled_range(self, index: int) -> bool:
        return schedule.remove_disabled_range(index)

    def get_all_disabled_ranges(self) -> list:
        return schedule.get_all_disabled_ranges()

    @property
    def all_periods(self):
        return list(schedule.PERIODS.keys())
