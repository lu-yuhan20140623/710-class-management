package com.example.timetable.teacher

import android.app.Activity
import android.app.AlertDialog
import android.app.Dialog
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Environment
import android.text.InputType
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TableLayout
import android.widget.TableRow
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.time.LocalDateTime
import java.util.Timer
import kotlin.concurrent.timerTask
import kotlin.random.Random

private val W_PANEL = Color.rgb(0x2A, 0x2A, 0x3A)
private val W_CELL = Color.rgb(0x3A, 0x3A, 0x4A)
private val W_CELL_ALT = Color.rgb(0x44, 0x44, 0x58)
private val W_TEXT = Color.rgb(0xE8, 0xE8, 0xF0)
private val W_DIM = Color.rgb(0x90, 0x90, 0xA0)
private val W_ACCENT = Color.rgb(0x7A, 0xB8, 0xFF)
private val W_WARN = Color.rgb(0xFF, 0xCC, 0x66)
private val W_OK = Color.rgb(0x66, 0xCC, 0x88)
private val W_DANGER = Color.rgb(0xFF, 0x6B, 0x6B)

private fun Context.wdp(v: Int) = (v * resources.displayMetrics.density).toInt()

private fun Context.wText(text: String, size: Int = 15, color: Int = W_TEXT, bold: Boolean = false) =
    TextView(this).apply {
        this.text = text
        textSize = size.toFloat()
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

private fun Context.wButton(label: String, click: () -> Unit) = Button(this).apply {
    text = label
    textSize = 13f
    setBackgroundColor(W_CELL)
    setTextColor(W_TEXT)
    setOnClickListener { click() }
}

private fun Context.wEdit(hint: String, value: String = "", number: Boolean = false) = EditText(this).apply {
    this.hint = hint
    setText(value)
    setTextColor(W_TEXT)
    setHintTextColor(W_DIM)
    setBackgroundColor(W_CELL)
    if (number) inputType = InputType.TYPE_CLASS_NUMBER
}

private fun Context.wSpinner(items: List<String>) = Spinner(this).apply {
    adapter = ArrayAdapter(this@wSpinner, android.R.layout.simple_spinner_item, items).apply {
        setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
    }
}

private fun Context.wSection(title: String) = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    setBackgroundColor(W_PANEL)
    setPadding(wdp(10), wdp(8), wdp(10), wdp(10))
    addView(wText(title, 16, W_ACCENT, true))
}

private fun LinearLayout.wMargins(top: Int = 6, bottom: Int = 6) {
    (layoutParams as? LinearLayout.LayoutParams)?.setMargins(0, top, 0, bottom)
}

abstract class ParityPage(context: Context) : Page(context)

class ParitySchedulePage(context: Context, private val readOnly: Boolean = false) : ParityPage(context) {
    private val stateLabel = context.wText("正在读取状态…", 17, W_ACCENT, true)
    private val countLabel = context.wText("--:--", 40, W_WARN, true).apply { gravity = Gravity.CENTER }
    private val nextLabel = context.wText("", 13, W_DIM)
    private val disabledText = context.wText("", 13, W_DIM)
    private val table = TableLayout(context).apply { setStretchAllColumns(true) }

