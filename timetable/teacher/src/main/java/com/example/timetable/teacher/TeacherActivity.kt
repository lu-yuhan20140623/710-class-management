package com.example.timetable.teacher

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TableLayout
import android.widget.TableRow
import android.widget.TextView
import android.widget.Toast
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Timer
import kotlin.concurrent.timerTask
import kotlin.random.Random

private val BG_MAIN = Color.rgb(0x1E, 0x1E, 0x2E)
private val BG_PANEL = Color.rgb(0x2A, 0x2A, 0x3A)
private val BG_CELL = Color.rgb(0x3A, 0x3A, 0x4A)
private val FG_TEXT = Color.rgb(0xE8, 0xE8, 0xF0)
private val FG_DIM = Color.rgb(0x90, 0x90, 0xA0)
private val FG_ACCENT = Color.rgb(0x7A, 0xB8, 0xFF)
private val FG_WARN = Color.rgb(0xFF, 0xCC, 0x66)
private val FG_OK = Color.rgb(0x66, 0xCC, 0x88)
private val FG_DANGER = Color.rgb(0xFF, 0x6B, 0x6B)

private fun Context.dp(value: Int) = (value * resources.displayMetrics.density).toInt()

private fun Context.uiText(text: String, size: Int = 16, color: Int = FG_TEXT, bold: Boolean = false) =
    TextView(this).apply {
        this.text = text
        textSize = size.toFloat()
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

private fun Context.uiButton(label: String, onClick: () -> Unit) = Button(this).apply {
    text = label
    textSize = 14f
    setBackgroundColor(BG_CELL)
    setTextColor(FG_TEXT)
    setOnClickListener { onClick() }
}

private fun Context.uiEdit(hint: String, value: String = "", number: Boolean = false) =
    EditText(this).apply {
        this.hint = hint
        setText(value)
        setTextColor(FG_TEXT)
        setHintTextColor(FG_DIM)
        setBackgroundColor(BG_CELL)
        if (number) inputType = InputType.TYPE_CLASS_NUMBER
    }

private fun Context.uiSpinner(items: List<String>) = Spinner(this).apply {
    adapter = ArrayAdapter(this@uiSpinner, android.R.layout.simple_spinner_item, items).apply {
        setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
    }
}

private fun LinearLayout.margins(left: Int = 4, top: Int = 4, right: Int = 4, bottom: Int = 4) {
    (layoutParams as? ViewGroup.MarginLayoutParams)?.setMargins(left, top, right, bottom)
}

fun allClasses(): List<String> {
    val names = linkedSetOf<String>()
    listOf("student_data.txt", "group_data.txt", "hygiene_data.txt").forEach { file ->
        DataStore.loadMap(file).keys.forEach { names.add(it) }
    }
    if (names.isEmpty()) names.add(DataStore.className())
    return names.toList()
}

class TeacherActivity : Activity() {
    companion object {
        const val EXTRA_MODE = "mode"
        const val EXTRA_SID = "sid"
        const val EXTRA_NAME = "name"
        const val EXTRA_CLASS = "cls"
        const val EXTRA_ROLE = "role"
        const val EXTRA_DUTY_ID = "duty_id"

        const val MODE_TEACHER = "teacher"
        const val MODE_STUDENT = "student"
        const val MODE_DUTY_SCORE = "duty_score"
        const val MODE_DUTY_HYGIENE = "duty_hygiene"
        const val MODE_VIEW = "view"
    }

    private val pages = mutableListOf<Page>()
    private lateinit var tabGroup: RadioGroup
    private lateinit var content: FrameLayout
    private lateinit var reminder: ReminderOverlay
    private lateinit var ball: InAppBall
    private val mode: String by lazy { intent.getStringExtra(EXTRA_MODE) ?: MODE_TEACHER }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tabGroup = RadioGroup(this)
        content = FrameLayout(this)
        DataStore.context = applicationContext
        AssetsInitializer.copyIfNeeded(applicationContext)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG_MAIN)
        }
        val header = when (mode) {
            MODE_STUDENT -> "学生端 · ${intent.getStringExtra(EXTRA_NAME).orEmpty()}"
            MODE_DUTY_SCORE, MODE_DUTY_HYGIENE -> "值日生端 · ${intent.getStringExtra(EXTRA_ROLE).orEmpty()}"
            MODE_VIEW -> "查看信息（只读）"
            else -> "课程表教师端 · 安卓一体机"
        }
        root.addView(uiText(header, 20, FG_ACCENT, true).apply {
            gravity = Gravity.CENTER
            setPadding(0, dp(10), 0, dp(6))
        }, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))

        val (tabNames, builtPages) = when (mode) {
            MODE_STUDENT -> listOf("我的信息") to listOf(
                ParityStudentPage(this,
                    intent.getStringExtra(EXTRA_SID).orEmpty(),
                    intent.getStringExtra(EXTRA_NAME).orEmpty(),
                    intent.getStringExtra(EXTRA_CLASS).orEmpty())
            )
            MODE_DUTY_SCORE -> listOf("积分管理") to listOf(ParityScorePage(this, canManage = false))
            MODE_DUTY_HYGIENE -> listOf("卫生管理") to listOf(
                ParityHygienePage(this, operator = "${intent.getStringExtra(EXTRA_ROLE).orEmpty()} ${intent.getStringExtra(EXTRA_NAME).orEmpty()}".trim())
            )
            MODE_VIEW -> listOf("课程表", "积分", "卫生") to listOf(
                ParitySchedulePage(this, readOnly = true),
                ParityScorePage(this, canManage = false, readOnly = true),
                ParityHygienePage(this, readOnly = true),
            )
            else -> listOf("课程表", "积分管理", "卫生管理", "设置") to listOf(
                ParitySchedulePage(this), ParityScorePage(this), ParityHygienePage(this), ParitySettingsPage(this, this)
            )
        }

        tabGroup.orientation = RadioGroup.HORIZONTAL
        tabGroup.setBackgroundColor(BG_PANEL)
        tabNames.forEachIndexed { index, name ->
            val button = android.widget.RadioButton(this).apply {
                id = 100 + index
                text = name
                textSize = 15f
                setTextColor(FG_TEXT)
                buttonTintList = android.content.res.ColorStateList.valueOf(FG_ACCENT)
            }
            tabGroup.addView(button, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply {
                setMargins(dp(4), dp(6), dp(4), dp(6))
            })
        }
        root.addView(tabGroup, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))

        pages.addAll(builtPages)
        pages.forEach { content.addView(it, MATCH_PARENT, MATCH_PARENT) }
        root.addView(content, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        setContentView(root)

        if (mode == MODE_TEACHER) {
            reminder = ReminderOverlay(this)
            if (SystemBall.canDraw(this)) {
                SystemBall.show(applicationContext)
            } else {
                ball = InAppBall(this, content) { showPage(3) }
                content.addView(ball)
            }
        }

        tabGroup.setOnCheckedChangeListener { _, checkedId ->
            val index = checkedId - 100
            if (index in pages.indices) showPage(index)
        }
        tabGroup.check(100)
        showPage(0)

        if (DataStore.settings().flag("lan_autostart")) {
            LanServer.start(LanServer.configuredPort())
        }
        Thread({
            while (true) {
                runCatching { CloudService.tick() }
                Thread.sleep(2000)
            }
        }, "cloud-teacher").apply { isDaemon = true }.start()

        Timer(true).scheduleAtFixedRate(timerTask {
            LanServer.checkAndPublish()
            runOnUiThread {
                pages.forEach { it.tick() }
                if (mode == MODE_TEACHER) {
                    val info = ScheduleService.state()
                    reminder.update(info)
                    SystemBall.update(info)
                    if (::ball.isInitialized) ball.update(info)
                }
            }
        }, 1000, 1000)
    }

    private fun showPage(index: Int) {
        pages.forEachIndexed { i, page -> page.visibility = if (i == index) View.VISIBLE else View.GONE }
    }

    override fun onResume() {
        super.onResume()
        if (mode == MODE_TEACHER && SystemBall.canDraw(this)) {
            SystemBall.show(applicationContext)
            if (::ball.isInitialized) ball.visibility = View.GONE
        }
    }

    override fun onDestroy() {
        if (mode == MODE_TEACHER && ::reminder.isInitialized) reminder.dismiss()
        LanServer.stop()
        super.onDestroy()
    }
}

