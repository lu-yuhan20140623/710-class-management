package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.GridLayout
import javax.swing.BorderFactory
import javax.swing.DefaultComboBoxModel
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JCheckBox
import javax.swing.JComboBox
import javax.swing.JDialog
import javax.swing.JLabel
import javax.swing.JList
import javax.swing.JOptionPane
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JSpinner
import javax.swing.JSplitPane
import javax.swing.JTable
import javax.swing.JTextField
import javax.swing.ListSelectionModel
import javax.swing.SpinnerNumberModel
import javax.swing.event.ListSelectionEvent
import javax.swing.table.DefaultTableModel
import kotlin.random.Random

fun allClasses(): List<String> {
    val names = linkedSetOf<String>()
    listOf("student_data.txt", "group_data.txt", "hygiene_data.txt").forEach { file ->
        DataStore.loadMap(file).keys.forEach { names.add(it) }
    }
    if (names.isEmpty()) names.add(DataStore.className())
    return names.toList()
}

class ScorePanel : JPanel(BorderLayout()) {
    private val classCombo = JComboBox<String>()
    private val scopeCombo = JComboBox(arrayOf("按学生", "按小组"))
    private val reasonField = JTextField("积极发言", 18)
    private val scoreSpinner = JSpinner(SpinnerNumberModel(1, 1, 100, 1))
    private val groupModel = DefaultTableModel(arrayOf("小组", "人数", "积分"), 0)
    private val studentModel = DefaultTableModel(arrayOf("学号", "姓名", "积分", "组长"), 0)
    private val recordModel = DefaultTableModel(arrayOf("时间", "小组", "姓名", "原因", "增减"), 0)
    private val groupTable = Theme.table(groupModel)
    private val studentTable = Theme.table(studentModel)
    private val recordTable = Theme.table(recordModel)

    private var currentClass: String = DataStore.className()
    private var groupRows: List<GroupRow> = emptyList()
    private var studentRows: List<StudentRow> = emptyList()
    private var pointRows: List<PointRow> = emptyList()

    init {
        background = Theme.BG_MAIN
        border = BorderFactory.createEmptyBorder(12, 12, 12, 12)

        val top = JPanel().apply {
            background = Theme.BG_MAIN
            add(JLabel("班级"))
            add(classCombo.apply { font = Theme.FONT; preferredSize = Dimension(180, 32) })
            add(JLabel("  记分对象"))
            add(scopeCombo.apply { font = Theme.FONT })
            add(JLabel("  原因"))
            add(reasonField.apply { font = Theme.FONT })
            add(JLabel("  分值"))
            add(scoreSpinner.apply { font = Theme.FONT; preferredSize = Dimension(70, 32) })
            add(Theme.button("加分") { addPoints(1) })
            add(Theme.button("扣分") { addPoints(-1) })
        }
        add(top, BorderLayout.NORTH)

        groupTable.setSelectionMode(ListSelectionModel.SINGLE_SELECTION)
        groupTable.selectionModel.addListSelectionListener { _: ListSelectionEvent -> refreshStudents() }
        studentTable.setSelectionMode(ListSelectionModel.MULTIPLE_INTERVAL_SELECTION)
        recordTable.setSelectionMode(ListSelectionModel.SINGLE_SELECTION)

        val left = Theme.titled("小组积分榜").apply {
            layout = BorderLayout()
            add(JScrollPane(groupTable), BorderLayout.CENTER)
        }
        val right = Theme.titled("学生名单（可多选）").apply {
            layout = BorderLayout()
            add(JScrollPane(studentTable), BorderLayout.CENTER)
            val bar = JPanel().apply {
                background = Theme.BG_PANEL
                add(Theme.button("随机点名") { randomStudent() })
                add(Theme.button("添加学生") { addStudent() })
                add(Theme.button("删除学生") { removeStudent() })
                add(Theme.button("小组设置") { groupSettings() })
            }
            add(bar, BorderLayout.SOUTH)
        }
        val middle = JSplitPane(JSplitPane.HORIZONTAL_SPLIT, left, right).apply {
            resizeWeight = 0.4
            dividerSize = 8
            background = Theme.BG_MAIN
        }

        val bottom = Theme.titled("积分明细").apply {
            layout = BorderLayout()
            add(JScrollPane(recordTable), BorderLayout.CENTER)
            val bar = JPanel().apply {
                background = Theme.BG_PANEL
                add(Theme.button("撤销选中记录") { revokeRecord() })
                add(Theme.button("刷新") { refresh() })
            }
            add(bar, BorderLayout.SOUTH)
        }
        val mainSplit = JSplitPane(JSplitPane.VERTICAL_SPLIT, middle, bottom).apply {
            resizeWeight = 0.62
            dividerSize = 8
            background = Theme.BG_MAIN
        }
        add(mainSplit, BorderLayout.CENTER)

        classCombo.addActionListener { currentClass = classCombo.selectedItem?.toString() ?: currentClass; refresh() }
        refresh()
    }