    init {
        val split = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        val left = context.wSection(if (readOnly) "本周课程表（只读）" else "本周课程表（点击单元格可调课）")
        left.addView(table, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        val right = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        val card = context.wSection("当前状态")
        card.addView(stateLabel.apply { setPadding(0, context.wdp(8), 0, context.wdp(4)) })
        card.addView(countLabel)
        card.addView(nextLabel)
        val disabled = context.wSection("暂停提醒时间段")
        disabled.addView(disabledText)
        if (!readOnly) {
            val row = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            row.addView(context.wButton("添加") { addDisabled() }, wBtn())
            row.addView(context.wButton("删除") { removeDisabled() }, wBtn())
            row.addView(context.wButton("恢复默认") { reset() }, wBtn())
            disabled.addView(row)
        }
        right.addView(card)
        right.addView(disabled)
        split.addView(left, LinearLayout.LayoutParams(0, WRAP_CONTENT, 0.68f))
        split.addView(right, LinearLayout.LayoutParams(0, WRAP_CONTENT, 0.32f))
        body.addView(split)
        refreshGrid()
        refreshDisabled()
    }

    private fun wBtn() = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply { setMargins(2, 6, 2, 2) }

    private fun refreshGrid() {
        table.removeAllViews()
        val header = TableRow(context)
        listOf("节次", "时间").forEach {
            header.addView(context.wText(it, 12, W_ACCENT, true).apply { gravity = Gravity.CENTER }, wCell(1f))
        }
        ScheduleService.weekdayNames.forEachWithHeader(header)
        table.addView(header)
        val rows = ScheduleService.periods.map { it.name to it.clock }.toMutableList()
        rows.add(ScheduleService.practice.name to ScheduleService.practice.clock)
        rows.add(ScheduleService.evening.name to ScheduleService.evening.clock)
        rows.forEachIndexed { index, (name, clock) ->
            val tr = TableRow(context)
            tr.addView(context.wText(name, 12, W_TEXT), wCell(1f))
            tr.addView(context.wText(clock, 11, W_DIM), wCell(1f))
            (0 until 5).forEach { day ->
                val pid = if (index < 7) index + 1 else if (index == 7) 99 else 100
                val subject = if (pid <= 7) ScheduleService.subject(day, pid)
                else if (pid == 99) ScheduleService.practiceSubjects[day] ?: "小练" else "晚辅"
                val cell = context.wText(subject, 13, if (pid <= 7) W_OK else W_WARN).apply {
                    gravity = Gravity.CENTER
                    setBackgroundColor(if (index % 2 == 0) W_CELL else W_CELL_ALT)
                    setPadding(2, context.wdp(9), 2, context.wdp(9))
                    if (!readOnly && pid <= 7) setOnClickListener { edit(day, pid) }
                }
                tr.addView(cell, wCell(1f))
            }
            table.addView(tr)
        }
    }

    private fun List<String>.forEachWithHeader(row: TableRow) {
        forEach { row.addView(context.wText(it, 12, W_ACCENT, true).apply { gravity = Gravity.CENTER }, wCell(1f)) }
    }

    private fun wCell(weight: Float) = TableRow.LayoutParams(0, WRAP_CONTENT, weight).apply { setMargins(1, 1, 1, 1) }

    private fun edit(day: Int, pid: Int) {
        val input = context.wEdit("科目", ScheduleService.subject(day, pid))
        AlertDialog.Builder(context).setTitle("调课 · ${ScheduleService.weekdayNames[day]} 第${pid}节")
            .setView(input)
            .setPositiveButton("保存") { _, _ -> ScheduleService.setOverride(day, pid, input.text.toString().trim()); refreshGrid() }
            .setNegativeButton("取消", null).show()
    }

    private fun refreshDisabled() {
        val ranges = ScheduleService.disabledRanges()
        disabledText.text = if (ranges.isEmpty()) "暂无暂停时段" else ranges.joinToString("\n") {
            "${(it["start"] as LocalDateTime).format(MINUTE_FORMAT)} → ${(it["end"] as LocalDateTime).format(MINUTE_FORMAT)} ${it.str("note")}"
        }
    }

    private fun addDisabled() {
        val s = context.wEdit("开始 2026-11-22T14:00")
        val e = context.wEdit("结束 2026-11-22T17:00")
        val n = context.wEdit("备注")
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; addView(s); addView(e); addView(n) }
        AlertDialog.Builder(context).setTitle("添加暂停时段").setView(box)
            .setPositiveButton("保存") { _, _ ->
                val start = runCatching { LocalDateTime.parse(s.text.toString(), MINUTE_FORMAT) }.getOrNull()
                val end = runCatching { LocalDateTime.parse(e.text.toString(), MINUTE_FORMAT) }.getOrNull()
                if (start == null || end == null || !ScheduleService.addDisabled(start, end, n.text.toString().trim())) {
                    Toast.makeText(context, "时间格式不正确或结束早于开始", Toast.LENGTH_SHORT).show()
                } else refreshDisabled()
            }.setNegativeButton("取消", null).show()
    }

    private fun removeDisabled() {
        val ranges = ScheduleService.disabledRanges()
        if (ranges.isEmpty()) return
        AlertDialog.Builder(context).setTitle("删除暂停时段")
            .setItems(ranges.map { "${(it["start"] as LocalDateTime).format(MINUTE_FORMAT)} → ${(it["end"] as LocalDateTime).format(MINUTE_FORMAT)} ${it.str("note")}" }.toTypedArray()) { _, i ->
                ScheduleService.removeDisabled(i); refreshDisabled()
            }.show()
    }

    private fun reset() {
        AlertDialog.Builder(context).setTitle("恢复默认课表").setMessage("确定清除全部调课记录？")
            .setPositiveButton("确定") { _, _ -> ScheduleService.clearOverrides(); refreshGrid() }
            .setNegativeButton("取消", null).show()
    }

    override fun tick() {
        val info = ScheduleService.state()
        stateLabel.text = ScheduleService.stateLine(info)
        when (info.str("state")) {
            "in_class" -> {
                val sec = runCatching {
                    val now = LocalDateTime.now()
                    java.time.Duration.between(now, LocalDateTime.of(now.toLocalDate(), java.time.LocalTime.parse(info.str("current_end"), HH_MM))).seconds
                }.getOrDefault(0).coerceAtLeast(0)
                countLabel.text = "距下课 %02d:%02d".format(sec / 60, sec % 60)
            }
            "disabled" -> countLabel.text = "暂停提醒"
            else -> countLabel.text = "距上课 ${info.num("seconds_to_next")} 秒"
        }
        nextLabel.text = if (info.str("next_name").isNotBlank()) "下一节：${info.str("next_name")} ${info.str("next_subject")} ${info.str("next_start")}" else "今天课程已结束"
    }
}

class ParityScorePage(context: Context, private val canManage: Boolean = true, private val readOnly: Boolean = false) : ParityPage(context) {
    private var currentClass = DataStore.className()
    private val classSpinner = context.wSpinner(allClasses())
    private val scopeSpinner = context.wSpinner(listOf("按学生", "按小组"))
    private val reasonEdit = context.wEdit("原因", "积极发言")
    private val scoreEdit = context.wEdit("分值", "1", true)
    private val groupList = ListView(context)
    private val studentBox = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val recordList = ListView(context)
    private var groups = emptyList<GroupRow>()
    private var students = emptyList<StudentRow>()
    private var records = emptyList<PointRow>()
    private var refreshing = false