abstract class Page(context: Context) : ScrollView(context) {
    protected val body = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        setBackgroundColor(BG_MAIN)
        setPadding(context.dp(12), context.dp(12), context.dp(12), context.dp(24))
    }

    init {
        addView(body, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
    }

    protected fun section(title: String): LinearLayout {
        val layout = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG_PANEL)
            setPadding(context.dp(10), context.dp(8), context.dp(10), context.dp(10))
        }
        val label = context.uiText(title, 17, FG_ACCENT, true)
        layout.addView(label)
        (layout.layoutParams as? LinearLayout.LayoutParams)?.setMargins(0, context.dp(8), 0, context.dp(8))
        body.addView(layout)
        return layout
    }

    open fun tick() {}
}

class SchedulePage(context: Context, private val readOnly: Boolean = false) : Page(context) {
    private val statusText = context.uiText("正在读取状态…", 18, FG_ACCENT, true)
    private val table = TableLayout(context).apply { setStretchAllColumns(true) }
    private val disabledText = context.uiText("", 14, FG_DIM)

    init {
        val statusBox = section("当前状态")
        statusText.setPadding(0, context.dp(8), 0, context.dp(4))
        statusBox.addView(statusText)
        refreshGrid()

        val gridBox = section(if (readOnly) "课程表（只读）" else "课程表（点击单元格调课）")
        gridBox.addView(table, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))