    fun refresh() {
        val classes = allClasses()
        classCombo.model = DefaultComboBoxModel<String>(classes.toTypedArray())
        if (currentClass !in classes && classes.isNotEmpty()) currentClass = classes.first()
        classCombo.selectedItem = currentClass

        groupRows = ScoreService.groupRows(currentClass)
        groupModel.setRowCount(0)
        groupRows.forEachIndexed { index, row ->
            groupModel.addRow(arrayOf<Any>(row.name, row.count, row.total))
            if (index == 0) groupTable.setRowSelectionInterval(0, 0)
        }
        refreshStudents()
        refreshRecords()
    }

    private fun refreshStudents() {
        val selectedGroup = groupTable.selectedRow.takeIf { it in groupRows.indices }?.let { groupRows[it].name }
        studentRows = ScoreService.studentRows(currentClass).filter { selectedGroup == null || it.group == selectedGroup }
        studentModel.setRowCount(0)
        studentRows.forEach { row ->
            studentModel.addRow(arrayOf<Any>(row.sid, row.name, row.total, if (row.isLeader) "组长" else ""))
        }
    }

    private fun refreshRecords() {
        pointRows = ScoreService.pointRows(currentClass)
        recordModel.setRowCount(0)
        val selectedGroup = groupTable.selectedRow.takeIf { it in groupRows.indices }?.let { groupRows[it].name }
        pointRows.filter { selectedGroup == null || it.group == selectedGroup }.take(200).forEach { row ->
            recordModel.addRow(arrayOf<Any>(row.time, row.group, row.name, row.reason, row.delta))
        }
    }