    init {
        if (!readOnly) {
            val top = context.wSection("记分")
            val row = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            row.addView(classSpinner, ww(1.2f)); row.addView(scopeSpinner, ww(0.8f))
            row.addView(reasonEdit, ww(1.2f)); row.addView(scoreEdit, ww(0.4f))
            row.addView(context.wButton("加分") { add(1) }, ww(0.5f))
            row.addView(context.wButton("扣分") { add(-1) }, ww(0.5f))
            top.addView(row)
            body.addView(top)
        }

        val mid = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        val left = context.wSection("小组积分榜")
        left.addView(groupList, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        val right = context.wSection(if (readOnly) "学生名单" else "学生名单（可多选）")
        val studentScroll = ScrollView(context).apply { addView(studentBox) }
        right.addView(studentScroll, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        if (!readOnly) {
            val bar = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            bar.addView(context.wButton("随机点名") { random() }, ww(1f))
            if (canManage) {
                bar.addView(context.wButton("添加学生") { addStudent() }, ww(1f))
                bar.addView(context.wButton("删除学生") { removeStudent() }, ww(1f))
                bar.addView(context.wButton("小组设置") { groupSettings() }, ww(1f))
            }
            right.addView(bar)
        }
        mid.addView(left, LinearLayout.LayoutParams(0, MATCH_PARENT, 0.4f))
        mid.addView(right, LinearLayout.LayoutParams(0, MATCH_PARENT, 0.6f))
        body.addView(mid, LinearLayout.LayoutParams(MATCH_PARENT, context.wdp(320)))

        val bottom = context.wSection(if (readOnly) "积分明细" else "积分明细（点击记录可撤销）")
        bottom.addView(recordList, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        if (!readOnly) {
            val bar = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            bar.addView(context.wButton("撤销选中记录") { revoke() }, ww(1f))
            bar.addView(context.wButton("刷新") { refresh() }, ww(1f))
            bottom.addView(bar)
        }
        body.addView(bottom, LinearLayout.LayoutParams(MATCH_PARENT, context.wdp(230)))

        groupList.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!refreshing) refreshStudents()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        classSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (refreshing) return
                currentClass = classSpinner.selectedItem?.toString() ?: currentClass
                refresh()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        recordList.setOnItemClickListener { _, _, pos, _ -> if (!readOnly) revokeAt(pos) }
        refresh()
    }

    private fun ww(weight: Float) = LinearLayout.LayoutParams(0, WRAP_CONTENT, weight).apply { setMargins(2, 4, 2, 4) }

    fun refresh() {
        refreshing = true
        try {
            val classes = allClasses()
            classSpinner.adapter = context.wSpinner(classes).adapter
            if (currentClass !in classes && classes.isNotEmpty()) currentClass = classes.first()
            classSpinner.setSelection(classes.indexOf(currentClass).coerceAtLeast(0))
            groups = ScoreService.groupRows(currentClass)
            groupList.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1,
                groups.map { "${it.name}     ${it.count}人     ${it.total}分" })
            if (groups.isNotEmpty()) groupList.setSelection(0)
            refreshStudents()
            refreshRecords()
        } finally { refreshing = false }
    }

    private fun selectedGroup(): String? = groups.getOrNull(groupList.selectedItemPosition)?.name

    private fun refreshStudents() {
        val group = selectedGroup()
        students = ScoreService.studentRows(currentClass).filter { group == null || it.group == group }
        studentBox.removeAllViews()
        students.forEach { row ->
            studentBox.addView(CheckBox(context).apply {
                text = "${row.sid}  ${row.name}  ${row.total}分${if (row.isLeader) "（组长）" else ""}"
                textSize = 14f; setTextColor(W_TEXT); tag = row.sid
            })
        }
    }

    private fun refreshRecords() {
        val group = selectedGroup()
        records = ScoreService.pointRows(currentClass).filter { group == null || it.group == group }.take(200)
        recordList.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1,
            records.map { "${it.time}  ${it.group}  ${it.name}  ${it.reason}  ${it.delta}" })
    }

    private fun selectedSids(): List<String> = (0 until studentBox.childCount).mapNotNull { i ->
        (studentBox.getChildAt(i) as? CheckBox)?.let { if (it.isChecked) it.tag?.toString() else null }
    }

    private fun add(sign: Int) {
        val delta = (scoreEdit.text.toString().toIntOrNull() ?: 1) * sign
        val reason = reasonEdit.text.toString().trim().ifBlank { "未填写原因" }
        val count = if (scopeSpinner.selectedIndex() == 0) {
            ScoreService.addPoint(currentClass, selectedSids(), reason, delta)
        } else {
            val name = selectedGroup()
            ScoreService.addGroupPoint(currentClass, if (name.isNullOrBlank()) emptyList() else listOf(name), reason, delta)
        }
        if (count == 0) Toast.makeText(context, "请先选择学生或小组", Toast.LENGTH_SHORT).show() else refresh()
    }

    private fun Spinner.selectedIndex(): Int = selectedItemPosition

    private fun revokeAt(pos: Int) {
        val row = records.getOrNull(pos) ?: return
        AlertDialog.Builder(context).setTitle("撤销记录").setMessage("${row.name}  ${row.reason}  ${row.delta}")
            .setPositiveButton("撤销") { _, _ -> ScoreService.revokeStudentRecord(currentClass, row.sid, row.recordIndex); refresh() }
            .setNegativeButton("取消", null).show()
    }