        if (!readOnly) {
            val tools = section("工具")
            val row = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            row.addView(context.uiButton("恢复默认") {
                AlertDialog.Builder(context).setTitle("恢复默认课表")
                    .setMessage("确定清除全部调课记录？")
                    .setPositiveButton("确定") { _, _ -> ScheduleService.clearOverrides(); refreshGrid() }
                    .setNegativeButton("取消", null).show()
            }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            row.addView(context.uiButton("添加暂停时段") { addDisabled() }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            row.addView(context.uiButton("删除暂停时段") { removeDisabled() }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            tools.addView(row)
            tools.addView(disabledText)
        }
        refreshDisabled()
    }

    private fun refreshGrid() {
        table.removeAllViews()
        val header = TableRow(context).apply {
            addView(context.uiText("节次", 14, FG_ACCENT, true), cellParams(1f))
            addView(context.uiText("时间", 14, FG_ACCENT, true), cellParams(1f))
            ScheduleService.weekdayNames.forEach {
                addView(context.uiText(it, 14, FG_ACCENT, true), cellParams(1f))
            }
        }
        table.addView(header, MATCH_PARENT, WRAP_CONTENT)

        val rows = ScheduleService.periods.map { it.name to it.clock }.toMutableList()
        rows.add(ScheduleService.practice.name to ScheduleService.practice.clock)
        rows.add(ScheduleService.evening.name to ScheduleService.evening.clock)

        rows.forEachIndexed { rowIndex, (name, clock) ->
            val tr = TableRow(context)
            tr.addView(context.uiText(name, 13, FG_TEXT), cellParams(1f))
            tr.addView(context.uiText(clock, 12, FG_DIM), cellParams(1f))
            (0 until 5).forEach { day ->
                val pid = if (rowIndex < ScheduleService.periods.size) rowIndex + 1 else if (rowIndex == 7) 99 else 100
                val subject = if (pid <= 7) ScheduleService.subject(day, pid)
                else if (pid == 99) ScheduleService.practiceSubjects[day] ?: "小练" else "晚辅"
                val cell = context.uiText(subject, 14, if (pid <= 7) FG_OK else FG_WARN).apply {
                    gravity = Gravity.CENTER
                    setBackgroundColor(if (rowIndex % 2 == 0) BG_CELL else BG_PANEL)
                    tag = day * 100 + pid
                    setPadding(2, context.dp(8), 2, context.dp(8))
                    if (!readOnly) setOnClickListener { editSubject(day, pid) }
                }
                tr.addView(cell, cellParams(1f))
            }
            table.addView(tr, MATCH_PARENT, WRAP_CONTENT)
        }
    }

    private fun cellParams(weight: Float) = TableRow.LayoutParams(0, WRAP_CONTENT, weight).apply {
        setMargins(1, 1, 1, 1)
    }

    private fun editSubject(day: Int, period: Int) {
        if (period > 7) {
            Toast.makeText(context, "午间小练和晚辅为固定安排", Toast.LENGTH_SHORT).show()
            return
        }
        val input = context.uiEdit("科目", ScheduleService.subject(day, period))
        AlertDialog.Builder(context)
            .setTitle("调课 · ${ScheduleService.weekdayNames[day]} 第${period}节")
            .setView(input)
            .setPositiveButton("保存") { _, _ ->
                ScheduleService.setOverride(day, period, input.text.toString().trim())
                refreshGrid()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun addDisabled() {
        val start = context.uiEdit("开始 2026-11-22T14:00")
        val end = context.uiEdit("结束 2026-11-22T17:00")
        val note = context.uiEdit("备注")
        val box = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            addView(start); addView(end); addView(note)
        }
        AlertDialog.Builder(context).setTitle("添加暂停提醒时段").setView(box)
            .setPositiveButton("保存") { _, _ ->
                val s = runCatching { LocalDateTime.parse(start.text.toString(), MINUTE_FORMAT) }.getOrNull()
                val e = runCatching { LocalDateTime.parse(end.text.toString(), MINUTE_FORMAT) }.getOrNull()
                if (s == null || e == null) {
                    Toast.makeText(context, "时间格式不正确", Toast.LENGTH_SHORT).show()
                } else if (!ScheduleService.addDisabled(s, e, note.text.toString().trim())) {
                    Toast.makeText(context, "结束时间必须晚于开始时间", Toast.LENGTH_SHORT).show()
                } else refreshDisabled()
            }
            .setNegativeButton("取消", null).show()
    }

    private fun removeDisabled() {
        val ranges = ScheduleService.disabledRanges()
        if (ranges.isEmpty()) {
            Toast.makeText(context, "暂无暂停时段", Toast.LENGTH_SHORT).show()
            return
        }
        val labels = ranges.map {
            "${(it["start"] as LocalDateTime).format(MINUTE_FORMAT)} → ${(it["end"] as LocalDateTime).format(MINUTE_FORMAT)} ${it.str("note")}"
        }.toTypedArray()
        AlertDialog.Builder(context).setTitle("删除暂停时段").setItems(labels) { _, which ->
            ScheduleService.removeDisabled(which)
            refreshDisabled()
        }.show()
    }

    private fun refreshDisabled() {
        val ranges = ScheduleService.disabledRanges()
        disabledText.text = if (ranges.isEmpty()) "暂无暂停时段" else ranges.joinToString("\n") {
            "${(it["start"] as LocalDateTime).format(MINUTE_FORMAT)} → ${(it["end"] as LocalDateTime).format(MINUTE_FORMAT)}  ${it.str("note")}"
        }
    }

    override fun tick() {
        val info = ScheduleService.state()
        val extra = when (info.str("state")) {
            "in_class" -> {
                val end = info.str("current_end")
                val seconds = runCatching {
                    val now = LocalDateTime.now()
                    java.time.Duration.between(now, LocalDateTime.of(now.toLocalDate(), java.time.LocalTime.parse(end, HH_MM))).seconds
                }.getOrDefault(0).coerceAtLeast(0)
                "距下课 %02d:%02d".format(seconds / 60, seconds % 60)
            }
            "disabled" -> "暂停提醒"
            else -> "距上课 ${info.num("seconds_to_next")} 秒"
        }
        statusText.text = "${ScheduleService.stateLine(info)}\n$extra"
        statusText.setTextColor(if (info.str("state") == "disabled") FG_DANGER else FG_ACCENT)
    }
}

class ScorePage(context: Context, private val canManage: Boolean = true, private val readOnly: Boolean = false) : Page(context) {
    private var currentClass = DataStore.className()
    private val classSpinner = context.uiSpinner(allClasses())
    private val groupSpinner = context.uiSpinner(emptyList())
    private val studentBox = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val reasonEdit = context.uiEdit("原因", "积极发言")
    private val scoreEdit = context.uiEdit("分值", "1", true)
    private val recordsView = ListView(context)
    private var groupRows: List<GroupRow> = emptyList()
    private var pointRows: List<PointRow> = emptyList()
    private var refreshing = false

    init {
        val top = section(if (readOnly) "积分（只读）" else "记分")
        top.addView(classSpinner)
        top.addView(groupSpinner)
        if (!readOnly) {
            top.addView(reasonEdit)
            top.addView(scoreEdit)
            val actions = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            actions.addView(context.uiButton("加分") { addPoints(1) }, btnParams())
            actions.addView(context.uiButton("扣分") { addPoints(-1) }, btnParams())
            actions.addView(context.uiButton("随机点名") { randomStudent() }, btnParams())
            top.addView(actions)
        }

        val students = section(if (readOnly) "学生名单" else "学生（勾选后记分）")
        students.addView(studentBox)

        if (canManage && !readOnly) {
            val manage = section("管理")
            val manageRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            manageRow.addView(context.uiButton("添加学生") { addStudent() }, btnParams())
            manageRow.addView(context.uiButton("删除学生") { removeStudent() }, btnParams())
            manageRow.addView(context.uiButton("添加小组") { addGroup() }, btnParams())
            manageRow.addView(context.uiButton("删除小组") { deleteGroup() }, btnParams())
            manage.addView(manageRow)
        }

        val records = section(if (readOnly) "积分明细" else "积分明细（点击记录后撤销）")
        records.addView(recordsView)
        if (!readOnly) {
            recordsView.setOnItemClickListener { _, _, position, _ ->
                val row = pointRows.getOrNull(position) ?: return@setOnItemClickListener
                AlertDialog.Builder(context).setTitle("撤销记录")
                    .setMessage("${row.name}  ${row.reason}  ${row.delta}")
                    .setPositiveButton("撤销") { _, _ ->
                        ScoreService.revokeStudentRecord(currentClass, row.sid, row.recordIndex)
                        refresh()
                    }
                    .setNegativeButton("取消", null).show()
            }
        }

        classSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (refreshing) return
                currentClass = classSpinner.selectedItem?.toString() ?: currentClass
                refresh()
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        groupSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (refreshing) return
                refreshStudents()
                refreshRecords()
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        refresh()
    }

    private fun btnParams() = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply { setMargins(2, 4, 2, 4) }

    fun refresh() {
        refreshing = true
        try {
            val classes = allClasses()
            classSpinner.adapter = context.uiSpinner(classes).adapter
            if (currentClass !in classes && classes.isNotEmpty()) currentClass = classes.first()
            classSpinner.setSelection(classes.indexOf(currentClass).coerceAtLeast(0))
            groupRows = ScoreService.groupRows(currentClass)
            groupSpinner.adapter = context.uiSpinner(groupRows.map { "${it.name} (${it.total})" }).adapter
            refreshStudents()
            refreshRecords()
        } finally {
            refreshing = false
        }
    }

    private fun selectedGroup(): String? = groupRows.getOrNull(groupSpinner.selectedItemPosition)?.name

    private fun refreshStudents() {
        studentBox.removeAllViews()
        val group = selectedGroup()
        ScoreService.studentRows(currentClass).filter { group == null || it.group == group }.forEach { row ->
            val check = CheckBox(context).apply {
                text = "${row.sid}  ${row.name}  ${row.total}分${if (row.isLeader) "（组长）" else ""}"
                textSize = 15f
                setTextColor(FG_TEXT)
                tag = row.sid
            }
            studentBox.addView(check)
        }
    }

    private fun refreshRecords() {
        val group = selectedGroup()
        pointRows = ScoreService.pointRows(currentClass).filter { group == null || it.group == group }.take(200)
        recordsView.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1,
            pointRows.map { "${it.time}  ${it.group}  ${it.name}  ${it.reason}  ${it.delta}" })
    }

    private fun selectedSids(): List<String> = (0 until studentBox.childCount).mapNotNull { i ->
        val check = studentBox.getChildAt(i) as? CheckBox
        if (check?.isChecked == true) check.tag?.toString() else null
    }

    private fun addPoints(sign: Int) {
        val sids = selectedSids()
        val delta = (scoreEdit.text.toString().toIntOrNull() ?: 1) * sign
        val reason = reasonEdit.text.toString().trim().ifBlank { "未填写原因" }
        val count = ScoreService.addPoint(currentClass, sids, reason, delta)
        if (count == 0) Toast.makeText(context, "请先勾选学生", Toast.LENGTH_SHORT).show() else refresh()
    }

    private fun randomStudent() {
        val group = selectedGroup()
        val pool = ScoreService.studentRows(currentClass).filter { group == null || it.group == group }
        if (pool.isEmpty()) {
            Toast.makeText(context, "暂无学生", Toast.LENGTH_SHORT).show()
            return
        }
        val picked = pool[Random(System.currentTimeMillis()).nextInt(pool.size)]
        Toast.makeText(context, "${picked.group} ${picked.name}（${picked.sid}）", Toast.LENGTH_LONG).show()
    }

    private fun addStudent() {
        val sid = context.uiEdit("学号")
        val name = context.uiEdit("姓名")
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; addView(sid); addView(name) }
        AlertDialog.Builder(context).setTitle("添加学生").setView(box)
            .setPositiveButton("保存") { _, _ ->
                ScoreService.addStudent(currentClass, sid.text.toString().trim(), name.text.toString().trim())?.let {
                    Toast.makeText(context, it, Toast.LENGTH_SHORT).show()
                }
                refresh()
            }.setNegativeButton("取消", null).show()
    }

    private fun removeStudent() {
        val sids = selectedSids()
        if (sids.isEmpty()) {
            Toast.makeText(context, "请先勾选学生", Toast.LENGTH_SHORT).show()
            return
        }
        AlertDialog.Builder(context).setTitle("删除学生").setMessage("确定删除 ${sids.size} 名学生？")
            .setPositiveButton("确定") { _, _ -> sids.forEach { ScoreService.removeStudent(currentClass, it) }; refresh() }
            .setNegativeButton("取消", null).show()
    }

    private fun addGroup() {
        val name = context.uiEdit("小组名称")
        AlertDialog.Builder(context).setTitle("添加小组").setView(name)
            .setPositiveButton("保存") { _, _ ->
                ScoreService.addGroup(currentClass, name.text.toString().trim())?.let {
                    Toast.makeText(context, it, Toast.LENGTH_SHORT).show()
                }
                refresh()
            }.setNegativeButton("取消", null).show()
    }

    private fun deleteGroup() {
        val group = selectedGroup()
        if (group == null) {
            Toast.makeText(context, "请先选择小组", Toast.LENGTH_SHORT).show()
            return
        }
        AlertDialog.Builder(context).setTitle("删除小组").setMessage("确定删除「$group」？")
            .setPositiveButton("确定") { _, _ -> ScoreService.deleteGroup(currentClass, group); refresh() }
            .setNegativeButton("取消", null).show()
    }
}

class HygienePage(context: Context, private val readOnly: Boolean = false, private val operator: String = "值日生") : Page(context) {
    private var currentClass = DataStore.className()
    private val classSpinner = context.uiSpinner(allClasses())
    private val studentBox = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val reasonInput = AutoCompleteTextView(context).apply {
        hint = "扣分原因"
        setTextColor(FG_TEXT)
        setHintTextColor(FG_DIM)
        setBackgroundColor(BG_CELL)
        threshold = 1
    }
    private val scoreEdit = context.uiEdit("扣分", "1", true)
    private val noteEdit = context.uiEdit("备注")
    private val byEdit = context.uiEdit("操作人", "值日生")
    private val recordsView = ListView(context)
    private val summary = context.uiText("", 15, FG_WARN)
    private val barChart = BarView(context)
    private var rows: List<HygieneRow> = emptyList()
    private var refreshing = false

