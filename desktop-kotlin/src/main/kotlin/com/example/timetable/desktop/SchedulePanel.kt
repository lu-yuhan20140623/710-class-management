package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Color
import java.awt.Component
import java.awt.Dimension
import java.awt.GridLayout
import java.time.LocalDateTime
import java.time.format.DateTimeParseException
import javax.swing.BorderFactory
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JList
import javax.swing.JOptionPane
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JSplitPane
import javax.swing.JTable
import javax.swing.SwingConstants
import javax.swing.table.AbstractTableModel
import javax.swing.table.TableCellRenderer

private data class Row(val name: String, val clock: String, val period: Int?, val subject: String)

class SchedulePanel : JPanel(BorderLayout()) {
    private val model = ScheduleTableModel()
    private val table = Theme.table(model)
    private val stateLabel = Theme.label("正在读取课节状态…", Theme.FG_ACCENT, Theme.FONT_TITLE)
    private val countdownLabel = Theme.label("--:--", Theme.FG_WARN, Theme.FONT_BIG)
    private val nextLabel = Theme.label("", Theme.FG_DIM)
    private val disabledModel = DefaultListModel<String>()
    private val disabledList = JList(disabledModel)

    init {
        background = Theme.BG_MAIN
        border = BorderFactory.createEmptyBorder(12, 12, 12, 12)

        table.defaultRenderer(Theme.centerRenderer())
        table.rowHeight = 44
        table.selectionBackground = Color(0x4A6FA5)

        val left = Theme.titled("本周课程表（双击单元格可调课）").apply {
            layout = BorderLayout()
            add(JScrollPane(table), BorderLayout.CENTER)
            val buttons = JPanel().apply {
                background = Theme.BG_PANEL
                add(Theme.button("恢复默认课表") {
                    if (JOptionPane.showConfirmDialog(
                            this@SchedulePanel, "确定清除全部调课记录？", "恢复默认",
                            JOptionPane.YES_NO_OPTION,
                        ) == JOptionPane.YES_OPTION
                    ) {
                        ScheduleService.clearOverrides()
                        refresh()
                    }
                })
                add(Theme.button("刷新") { refresh() })
            }
            add(buttons, BorderLayout.SOUTH)
        }

        val right = JPanel(BorderLayout()).apply {
            background = Theme.BG_PANEL
            border = BorderFactory.createEmptyBorder(0, 0, 0, 0)
            val card = Theme.titled("当前状态").apply {
                layout = GridLayout(0, 1, 8, 8)
                border = BorderFactory.createCompoundBorder(
                    BorderFactory.createLineBorder(Theme.BG_CELL_ALT),
                    BorderFactory.createEmptyBorder(16, 16, 16, 16),
                )
                add(stateLabel)
                add(countdownLabel.apply { horizontalAlignment = SwingConstants.CENTER })
                add(nextLabel)
            }
            add(card, BorderLayout.NORTH)

            val disabledPanel = Theme.titled("暂停提醒时间段").apply {
                layout = BorderLayout()
                add(JScrollPane(disabledList.apply { font = Theme.FONT_SMALL }), BorderLayout.CENTER)
                val bar = JPanel().apply {
                    background = Theme.BG_PANEL
                    add(Theme.button("添加") { addDisabledRange() })
                    add(Theme.button("删除") { removeDisabledRange() })
                }
                add(bar, BorderLayout.SOUTH)
            }
            add(disabledPanel, BorderLayout.CENTER)
        }

        val split = JSplitPane(JSplitPane.HORIZONTAL_SPLIT, left, right).apply {
            resizeWeight = 0.68
            dividerSize = 8
            background = Theme.BG_MAIN
        }
        add(split, BorderLayout.CENTER)
        refresh()
    }

    private fun JTable.defaultRenderer(renderer: TableCellRenderer) {
        (0 until columnModel.columnCount).forEach { column ->
            setDefaultRenderer(getColumnClass(column), renderer)
        }
    }

    fun refresh() {
        model.fireTableStructureChanged()
        refreshDisabled()
    }

    private fun refreshDisabled() {
        disabledModel.clear()
        ScheduleService.disabledRanges().forEach { range ->
            val start = (range["start"] as LocalDateTime).format(MINUTE_FORMAT)
            val end = (range["end"] as LocalDateTime).format(MINUTE_FORMAT)
            disabledModel.addElement("$start  →  $end   ${range.str("note")}".trimEnd())
        }
    }