    private fun revoke() {
        val pos = recordList.selectedItemPosition
        if (pos < 0) Toast.makeText(context, "请先选中一条记录", Toast.LENGTH_SHORT).show() else revokeAt(pos)
    }

    private fun random() {
        val group = selectedGroup()
        val pool = ScoreService.studentRows(currentClass).filter { group == null || it.group == group }
        if (pool.isEmpty()) { Toast.makeText(context, "暂无学生", Toast.LENGTH_SHORT).show(); return }
        val p = pool[Random(System.currentTimeMillis()).nextInt(pool.size)]
        Toast.makeText(context, "${p.group}  ${p.name}（${p.sid}）", Toast.LENGTH_LONG).show()
    }

    private fun addStudent() {
        val sid = context.wEdit("学号"); val name = context.wEdit("姓名")
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; addView(sid); addView(name) }
        AlertDialog.Builder(context).setTitle("添加学生").setView(box)
            .setPositiveButton("保存") { _, _ ->
                ScoreService.addStudent(currentClass, sid.text.toString().trim(), name.text.toString().trim())?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() }
                refresh()
            }.setNegativeButton("取消", null).show()
    }

    private fun removeStudent() {
        val sids = selectedSids()
        if (sids.isEmpty()) { Toast.makeText(context, "请先勾选学生", Toast.LENGTH_SHORT).show(); return }
        AlertDialog.Builder(context).setTitle("删除学生").setMessage("确定删除 ${sids.size} 名学生？")
            .setPositiveButton("确定") { _, _ -> sids.forEach { ScoreService.removeStudent(currentClass, it) }; refresh() }
            .setNegativeButton("取消", null).show()
    }

    private fun groupSettings() {
        val name = selectedGroup()
        if (name == null) { Toast.makeText(context, "请先选择小组", Toast.LENGTH_SHORT).show(); return }
        val all = ScoreService.studentRows(currentClass)
        val group = ScoreService.classGroups(currentClass)[name].asMap()
        val selected = group["members"].asList().map { it?.toString() }.toSet()
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        val checks = all.map { student ->
            CheckBox(context).apply {
                text = "${student.sid}  ${student.name}  ${student.group}"
                isChecked = student.sid in selected
                setTextColor(W_TEXT)
            }
        }
        checks.forEach { box.addView(it) }
        val leaderSpinner = context.wSpinner(listOf("无") + all.map { "${it.sid} ${it.name}" })
        val leaderSid = group.str("leader")
        val idx = all.indexOfFirst { it.sid == leaderSid }
        leaderSpinner.setSelection(if (idx >= 0) idx + 1 else 0)
        box.addView(context.wText("组长"))
        box.addView(leaderSpinner)
        AlertDialog.Builder(context).setTitle("小组设置 · $name").setView(box)
            .setPositiveButton("保存") { _, _ ->
                val members = checks.filter { it.isChecked }.mapIndexed { i, _ -> all[i].sid }
                val leader = if (leaderSpinner.selectedItemPosition == 0) "" else all[leaderSpinner.selectedItemPosition - 1].sid
                ScoreService.setGroupMembers(currentClass, name, members, leader)
                refresh()
            }.setNegativeButton("取消", null).show()
    }
}

class ParityHygienePage(context: Context, private val readOnly: Boolean = false, private val operator: String = "值日生") : ParityPage(context) {
    private var currentClass = DataStore.className()
    private val classSpinner = context.wSpinner(allClasses())
    private val reasonInput = AutoCompleteTextView(context).apply {
        hint = "扣分原因"; setTextColor(W_TEXT); setHintTextColor(W_DIM); setBackgroundColor(W_CELL); threshold = 1
    }
    private val scoreEdit = context.wEdit("扣分", "1", true)
    private val noteEdit = context.wEdit("备注")
    private val byEdit = context.wEdit("操作人", operator)
    private val studentBox = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val barChart = WBarChart(context)
    private val pieChart = WPieChart(context)
    private val recordList = ListView(context)
    private var rows = emptyList<HygieneRow>()
    private var refreshing = false

