"""学生积分：更多功能下拉菜单与插件入口。"""
import tkinter as tk
from tkinter import messagebox

from score_data import FONT
from ui import BG_CELL_ALT, BG_PANEL, FG_TEXT


class ScoreMenuMixin:
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