    init {
        val top = section(if (readOnly) "卫生扣分（只读）" else "卫生扣分登记")
        top.addView(classSpinner)
        if (!readOnly) {
            top.addView(reasonInput)
            top.addView(scoreEdit)
            top.addView(noteEdit)
            if (operator != "值日生") byEdit.setText(operator)
            top.addView(byEdit)
            top.addView(context.uiButton("记扣分") { addRecord() })
        }

        val students = section(if (readOnly) "学生名单" else "选择学生（可多选）")
        students.addView(studentBox)

        val stats = section("统计")
        stats.addView(summary)
        stats.addView(barChart, LinearLayout.LayoutParams(MATCH_PARENT, context.dp(150)))

        val records = section(if (readOnly) "扣分明细" else "扣分明细（点击撤销）")
        records.addView(recordsView)
        if (!readOnly) {
            recordsView.setOnItemClickListener { _, _, position, _ ->
                val row = rows.getOrNull(position) ?: return@setOnItemClickListener
                AlertDialog.Builder(context).setTitle("撤销扣分")
                    .setMessage("${row.name}  ${row.reason}  -${row.score}")
                    .setPositiveButton("撤销") { _, _ -> HygieneService.revoke(currentClass, row.recordIndex); refresh() }
                    .setNegativeButton("取消", null).show()
            }
        }

        classSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (refreshing) return
                currentClass = classSpinner.selectedItem?.toString() ?: currentClass
                refresh()
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        refresh()
    }