    init {
        if (!readOnly) {
            val top = context.wSection("卫生扣分登记")
            val row = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            row.addView(classSpinner, ww(1f)); row.addView(reasonInput, ww(1.4f))
            row.addView(scoreEdit, ww(0.4f)); row.addView(noteEdit, ww(1f)); row.addView(byEdit, ww(0.8f))
            row.addView(context.wButton("记扣分") { addRecord() }, ww(0.6f))
            top.addView(row)
            body.addView(top)
        }

        val mid = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        val left = context.wSection(if (readOnly) "学生名单" else "选择学生（可多选）")
        left.addView(ScrollView(context).apply { addView(studentBox) }, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        val right = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        right.addView(context.wSection("小组扣分").apply { addView(barChart, LinearLayout.LayoutParams(0, MATCH_PARENT, 1f)) }, LinearLayout.LayoutParams(0, MATCH_PARENT, 0.5f))
        right.addView(context.wSection("原因分布").apply { addView(pieChart, LinearLayout.LayoutParams(0, MATCH_PARENT, 1f)) }, LinearLayout.LayoutParams(0, MATCH_PARENT, 0.5f))
        mid.addView(left, LinearLayout.LayoutParams(0, MATCH_PARENT, 0.3f))
        mid.addView(right, LinearLayout.LayoutParams(0, MATCH_PARENT, 0.7f))
        body.addView(mid, LinearLayout.LayoutParams(MATCH_PARENT, context.wdp(300)))

        val bottom = context.wSection(if (readOnly) "扣分明细" else "扣分明细（点击记录可撤销）")
        bottom.addView(recordList, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        if (!readOnly) bottom.addView(context.wButton("刷新") { refresh() })
        body.addView(bottom, LinearLayout.LayoutParams(MATCH_PARENT, context.wdp(230)))

        recordList.setOnItemClickListener { _, _, pos, _ -> if (!readOnly && pos in rows.indices) revoke(rows[pos]) }
        classSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (refreshing) return
                currentClass = classSpinner.selectedItem?.toString() ?: currentClass
                refresh()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        refresh()
    }

    private fun ww(weight: Float) = LinearLayout.LayoutParams(0, WRAP_CONTENT, weight).apply { setMargins(2, 4, 2, 4) }

    fun refresh() {
        refreshing = true
        try {
            val classes = allClasses()
            classSpinner.adapter = context.wSpinner(classes).adapter
            if (currentClass !in classes && classes.isNotEmpty()) currentClass = classes.first()
            classSpinner.setSelection(classes.indexOf(currentClass).coerceAtLeast(0))
            studentBox.removeAllViews()
            ScoreService.studentRows(currentClass).forEach { row ->
                studentBox.addView(CheckBox(context).apply {
                    text = "${row.sid}  ${row.name}  ${row.group}"; textSize = 13f; setTextColor(W_TEXT); tag = row.sid
                })
            }
            reasonInput.setAdapter(ArrayAdapter(context, android.R.layout.simple_dropdown_item_1line, HygieneService.reasons(currentClass)))
            rows = HygieneService.records(currentClass)
            recordList.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1,
                rows.map { "${it.time}  ${it.group}  ${it.name}  ${it.reason}  -${it.score}  ${it.by}" })
            barChart.data = HygieneService.groupRows(currentClass)
            pieChart.data = HygieneService.reasonRows(currentClass)
            barChart.invalidate(); pieChart.invalidate()
        } finally { refreshing = false }
    }

    private fun addRecord() {
        val sids = (0 until studentBox.childCount).mapNotNull { i ->
            (studentBox.getChildAt(i) as? CheckBox)?.let { if (it.isChecked) it.tag?.toString() else null }
        }
        if (sids.isEmpty()) { Toast.makeText(context, "请先勾选学生", Toast.LENGTH_SHORT).show(); return }
        val count = HygieneService.addRecord(currentClass, sids,
            reasonInput.text.toString().trim().ifBlank { "未填写原因" },
            scoreEdit.text.toString().toIntOrNull() ?: 1,
            noteEdit.text.toString().trim(), byEdit.text.toString().trim().ifBlank { "未记录" })
        if (count > 0) refresh()
    }

    private fun revoke(row: HygieneRow) {
        AlertDialog.Builder(context).setTitle("撤销扣分").setMessage("${row.name}  ${row.reason}  -${row.score}")
            .setPositiveButton("撤销") { _, _ -> HygieneService.revoke(currentClass, row.recordIndex); refresh() }
            .setNegativeButton("取消", null).show()
    }

    private class WBarChart(context: Context) : View(context) {
        var data: List<Pair<String, Int>> = emptyList()
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            canvas.drawColor(W_PANEL)
            if (data.isEmpty()) { paint.color = W_DIM; paint.textSize = 26f; canvas.drawText("暂无记录", 16f, 46f, paint); return }
            val max = data.maxOf { it.second }.coerceAtLeast(1)
            val step = (height - 30f) / data.size.coerceAtLeast(1)
            data.take(8).forEachIndexed { i, (name, value) ->
                val y = 16f + i * step
                paint.color = W_TEXT; paint.textSize = 20f
                canvas.drawText(name, 8f, y + step * 0.7f, paint)
                paint.color = Color.rgb(0xE0, 0x6C, 0x75)
                val left = 130f
                val width = ((width - left - 40f) * value / max).coerceAtLeast(2f)
                canvas.drawRect(left, y + 4f, left + width, y + step - 6f, paint)
                paint.color = W_WARN
                canvas.drawText(value.toString(), left + width + 6f, y + step * 0.7f, paint)
            }
        }
    }

    private class WPieChart(context: Context) : View(context) {
        var data: List<Pair<String, Int>> = emptyList()
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val colors = listOf(
            Color.rgb(0xE0, 0x6C, 0x75), Color.rgb(0xE5, 0xC0, 0x7B), Color.rgb(0x98, 0xC3, 0x79),
            Color.rgb(0x61, 0xAF, 0xEF), Color.rgb(0xC6, 0x78, 0xDD), Color.rgb(0x56, 0xB6, 0xC2),
        )
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            canvas.drawColor(W_PANEL)
            if (data.isEmpty()) { paint.color = W_DIM; paint.textSize = 26f; canvas.drawText("暂无记录", 16f, 46f, paint); return }
            val total = data.sumOf { it.second }.coerceAtLeast(1)
            val cx = width * 0.32f; val cy = height * 0.5f; val r = minOf(cx, cy) * 0.8f
            var start = 0f
            data.take(6).forEachIndexed { i, (_, value) ->
                val sweep = 360f * value / total
                paint.color = colors[i % colors.size]
                canvas.drawArc(cx - r, cy - r, cx + r, cy + r, start, sweep, true, paint)
                start += sweep
            }
            paint.color = W_PANEL; canvas.drawCircle(cx, cy, r * 0.45f, paint)
            paint.color = W_TEXT; paint.textSize = 24f
            val label = total.toString(); canvas.drawText(label, cx - paint.measureText(label) / 2, cy + 8f, paint)
            paint.textSize = 18f
            data.take(5).forEachIndexed { i, (name, value) ->
                val y = 30f + i * 30f
                paint.color = colors[i % colors.size]; canvas.drawRect(width * 0.6f, y - 12f, width * 0.6f + 14f, y + 2f, paint)
                paint.color = W_TEXT
                canvas.drawText("${name.take(6)} ($value)", width * 0.6f + 20f, y, paint)
            }
        }
    }
}

