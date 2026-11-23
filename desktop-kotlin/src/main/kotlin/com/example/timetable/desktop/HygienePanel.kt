package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Color
import java.awt.Dimension
import java.awt.Font
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.GridLayout
import java.awt.RenderingHints
import javax.swing.BorderFactory
import javax.swing.DefaultComboBoxModel
import javax.swing.DefaultListModel
import javax.swing.JComboBox
import javax.swing.JLabel
import javax.swing.JList
import javax.swing.JOptionPane
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JSpinner
import javax.swing.JTable
import javax.swing.JTextField
import javax.swing.ListSelectionModel
import javax.swing.SpinnerNumberModel
import javax.swing.SwingUtilities
import javax.swing.table.DefaultTableModel
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

class HygienePanel : JPanel(BorderLayout()) {
    private val classCombo = JComboBox<String>()
    private val studentModel = DefaultListModel<String>()
    private val studentList = JList(studentModel)
    private val reasonCombo = JComboBox<String>()
    private val scoreSpinner = JSpinner(SpinnerNumberModel(1, 1, 100, 1))
    private val noteField = JTextField(14)
    private val byField = JTextField("值日生", 10)
    private val recordModel = DefaultTableModel(arrayOf("时间", "小组", "姓名", "原因", "扣分", "操作人"), 0)
    private val recordTable = Theme.table(recordModel)
    private val barChart = BarChartPanel()
    private val pieChart = PieChartPanel()
    private var currentClass = DataStore.className()
    private var rows: List<HygieneRow> = emptyList()

    init {
        background = Theme.BG_MAIN
        border = BorderFactory.createEmptyBorder(12, 12, 12, 12)

        val top = JPanel().apply {
            background = Theme.BG_MAIN
            add(JLabel("班级"))
            add(classCombo.apply { font = Theme.FONT; preferredSize = Dimension(180, 32) })
            add(JLabel("  扣分原因"))
            add(reasonCombo.apply { font = Theme.FONT; preferredSize = Dimension(190, 32); isEditable = true })
            add(JLabel("  分值"))
            add(scoreSpinner.apply { font = Theme.FONT; preferredSize = Dimension(70, 32) })
            add(JLabel("  备注"))
            add(noteField.apply { font = Theme.FONT })
            add(JLabel("  操作人"))
            add(byField.apply { font = Theme.FONT })
            add(Theme.button("记扣分") { addRecord() })
        }
        add(top, BorderLayout.NORTH)

        val left = Theme.titled("选择学生（可多选）").apply {
            layout = BorderLayout()
            add(JScrollPane(studentList.apply {
                font = Theme.FONT
                selectionMode = ListSelectionModel.MULTIPLE_INTERVAL_SELECTION
                visibleRowCount = 18
            }), BorderLayout.CENTER)
        }

        val charts = JPanel(GridLayout(1, 2, 10, 10)).apply {
            background = Theme.BG_MAIN
            add(Theme.titled("小组扣分").apply { layout = BorderLayout(); add(barChart, BorderLayout.CENTER) })
            add(Theme.titled("原因分布").apply { layout = BorderLayout(); add(pieChart, BorderLayout.CENTER) })
        }

        val middle = javax.swing.JSplitPane(javax.swing.JSplitPane.HORIZONTAL_SPLIT, left, charts).apply {
            resizeWeight = 0.28
            dividerSize = 8
            background = Theme.BG_MAIN
        }

        val bottom = Theme.titled("扣分明细").apply {
            layout = BorderLayout()
            add(JScrollPane(recordTable), BorderLayout.CENTER)
            val bar = JPanel().apply {
                background = Theme.BG_PANEL
                add(Theme.button("撤销选中") { revoke() })
                add(Theme.button("刷新") { refresh() })
            }
            add(bar, BorderLayout.SOUTH)
        }
        val split = javax.swing.JSplitPane(javax.swing.JSplitPane.VERTICAL_SPLIT, middle, bottom).apply {
            resizeWeight = 0.55
            dividerSize = 8
            background = Theme.BG_MAIN
        }
        add(split, BorderLayout.CENTER)

        recordTable.setSelectionMode(ListSelectionModel.SINGLE_SELECTION)
        classCombo.addActionListener {
            currentClass = classCombo.selectedItem?.toString() ?: currentClass
            refresh()
        }
        refresh()
    }

    fun refresh() {
        val classes = allClasses()
        classCombo.model = DefaultComboBoxModel<String>(classes.toTypedArray())
        if (currentClass !in classes && classes.isNotEmpty()) currentClass = classes.first()
        classCombo.selectedItem = currentClass

        val students = ScoreService.studentRows(currentClass)
        studentModel.clear()
        students.forEach { studentModel.addElement("${studentModel.size() + 1}. ${studentModelLabel(it)}") }
        studentList.selectedIndices = intArrayOf()
        studentList.putClientProperty("students", students)

        reasonCombo.model = DefaultComboBoxModel<String>(HygieneService.reasons(currentClass).toTypedArray())
        if (reasonCombo.itemCount > 0) reasonCombo.selectedIndex = 0

        rows = HygieneService.records(currentClass)
        recordModel.setRowCount(0)
        rows.take(300).forEach { row ->
            recordModel.addRow(arrayOf<Any>(row.time, row.group, row.name, row.reason, row.score, row.by))
        }
        barChart.data = HygieneService.groupRows(currentClass)
        pieChart.data = HygieneService.reasonRows(currentClass)
        barChart.repaint()
        pieChart.repaint()
    }