    fun refresh() {
        refreshing = true
        try {
            val classes = allClasses()
            classSpinner.adapter = context.uiSpinner(classes).adapter
            if (currentClass !in classes && classes.isNotEmpty()) currentClass = classes.first()
            classSpinner.setSelection(classes.indexOf(currentClass).coerceAtLeast(0))

            studentBox.removeAllViews()
            ScoreService.studentRows(currentClass).forEach { row ->
                studentBox.addView(CheckBox(context).apply {
                    text = "${row.sid}  ${row.name}  ${row.group}"
                    textSize = 14f
                    setTextColor(FG_TEXT)
                    tag = row.sid
                })
            }
            reasonInput.setAdapter(ArrayAdapter(context, android.R.layout.simple_dropdown_item_1line,
                HygieneService.reasons(currentClass)))
            rows = HygieneService.records(currentClass)
            recordsView.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1,
                rows.map { "${it.time}  ${it.group}  ${it.name}  ${it.reason}  -${it.score}  ${it.by}" })
            val totals = HygieneService.groupRows(currentClass)
            summary.text = "共 ${rows.size} 条 · 扣分 ${rows.sumOf { it.score }}"
            barChart.data = totals
            barChart.invalidate()
        } finally {
            refreshing = false
        }
    }

    private fun addRecord() {
        val sids = (0 until studentBox.childCount).mapNotNull { i ->
            val check = studentBox.getChildAt(i) as? CheckBox
            if (check?.isChecked == true) check.tag?.toString() else null
        }
        if (sids.isEmpty()) {
            Toast.makeText(context, "请先勾选学生", Toast.LENGTH_SHORT).show()
            return
        }
        val reason = reasonInput.text.toString().trim().ifBlank { "未填写原因" }
        val score = scoreEdit.text.toString().toIntOrNull() ?: 1
        val count = HygieneService.addRecord(currentClass, sids, reason, score,
            noteEdit.text.toString().trim(), byEdit.text.toString().trim().ifBlank { "未记录" })
        if (count > 0) refresh()
    }