class ParitySettingsPage(context: Context, private val activity: Activity) : ParityPage(context) {
    private val portEdit = context.wEdit("端口", LanServer.configuredPort().toString(), true)
    private val lanAuto = CheckBox(context).apply { text = "启动时自动开启局域网服务"; isChecked = DataStore.settings().flag("lan_autostart"); setTextColor(W_TEXT) }
    private val statusText = context.wText("", 13, W_TEXT)
    private val cloudBox = CheckBox(context).apply { text = "启用官网云端同步"; isChecked = DataStore.settings()["cloud_api"].asMap().flag("enabled"); setTextColor(W_TEXT) }
    private val phoneField = context.wEdit("手机设备 ID")
    private val teacherPhone = context.wEdit("教师手机号", RolesService.phone())
    private val dutyText = context.wText("", 13, W_DIM)

    init {
        val lan = context.wSection("局域网服务")
        val lanRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        lanRow.addView(portEdit, LinearLayout.LayoutParams(0, WRAP_CONTENT, 0.4f))
        lanRow.addView(context.wButton("启动/停止服务") {
            if (LanServer.running) LanServer.stop() else {
                val err = LanServer.start(portEdit.text.toString().toIntOrNull() ?: LanServer.configuredPort())
                if (err != null) Toast.makeText(context, err, Toast.LENGTH_SHORT).show()
            }
            refresh()
        }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 0.6f))
        lan.addView(lanRow); lan.addView(lanAuto); body.addView(lan)