    private fun addPoints(sign: Int) {
        val raw = scoreSpinner.value as? Number ?: return
        val delta = raw.toInt() * sign
        val reason = reasonField.text.trim().ifBlank { "未填写原因" }
        val count = if (scopeCombo.selectedIndex == 0) {
            ScoreService.addPoint(currentClass, selectedSids(), reason, delta)
        } else {
            ScoreService.addGroupPoint(currentClass, selectedGroups(), reason, delta)
        }
        if (count == 0) {
            JOptionPane.showMessageDialog(this, "请先选中要记分的学生或小组", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        refresh()
    }

    private fun selectedSids(): List<String> =
        studentTable.selectedRows.toList().mapNotNull { row -> studentRows.getOrNull(row)?.sid }

    private fun selectedGroups(): List<String> =
        groupTable.selectedRows.toList().mapNotNull { row -> groupRows.getOrNull(row)?.name }

    private fun selectedRecord(): PointRow? {
        val row = recordTable.selectedRow
        if (row < 0) return null
        val group = recordModel.getValueAt(row, 1)?.toString()
        val name = recordModel.getValueAt(row, 2)?.toString()
        return pointRows.firstOrNull { it.group == group && it.name == name && it.time == recordModel.getValueAt(row, 0) }
    }

    private fun revokeRecord() {
        val record = selectedRecord()
        if (record == null) {
            JOptionPane.showMessageDialog(this, "请先选中一条积分记录", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        if (ScoreService.revokeStudentRecord(currentClass, record.sid, record.recordIndex)) refresh()
    }

    private fun randomStudent() {
        val pool = studentRows.filter { row ->
            val selected = groupTable.selectedRow.takeIf { it in groupRows.indices }?.let { groupRows[it].name }
            selected == null || row.group == selected
        }
        if (pool.isEmpty()) {
            JOptionPane.showMessageDialog(this, "当前没有可选学生", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        val picked = pool[Random(System.currentTimeMillis()).nextInt(pool.size)]
        JOptionPane.showMessageDialog(
            this, "${picked.group}  ${picked.name}（${picked.sid}）", "随机点名", JOptionPane.INFORMATION_MESSAGE,
        )
    }

    private fun addStudent() {
        val sid = JOptionPane.showInputDialog(this, "学号：", "添加学生", JOptionPane.QUESTION_MESSAGE)?.trim()
            ?: return
        val name = JOptionPane.showInputDialog(this, "姓名：", "添加学生", JOptionPane.QUESTION_MESSAGE)?.trim()
            ?: return
        ScoreService.addStudent(currentClass, sid, name)?.let {
            JOptionPane.showMessageDialog(this, it, "提示", JOptionPane.WARNING_MESSAGE)
        }
        refresh()
    }

    private fun removeStudent() {
        val sids = selectedSids()
        if (sids.isEmpty()) {
            JOptionPane.showMessageDialog(this, "请先选中学生", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        if (JOptionPane.showConfirmDialog(
                this, "确定删除选中的 ${sids.size} 名学生？", "删除学生", JOptionPane.YES_NO_OPTION,
            ) != JOptionPane.YES_OPTION) return
        sids.forEach { ScoreService.removeStudent(currentClass, it) }
        refresh()
    }

    private fun groupSettings() {
        val groupName = selectedGroups().firstOrNull()
        if (groupName == null) {
            JOptionPane.showMessageDialog(this, "请先选中一个小组", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        val students = ScoreService.studentRows(currentClass)
        val group = ScoreService.classGroups(currentClass)[groupName].asMap()
        val selected = group["members"].asList().map { it?.toString() }.toSet()
        val listModel = DefaultListModel<String>()
        val labels = students.map { "${it.group}  ${it.sid} ${it.name}" }
        labels.forEachIndexed { index, label ->
            listModel.addElement(label)
            if (students[index].sid in selected) listModel.set(index, "✓ $label")
        }
        val list = JList(listModel).apply {
            selectionMode = ListSelectionModel.MULTIPLE_INTERVAL_SELECTION
            font = Theme.FONT
        }
        val leaderModel = DefaultComboBoxModel<String>(students.map { it.sid }.toTypedArray())
        val leaderCombo = JComboBox(leaderModel).apply { font = Theme.FONT }
        val currentLeader = group.str("leader")
        val idx = students.indexOfFirst { it.sid == currentLeader }
        if (idx >= 0) leaderCombo.selectedIndex = idx

        val panel = JPanel(BorderLayout(8, 8)).apply {
            background = Theme.BG_PANEL
            add(JLabel("成员（多选，勾选状态仅作提示，以当前选中为准）"), BorderLayout.NORTH)
            add(JScrollPane(list.apply { visibleRowCount = 12 }), BorderLayout.CENTER)
            val south = JPanel().apply {
                background = Theme.BG_PANEL
                add(JLabel("组长"))
                add(leaderCombo)
            }
            add(south, BorderLayout.SOUTH)
        }
        val dialog = JDialog(JOptionPane.getFrameForComponent(this), "小组设置 · $groupName", true).apply {
            contentPane.add(panel)
            size = Dimension(420, 460)
            setLocationRelativeTo(this@ScorePanel)
        }
        val apply = JButton("保存").apply {
            addActionListener {
                val members = list.selectedIndices.toList().mapNotNull { students.getOrNull(it)?.sid }
                ScoreService.setGroupMembers(
                    currentClass, groupName, members, leaderCombo.selectedItem?.toString() ?: "",
                )
                dialog.dispose()
                refresh()
            }
        }
        val cancel = JButton("取消").apply { addActionListener { dialog.dispose() } }
        val buttons = JPanel().apply {
            background = Theme.BG_PANEL
            add(apply); add(cancel)
        }
        dialog.contentPane.add(buttons, BorderLayout.SOUTH)
        dialog.isVisible = true
    }

}