    private class BarView(context: Context) : View(context) {
        var data: List<Pair<String, Int>> = emptyList()
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            canvas.drawColor(BG_PANEL)
            if (data.isEmpty()) {
                paint.color = FG_DIM
                paint.textSize = 28f
                canvas.drawText("暂无扣分记录", 20f, 50f, paint)
                return
            }
            val max = data.maxOf { it.second }.coerceAtLeast(1)
            val top = 20f
            val rowHeight = (height - 30f) / data.size.coerceAtLeast(1)
            data.take(8).forEachIndexed { index, (name, value) ->
                val y = top + index * rowHeight
                paint.color = FG_TEXT
                paint.textSize = 24f
                canvas.drawText(name, 10f, y + rowHeight * 0.7f, paint)
                paint.color = Color.rgb(0xE0, 0x6C, 0x75)
                val left = 180f
                val width = ((measuredWidth - left - 60f) * value / max).coerceAtLeast(2f)
                canvas.drawRect(left, y + 6f, left + width, y + rowHeight - 8f, paint)
                paint.color = FG_WARN
                canvas.drawText(value.toString(), left + width + 8f, y + rowHeight * 0.7f, paint)
            }
        }
    }
}

class StudentPage(context: Context, private val sid: String, private val name: String, private val cls: String) : Page(context) {
    private val summary = context.uiText("", 18, FG_ACCENT, true)
    private val scheduleText = context.uiText("", 15, FG_TEXT)
    private val recordsView = ListView(context)