        val cloud = context.wSection("云端同步")
        cloud.addView(cloudBox); cloud.addView(phoneField)
        val cloudRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        cloudRow.addView(context.wButton("发起绑定") {
            val id = phoneField.text.toString().trim()
            if (id.isBlank()) Toast.makeText(context, "请填写手机设备 ID", Toast.LENGTH_SHORT).show()
            else Toast.makeText(context, CloudService.bindPhone(id), Toast.LENGTH_LONG).show()
        }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        cloudRow.addView(context.wButton("保存设置") { save() }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        cloud.addView(cloudRow); body.addView(cloud)

        val keys = context.wSection("密钥与身份")
        keys.addView(teacherPhone)
        val keyRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        keyRow.addView(context.wButton("保存手机号") {
            Toast.makeText(context, RolesService.setPhone(teacherPhone.text.toString()).second, Toast.LENGTH_SHORT).show()
        }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        keyRow.addView(context.wButton("修改教师密钥") { changeKey() }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        keys.addView(keyRow)
        val dutyRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        dutyRow.addView(context.wButton("任命值日生") { addDuty() }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        dutyRow.addView(context.wButton("撤销任命") { removeDuty() }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        keys.addView(dutyRow); keys.addView(dutyText); body.addView(keys)

        val files = context.wSection("文件导出")
        val fileRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        fileRow.addView(context.wButton("课程表 PNG") { AndroidExporter.schedulePng(context) }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        fileRow.addView(context.wButton("积分 CSV") { AndroidExporter.scoresCsv(context) }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        fileRow.addView(context.wButton("卫生 CSV") { AndroidExporter.hygieneCsv(context) }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        files.addView(fileRow); body.addView(files)

        val floatSec = context.wSection("悬浮球")
        val floatStatus = context.wText(
            if (SystemBall.canDraw(context)) "系统悬浮窗权限：已开启" else "系统悬浮窗权限：未开启",
            13, W_DIM,
        )
        floatSec.addView(floatStatus)
        val floatRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        floatRow.addView(context.wButton("申请悬浮窗权限") {
            SystemBall.requestPermission(activity)
            floatStatus.text = if (SystemBall.canDraw(context)) "系统悬浮窗权限：已开启" else "系统悬浮窗权限：未开启"
        }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        floatRow.addView(context.wButton("显示/隐藏悬浮球") {
            SystemBall.toggle(context)
        }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        floatSec.addView(floatRow); body.addView(floatSec)

        val status = context.wSection("运行状态")
        status.addView(statusText); body.addView(status)
        refreshDuties(); refresh()
    }

    private fun save() {
        val settings = DataStore.settings()
        settings["lan_port"] = portEdit.text.toString().toIntOrNull() ?: 8765
        settings["lan_autostart"] = lanAuto.isChecked
        val cloud = settings["cloud_api"].asMutableMap(); cloud["enabled"] = cloudBox.isChecked; settings["cloud_api"] = cloud
        DataStore.saveSettings(settings)
        Toast.makeText(context, "设置已保存", Toast.LENGTH_SHORT).show()
    }

    private fun changeKey() {
        val old = context.wEdit("原密钥").apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val new = context.wEdit("新密钥").apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val confirm = context.wEdit("确认新密钥").apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; addView(old); addView(new); addView(confirm) }
        AlertDialog.Builder(context).setTitle("修改教师密钥").setView(box)
            .setPositiveButton("保存") { _, _ ->
                if (new.text.toString() != confirm.text.toString()) Toast.makeText(context, "两次输入不一致", Toast.LENGTH_SHORT).show()
                else Toast.makeText(context, AuthService.change(old.text.toString(), new.text.toString()).second, Toast.LENGTH_SHORT).show()
            }.setNegativeButton("取消", null).show()
    }

    private fun addDuty() {
        val classes = allClasses()
        val cs = context.wSpinner(classes)
        var stus = ScoreService.studentRows(classes.firstOrNull() ?: DataStore.className())
        val ss = context.wSpinner(stus.map { "${it.sid} ${it.name}" })
        val role = context.wSpinner(listOf("值日长", "卫生长"))
        val key = context.wEdit("专用密钥（留空自动生成）")
        cs.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                stus = ScoreService.studentRows(cs.selectedItem?.toString() ?: return)
                ss.adapter = ArrayAdapter(context, android.R.layout.simple_spinner_item, stus.map { "${it.sid} ${it.name}" }).apply {
                    setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
                }
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; addView(cs); addView(ss); addView(role); addView(key) }
        AlertDialog.Builder(context).setTitle("任命值日生").setView(box)
            .setPositiveButton("任命") { _, _ ->
                val s = stus.getOrNull(ss.selectedItemPosition) ?: return@setPositiveButton
                val kind = if (role.selectedItemPosition == 1) RolesService.KIND_HYGIENE else RolesService.KIND_SCORE
                val result = RolesService.addDuty(s.sid, s.name, role.selectedItem.toString(), kind, key.text.toString())
                Toast.makeText(context, result.second, Toast.LENGTH_LONG).show(); refreshDuties()
            }.setNegativeButton("取消", null).show()
    }

    private fun removeDuty() {
        val list = RolesService.duties()
        if (list.isEmpty()) { Toast.makeText(context, "暂无任命", Toast.LENGTH_SHORT).show(); return }
        AlertDialog.Builder(context).setTitle("撤销任命")
            .setItems(list.map { "${it.str("name")} · ${it.str("role")}" }.toTypedArray()) { _, i ->
                Toast.makeText(context, RolesService.removeDuty(list[i].str("id")).second, Toast.LENGTH_SHORT).show(); refreshDuties()
            }.show()
    }

    private fun refreshDuties() {
        val list = RolesService.duties()
        dutyText.text = if (list.isEmpty()) "暂无任命" else list.joinToString("\n") { "${it.str("name")} · ${it.str("role")} · ${if (it.str("kind") == RolesService.KIND_HYGIENE) "卫生" else "积分"}" }
    }

    override fun tick() = refresh()

    private fun refresh() {
        val s = ScheduleService.state()
        statusText.text = "课节：${ScheduleService.stateLine(s)}\n局域网：${if (LanServer.running) LanServer.url() else "未启动"}\n云端：${CloudService.status}\n数据目录：${DataStore.path("settings.json").parentFile}"
    }
}

class ParityStudentPage(context: Context, private val sid: String, private val name: String, private val cls: String) : ParityPage(context) {
    private val summary = context.wText("", 18, W_ACCENT, true)
    private val table = TableLayout(context).apply { setStretchAllColumns(true) }
    private val list = ListView(context)

    init {
        val info = context.wSection("我的信息")
        info.addView(context.wText("$name（$sid）· $cls", 16, W_TEXT, true)); info.addView(summary); body.addView(info)
        val schedule = context.wSection("我的课表（只读）"); schedule.addView(table); body.addView(schedule)
        val records = context.wSection("我的积分记录"); records.addView(list); body.addView(records)
        refresh()
    }

    private fun refresh() {
        val rows = ScoreService.pointRows(cls).filter { it.sid == sid }
        summary.text = "当前积分：${rows.sumOf { it.delta }} 分 · 共 ${rows.size} 条记录"
        table.removeAllViews()
        (0 until 5).forEach { day ->
            val tr = TableRow(context)
            tr.addView(context.wText(ScheduleService.weekdayNames[day], 12, W_ACCENT), TableRow.LayoutParams(0, WRAP_CONTENT, 0.8f))
            val subjects = (1..7).map { ScheduleService.subject(day, it) }
            tr.addView(context.wText(subjects.joinToString(" / "), 12, W_TEXT), TableRow.LayoutParams(0, WRAP_CONTENT, 4f))
            table.addView(tr)
        }
        list.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1, rows.map { "${it.time}  ${it.reason}  ${it.delta}" })
    }

    override fun tick() = refresh()
}

object AndroidExporter {
    fun schedulePng(context: Context) {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
        val file = File(dir, "课程表.png")
        runCatching {
            val bitmap = android.graphics.Bitmap.createBitmap(1080, 660, android.graphics.Bitmap.Config.ARGB_8888)
            val c = android.graphics.Canvas(bitmap)
            c.drawColor(Color.rgb(0x1E, 0x1E, 0x2E))
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 26f; color = W_TEXT }
            c.drawText("${DataStore.className()} 课程表", 32f, 48f, paint)
            paint.textSize = 16f
            val heads = listOf("节次", "时间") + ScheduleService.weekdayNames
            heads.forEachIndexed { i, h ->
                paint.color = W_ACCENT
                c.drawText(h, 40f + i * 140f, 110f, paint)
            }
            val rows = ScheduleService.periods.map { it.name to it.clock } +
                listOf(ScheduleService.practice.name to ScheduleService.practice.clock, ScheduleService.evening.name to ScheduleService.evening.clock)
            rows.forEachIndexed { r, (a, b) ->
                val y = 150f + r * 52f
                val values = listOf(a, b) + (0 until 5).map { d -> if (r < 7) ScheduleService.subject(d, r + 1) else if (r == 7) ScheduleService.practiceSubjects[d] ?: "小练" else "晚辅" }
                values.forEachIndexed { i, v -> paint.color = W_TEXT; c.drawText(v, 40f + i * 140f, y, paint) }
            }
            bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, file.outputStream())
            Toast.makeText(context, "已导出：$file", Toast.LENGTH_LONG).show()
        }.onFailure { Toast.makeText(context, "导出失败：${it.message}", Toast.LENGTH_SHORT).show() }
    }

    fun scoresCsv(context: Context) {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
        val file = File(dir, "积分记录.csv")
        val lines = mutableListOf("小组,学号,姓名,时间,原因,增减")
        ScoreService.pointRows(DataStore.className()).forEach { r ->
            lines.add(listOf(r.group, r.sid, r.name, r.time, r.reason, r.delta).joinToString(",") { csv(it) })
        }
        write(context, file, lines)
    }

    fun hygieneCsv(context: Context) {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
        val file = File(dir, "卫生记录.csv")
        val lines = mutableListOf("时间,小组,姓名,原因,扣分,备注,操作人")
        HygieneService.records(DataStore.className()).forEach { r ->
            lines.add(listOf(r.time, r.group, r.name, r.reason, r.score, r.note, r.by).joinToString(",") { csv(it) })
        }
        write(context, file, lines)
    }

    private fun write(context: Context, file: File, lines: List<String>) {
        runCatching { file.writeText("\uFEFF" + lines.joinToString("\r\n"), Charsets.UTF_8) }
            .onSuccess { Toast.makeText(context, "已导出：$file", Toast.LENGTH_LONG).show() }
            .onFailure { Toast.makeText(context, "导出失败：${it.message}", Toast.LENGTH_SHORT).show() }
    }

    private fun csv(v: Any?): String {
        val s = v?.toString() ?: ""
        return if (s.any { it == ',' || it == '"' || it == '\n' }) "\"" + s.replace("\"", "\"\"") + "\"" else s
    }
}

class ReminderOverlay(private val activity: Activity) {
    private val dialog: Dialog
    private val count: TextView
    init {
        val view = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.argb(210, 10, 10, 20))
            gravity = Gravity.CENTER
        }
        val title = activity.wText("准备上课", 50, W_WARN, true).apply { gravity = Gravity.CENTER }
        count = activity.wText("", 90, W_ACCENT, true).apply { gravity = Gravity.CENTER }
        val detail = activity.wText("", 24, W_TEXT).apply { gravity = Gravity.CENTER }
        view.addView(title, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT, 1f))
        view.addView(count, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT, 2f))
        view.addView(detail, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT, 1f))
        dialog = Dialog(activity, android.R.style.Theme_Translucent_NoTitleBar).apply {
            setContentView(view)
            setCancelable(false)
            window?.setLayout(MATCH_PARENT, MATCH_PARENT)
            window?.setFlags(
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            )
        }
    }