    private fun addDisabledRange() {
        val now = LocalDateTime.now().withSecond(0).withNano(0)
        val startText = (JOptionPane.showInputDialog(
            this, "开始时间（格式 2026-11-22T14:00）：", "添加暂停时段",
            JOptionPane.QUESTION_MESSAGE, null, null, now.format(MINUTE_FORMAT),
        ) ?: return).toString()
        val endText = (JOptionPane.showInputDialog(
            this, "结束时间：", "添加暂停时段",
            JOptionPane.QUESTION_MESSAGE, null, null, now.plusHours(2).format(MINUTE_FORMAT),
        ) ?: return).toString()
        val note = JOptionPane.showInputDialog(this, "备注（可留空）：", "添加暂停时段", JOptionPane.QUESTION_MESSAGE)
            ?: ""
        val start = runCatching { LocalDateTime.parse(startText, MINUTE_FORMAT) }
            .getOrElse {
                JOptionPane.showMessageDialog(this, "开始时间格式不正确", "提示", JOptionPane.WARNING_MESSAGE)
                return
            }
        val end = runCatching { LocalDateTime.parse(endText, MINUTE_FORMAT) }
            .getOrElse {
                JOptionPane.showMessageDialog(this, "结束时间格式不正确", "提示", JOptionPane.WARNING_MESSAGE)
                return
            }
        if (!ScheduleService.addDisabled(start, end, note.trim())) {
            JOptionPane.showMessageDialog(this, "结束时间必须晚于开始时间", "提示", JOptionPane.WARNING_MESSAGE)
        }
        refreshDisabled()
    }

    private fun removeDisabledRange() {
        val index = disabledList.selectedIndex
        if (index < 0) {
            JOptionPane.showMessageDialog(this, "请先选择一个时间段", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        ScheduleService.removeDisabled(index)
        refreshDisabled()
    }

    fun updateState(info: Map<*, *>) {
        stateLabel.text = ScheduleService.stateLine(info)
        when (info.str("state")) {
            "in_class" -> {
                stateLabel.foreground = Theme.FG_OK
                val end = info.str("current_end")
                val seconds = runCatching {
                    val now = LocalDateTime.now()
                    val endDt = LocalDateTime.of(now.toLocalDate(), java.time.LocalTime.parse(end, HH_MM))
                    java.time.Duration.between(now, endDt).seconds.coerceAtLeast(0)
                }.getOrDefault(0)
                countdownLabel.text = "距离下课 %02d:%02d".format(seconds / 60, seconds % 60)
            }
            "disabled" -> {
                stateLabel.foreground = Theme.FG_DANGER
                countdownLabel.text = "暂停提醒"
            }
            else -> {
                stateLabel.foreground = Theme.FG_ACCENT
                val seconds = info.num("seconds_to_next")
                countdownLabel.text = if (seconds > 0) "距离上课 %02d:%02d".format(seconds / 60, seconds % 60) else "--:--"
            }
        }
        nextLabel.text = if (info.str("next_name").isNotBlank()) {
            "下一节：${info.str("next_name")}  ${info.str("next_subject")}  ${info.str("next_start")}"
        } else "今天课程已结束"
        table.repaint()
    }

    private inner class ScheduleTableModel : AbstractTableModel() {
        private fun rows(): List<Row> {
            val list = ScheduleService.periods.map { p ->
                Row(p.name, p.clock, p.id, "")
            }.toMutableList()
            val practice = ScheduleService.practice
            val evening = ScheduleService.evening
            list.add(Row(practice.name, practice.clock, null, ""))
            list.add(Row(evening.name, evening.clock, null, evening.name))
            return list
        }

        override fun getRowCount(): Int = rows().size

        override fun getColumnCount(): Int = 7

        override fun getColumnName(column: Int): String =
            if (column == 0) "节次" else if (column == 1) "时间" else ScheduleService.weekdayNames[column - 2]

        override fun getValueAt(rowIndex: Int, columnIndex: Int): Any {
            val row = rows()[rowIndex]
            return when (columnIndex) {
                0 -> row.name
                1 -> row.clock
                else -> {
                    val day = columnIndex - 2
                    if (row.period != null) ScheduleService.subject(day, row.period) else row.subject.ifBlank {
                        ScheduleService.practiceSubjects[day] ?: "晚辅"
                    }
                }
            }
        }

        override fun isCellEditable(rowIndex: Int, columnIndex: Int): Boolean =
            columnIndex >= 2 && rows()[rowIndex].period != null

        override fun setValueAt(value: Any?, rowIndex: Int, columnIndex: Int) {
            val period = rows()[rowIndex].period ?: return
            ScheduleService.setOverride(columnIndex - 2, period, value?.toString() ?: "")
            fireTableCellUpdated(rowIndex, columnIndex)
        }
    }
}