    init {
        val info = section("我的信息")
        info.addView(context.uiText("$name（$sid）· $cls", 16, FG_TEXT, true))
        info.addView(summary)

        val schedule = section("我的课表（只读）")
        schedule.addView(scheduleText)

        val records = section("我的积分记录")
        records.addView(recordsView)
        refresh()
    }

    private fun refresh() {
        val rows = ScoreService.pointRows(cls).filter { it.sid == sid }
        summary.text = "当前积分：${rows.sumOf { it.delta }} 分 · 共 ${rows.size} 条记录"
        scheduleText.text = (0 until 5).joinToString("\n") { day ->
            val subjects = (1..7).map { ScheduleService.subject(day, it) }
            "${ScheduleService.weekdayNames[day]}：" + subjects.joinToString(" / ")
        }
        recordsView.adapter = ArrayAdapter(context, android.R.layout.simple_list_item_1,
            rows.map { "${it.time}  ${it.reason}  ${it.delta}" })
    }

    override fun tick() = refresh()
}

class SettingsPage(context: Context) : Page(context) {
    private val portEdit = context.uiEdit("端口", LanServer.configuredPort().toString(), true)
    private val statusText = context.uiText("", 14, FG_TEXT)
    private val cloudBox = CheckBox(context).apply {
        text = "启用官网云端同步"
        isChecked = DataStore.settings()["cloud_api"].asMap().flag("enabled")
        setTextColor(FG_TEXT)
    }
    private val phoneEdit = context.uiEdit("手机设备 ID")
    private val teacherPhoneEdit = context.uiEdit("教师手机号", RolesService.phone())
    private val dutyText = context.uiText("", 14, FG_DIM)

    init {
        val lan = section("局域网服务")
        lan.addView(portEdit)
        lan.addView(context.uiButton("启动/停止服务") {
            if (LanServer.running) LanServer.stop() else {
                val error = LanServer.start(portEdit.text.toString().toIntOrNull() ?: LanServer.configuredPort())
                if (error != null) Toast.makeText(context, error, Toast.LENGTH_SHORT).show()
            }
            refreshStatus()
        })
        lan.addView(statusText)

        val cloud = section("云端同步")
        cloud.addView(cloudBox)
        cloud.addView(phoneEdit)
        cloud.addView(context.uiButton("发起绑定") {
            val id = phoneEdit.text.toString().trim()
            if (id.isBlank()) Toast.makeText(context, "请填写手机设备 ID", Toast.LENGTH_SHORT).show()
            else Toast.makeText(context, CloudService.bindPhone(id), Toast.LENGTH_LONG).show()
        })
        cloud.addView(context.uiButton("保存设置") {
            val settings = DataStore.settings()
            settings["lan_port"] = portEdit.text.toString().toIntOrNull() ?: 8765
            val cloudSettings = settings["cloud_api"].asMutableMap()
            cloudSettings["enabled"] = cloudBox.isChecked
            settings["cloud_api"] = cloudSettings
            DataStore.saveSettings(settings)
            Toast.makeText(context, "已保存", Toast.LENGTH_SHORT).show()
        })

        val keys = section("密钥管理")
        keys.addView(context.uiText("教师手机号：${RolesService.phone().ifBlank { "未绑定" }}", 13, FG_DIM))
        keys.addView(teacherPhoneEdit)
        keys.addView(context.uiButton("保存手机号") {
            val result = RolesService.setPhone(teacherPhoneEdit.text.toString())
            Toast.makeText(context, result.second, Toast.LENGTH_SHORT).show()
            refreshStatus()
        })
        keys.addView(context.uiButton("修改教师密钥") { changeTeacherKey() })

        val duties = section("值日生任命")
        duties.addView(dutyText)
        duties.addView(context.uiButton("任命值日生") { addDutyDialog() })
        duties.addView(context.uiButton("撤销任命") { removeDutyDialog() })
        refreshDuties()
        refreshStatus()
    }