    fun update(info: Map<*, *>) {
        val active = info.flag("is_counting") || info.flag("is_prebell")
        if (active) {
            val sec = info.num("seconds_to_prebell").coerceAtLeast(0)
            count.text = "%02d:%02d".format(sec / 60, sec % 60)
            if (!dialog.isShowing) dialog.show()
        } else if (dialog.isShowing) dialog.dismiss()
    }

    fun dismiss() { if (dialog.isShowing) dialog.dismiss() }
}

class InAppBall(context: Context, private val container: FrameLayout, private val onClick: () -> Unit) : TextView(context) {
    private var dx = 0f; private var dy = 0f
    init {
        text = "710"
        setTextColor(Color.WHITE); textSize = 20f; gravity = Gravity.CENTER
        val drawable = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.rgb(0x3F, 0xA6, 0x6B))
            setStroke(2, Color.argb(90, 255, 255, 255))
        }
        background = drawable
        layoutParams = FrameLayout.LayoutParams(context.wdp(70), context.wdp(70)).apply {
            leftMargin = context.wdp(10); topMargin = context.wdp(10)
        }
        alpha = 0.9f
    }

    fun update(info: Map<*, *>) {
        val text = when (info.str("state")) {
            "in_class" -> "课"; "disabled" -> "停"; "weekend" -> "休"; else -> "710"
        }
        if (this.text.toString() != text) this.text = text
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> { dx = event.x; dy = event.y; return true }
            MotionEvent.ACTION_MOVE -> {
                val lp = layoutParams as FrameLayout.LayoutParams
                lp.leftMargin = (lp.leftMargin + event.x - dx).toInt().coerceAtLeast(0)
                lp.topMargin = (lp.topMargin + event.y - dy).toInt().coerceAtLeast(0)
                layoutParams = lp
            }
            MotionEvent.ACTION_UP -> {
                if (event.eventTime - event.downTime < 250) onClick()
            }
        }
        return true
    }
}