    private fun studentModelLabel(row: StudentRow) =
        "${row.sid}  ${row.name}  ${row.group}  ${row.total}分"

    private fun selectedStudentRows(): List<StudentRow> {
        @Suppress("UNCHECKED_CAST")
        val students = studentList.getClientProperty("students") as? List<StudentRow> ?: return emptyList()
        return studentList.selectedIndices.toList().mapNotNull { students.getOrNull(it) }
    }

    private fun addRecord() {
        val sids = selectedStudentRows().map { it.sid }
        if (sids.isEmpty()) {
            JOptionPane.showMessageDialog(this, "请先选择学生", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        val reason = reasonCombo.selectedItem?.toString()?.trim().takeUnless { it.isNullOrBlank() } ?: "未填写原因"
        val score = (scoreSpinner.value as? Number)?.toInt() ?: 1
        val count = HygieneService.addRecord(
            currentClass, sids, reason, score, noteField.text.trim(), byField.text.trim().ifBlank { "未记录" },
        )
        if (count > 0) refresh()
    }

    private fun revoke() {
        val index = recordTable.selectedRow
        if (index < 0 || index >= rows.size) {
            JOptionPane.showMessageDialog(this, "请先选中一条扣分记录", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        if (HygieneService.revoke(currentClass, rows[index].recordIndex)) refresh()
    }

    private inner class BarChartPanel : JPanel() {
        var data: List<Pair<String, Int>> = emptyList()

        init {
            background = Theme.BG_PANEL
            preferredSize = Dimension(320, 220)
        }

        override fun paintComponent(g: Graphics) {
            super.paintComponent(g)
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            if (data.isEmpty()) {
                g2.color = Theme.FG_DIM
                g2.font = Theme.FONT
                g2.drawString("暂无扣分记录", 20, 40)
                return
            }
            val max = data.maxOf { it.second }.coerceAtLeast(1)
            val left = 110
            val right = width - 30
            val top = 24
            val rowHeight = (height - 40) / data.size.coerceAtLeast(1)
            val colors = listOf(Color(0xE06C75), Color(0xE5C07B), Color(0x98C379), Color(0x61AFEF), Color(0xC678DD))
            data.forEachIndexed { index, (name, value) ->
                val y = top + index * rowHeight
                g2.color = Theme.FG_TEXT
                g2.font = Theme.FONT_SMALL
                g2.drawString(name, 8, y + rowHeight / 2 + 5)
                val barWidth = ((right - left) * value / max).toInt().coerceAtLeast(2)
                g2.color = colors[index % colors.size]
                g2.fillRoundRect(left, y + 4, barWidth, (rowHeight - 10).coerceAtLeast(6), 8, 8)
                g2.color = Theme.FG_WARN
                g2.drawString(value.toString(), left + barWidth + 8, y + rowHeight / 2 + 5)
            }
        }
    }

    private inner class PieChartPanel : JPanel() {
        var data: List<Pair<String, Int>> = emptyList()
        private val palette = listOf(
            Color(0xE06C75), Color(0xE5C07B), Color(0x98C379), Color(0x61AFEF),
            Color(0xC678DD), Color(0x56B6C2), Color(0xD19A66), Color(0xABB2BF),
        )

        init {
            background = Theme.BG_PANEL
            preferredSize = Dimension(320, 220)
        }

        override fun paintComponent(g: Graphics) {
            super.paintComponent(g)
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            if (data.isEmpty()) {
                g2.color = Theme.FG_DIM
                g2.font = Theme.FONT
                g2.drawString("暂无扣分记录", 20, 40)
                return
            }
            val total = data.sumOf { it.second }.coerceAtLeast(1)
            val cx = 92
            val cy = height / 2
            val radius = minOf(78, height / 2 - 16)
            var start = 0.0
            data.take(8).forEachIndexed { index, (name, value) ->
                val sweep = 360.0 * value / total
                g2.color = palette[index % palette.size]
                g2.fillArc(cx - radius, cy - radius, radius * 2, radius * 2, start.toInt(), sweep.toInt().coerceAtLeast(1))
                start += sweep
            }
            g2.color = Theme.BG_PANEL
            g2.fillOval(cx - radius / 2, cy - radius / 2, radius, radius)
            g2.color = Theme.FG_TEXT
            g2.font = Theme.FONT.deriveFont(Font.BOLD, 15f)
            val label = total.toString()
            g2.drawString(label, cx - g2.fontMetrics.stringWidth(label) / 2, cy + 5)

            g2.font = Theme.FONT_SMALL
            data.take(6).forEachIndexed { index, (name, value) ->
                val y = 28 + index * 22
                g2.color = palette[index % palette.size]
                g2.fillRoundRect(190, y - 10, 12, 12, 4, 4)
                g2.color = Theme.FG_TEXT
                val text = if (name.length > 10) name.take(9) + "…" else name
                g2.drawString("$text ($value)", 210, y)
            }
        }
    }
}