    private fun refreshDuties() {
        val list = RolesService.duties()
        dutyText.text = if (list.isEmpty()) "暂无任命" else list.joinToString("\n") {
            "${it.str("name")} · ${it.str("role")} · ${if (it.str("kind") == RolesService.KIND_HYGIENE) "卫生管理" else "积分管理"}"
        }
    }

    private fun changeTeacherKey() {
        val old = context.uiEdit("原密钥").apply { inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val new = context.uiEdit("新密钥").apply { inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val confirm = context.uiEdit("确认新密钥").apply { inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val box = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; addView(old); addView(new); addView(confirm) }
        AlertDialog.Builder(context).setTitle("修改教师密钥").setView(box)
            .setPositiveButton("保存") { _, _ ->
                when {
                    new.text.toString() != confirm.text.toString() -> Toast.makeText(context, "两次输入不一致", Toast.LENGTH_SHORT).show()
                    else -> Toast.makeText(context, AuthService.change(old.text.toString(), new.text.toString()).second, Toast.LENGTH_SHORT).show()
                }
            }.setNegativeButton("取消", null).show()
    }

    private fun addDutyDialog() {
        val classes = allClasses()
        val classSpinner = context.uiSpinner(classes)
        var students = ScoreService.studentRows(classes.firstOrNull() ?: DataStore.className())
        val studentSpinner = context.uiSpinner(students.map { "${it.sid} ${it.name}" })
        val roleSpinner = context.uiSpinner(listOf("值日长", "卫生长"))
        val keyEdit = context.uiEdit("专用密钥（留空自动生成）")
        classSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                students = ScoreService.studentRows(classSpinner.selectedItem?.toString() ?: return)
                studentSpinner.adapter = ArrayAdapter(context, android.R.layout.simple_spinner_item,
                    students.map { "${it.sid} ${it.name}" }).apply {
                    setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
                }
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        val box = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            addView(classSpinner); addView(studentSpinner); addView(roleSpinner); addView(keyEdit)
        }
        AlertDialog.Builder(context).setTitle("任命值日生").setView(box)
            .setPositiveButton("任命") { _, _ ->
                val student = students.getOrNull(studentSpinner.selectedItemPosition)
                if (student == null) {
                    Toast.makeText(context, "请选择学生", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                val role = roleSpinner.selectedItem.toString()
                val kind = if (role == "卫生长") RolesService.KIND_HYGIENE else RolesService.KIND_SCORE
                val result = RolesService.addDuty(student.sid, student.name, role, kind, keyEdit.text.toString())
                Toast.makeText(context, result.second, Toast.LENGTH_LONG).show()
                refreshDuties()
            }.setNegativeButton("取消", null).show()
    }

    private fun removeDutyDialog() {
        val list = RolesService.duties()
        if (list.isEmpty()) {
            Toast.makeText(context, "暂无任命", Toast.LENGTH_SHORT).show()
            return
        }
        val labels = list.map { "${it.str("name")} · ${it.str("role")}" }.toTypedArray()
        AlertDialog.Builder(context).setTitle("撤销任命").setItems(labels) { _, which ->
            val result = RolesService.removeDuty(list[which].str("id"))
            Toast.makeText(context, result.second, Toast.LENGTH_SHORT).show()
            refreshDuties()
        }.show()
    }

    override fun tick() = refreshStatus()

    private fun refreshStatus() {
        val state = ScheduleService.state()
        statusText.text = buildString {
            appendLine("课节：${ScheduleService.stateLine(state)}")
            appendLine("局域网：${if (LanServer.running) "运行中 · ${LanServer.url()}" else "未启动"}")
            appendLine("云端：${CloudService.status}")
            appendLine("数据目录：${DataStore.path("settings.json").parentFile}")
        }
    }
}
