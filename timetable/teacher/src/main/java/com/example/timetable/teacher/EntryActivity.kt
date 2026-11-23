package com.example.timetable.teacher

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import java.util.Timer
import kotlin.concurrent.timerTask

private val ENTRY_BG = Color.rgb(0x1E, 0x1E, 0x2E)
private val ENTRY_PANEL = Color.rgb(0x2A, 0x2A, 0x3A)
private val ENTRY_TEXT = Color.rgb(0xE8, 0xE8, 0xF0)
private val ENTRY_DIM = Color.rgb(0x90, 0x90, 0xA0)
private val ENTRY_ACCENT = Color.rgb(0x7A, 0xB8, 0xFF)

private fun Context.edp(value: Int) = (value * resources.displayMetrics.density).toInt()

private fun Context.etext(text: String, size: Int = 16, color: Int = ENTRY_TEXT, bold: Boolean = false) =
    TextView(this).apply {
        this.text = text
        textSize = size.toFloat()
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

private fun Context.eedit(hint: String, password: Boolean = false) = EditText(this).apply {
    this.hint = hint
    setTextColor(ENTRY_TEXT)
    setHintTextColor(ENTRY_DIM)
    setBackgroundColor(ENTRY_PANEL)
    if (password) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
}

private fun Context.espinner(items: List<String>) = Spinner(this).apply {
    adapter = ArrayAdapter(this@espinner, android.R.layout.simple_spinner_item, items).apply {
        setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
    }
}

class EntryActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        DataStore.context = applicationContext
        AssetsInitializer.copyIfNeeded(applicationContext)

        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(ENTRY_BG)
            setPadding(edp(24), edp(24), edp(24), edp(24))
        }
        val scroll = ScrollView(this).apply { addView(body) }
        setContentView(scroll)

        body.addView(etext("课程表", 28, ENTRY_ACCENT, true).apply { gravity = Gravity.CENTER })
        body.addView(etext("请选择进入的身份", 14, ENTRY_DIM).apply {
            gravity = Gravity.CENTER
            setPadding(0, edp(4), 0, edp(20))
        })

        listOf(
            "教师端" to "进入完整管理界面，需要教师密钥" to ::teacherLogin,
            "学生端" to "查看自己的积分与课表，需学生密钥" to ::studentLogin,
            "值日生端" to "按职务进入积分 / 卫生管理" to ::dutyLogin,
            "查看信息" to "课程表、积分、卫生（只读，无需密钥）" to ::viewer,
        ).forEach { (titleDesc, action) ->
            val (title, desc) = titleDesc
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setBackgroundColor(ENTRY_PANEL)
                setPadding(edp(16), edp(14), edp(16), edp(14))
                setOnClickListener { action() }
            }
            card.addView(etext(title, 18, ENTRY_TEXT, true))
            card.addView(etext(desc, 13, ENTRY_DIM).apply { setPadding(0, edp(4), 0, 0) })
            body.addView(card, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { setMargins(0, 0, 0, edp(10)) })
        }
        body.addView(etext("教师初始密钥 710 · 忘记密钥可用教师手机号重置", 12, ENTRY_DIM).apply {
            gravity = Gravity.CENTER
            setPadding(0, edp(16), 0, 0)
        })
        askOverlayPermissionOnFirstLaunch()
    }

    override fun onResume() {
        super.onResume()
        if (SystemBall.canDraw(this)) SystemBall.show(applicationContext)
    }

    private fun askOverlayPermissionOnFirstLaunch() {
        val settings = DataStore.settings()
        if (settings.flag("overlay_permission_asked")) return
        settings["overlay_permission_asked"] = true
        DataStore.saveSettings(settings)
        if (SystemBall.canDraw(this)) {
            SystemBall.show(applicationContext)
            return
        }
        AlertDialog.Builder(this)
            .setTitle("开启悬浮球权限")
            .setMessage("为了在所有界面显示课程表悬浮球，需要开启「显示在其他应用上层」权限。若现在拒绝，可在设置页随时重新申请。")
            .setPositiveButton("去开启") { _, _ -> SystemBall.requestPermission(this) }
            .setNegativeButton("以后再说", null)
            .show()
    }

    private fun start(mode: String, extra: Bundle.() -> Unit = {}) {
        val intent = Intent(this, TeacherActivity::class.java).apply {
            putExtra(TeacherActivity.EXTRA_MODE, mode)
            putExtras(Bundle().apply(extra))
        }
        startActivity(intent)
    }

    private fun teacherLogin() {
        val key = eedit("教师密钥", true)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(key)
        }
        val dialog = AlertDialog.Builder(this).setTitle("教师端 · 密钥").setView(box)
            .setPositiveButton("进入", null)
            .setNeutralButton("忘记密钥", null)
            .setNegativeButton("取消", null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                if (AuthService.verify(key.text.toString())) {
                    dialog.dismiss()
                    start(TeacherActivity.MODE_TEACHER)
                } else {
                    Toast.makeText(this, "密钥不正确", Toast.LENGTH_SHORT).show()
                    key.text.clear()
                }
            }
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                dialog.dismiss()
                resetDialog("教师端 · 重置密钥", "重置教师密钥", "教师密钥重置请求", "teacher", "")
            }
        }
        dialog.show()
    }

    private fun studentLogin() {
        val classes = allClasses()
        val classSpinner = espinner(classes)
        var students = ScoreService.studentRows(classes.firstOrNull() ?: DataStore.className())
        val studentSpinner = espinner(students.map { "${it.sid} ${it.name}" })
        val key = eedit("学生密钥（默认学号）", true)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(classSpinner)
            addView(studentSpinner)
            addView(key)
        }
        fun refreshStudents() {
            val cls = classSpinner.selectedItem?.toString() ?: return
            students = ScoreService.studentRows(cls)
            studentSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item,
                students.map { "${it.sid} ${it.name}" }).apply {
                setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            }
        }
        classSpinner.setOnItemSelectedListener(object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: android.widget.AdapterView<*>?, v: View?, pos: Int, id: Long) = refreshStudents()
            override fun onNothingSelected(p: android.widget.AdapterView<*>?) {}
        })

        val dialog = AlertDialog.Builder(this).setTitle("学生端 · 登录").setView(box)
            .setPositiveButton("进入", null)
            .setNeutralButton("修改/忘记密钥", null)
            .setNegativeButton("取消", null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val selected = studentSpinner.selectedItemPosition
                val row = students.getOrNull(selected) ?: run {
                    Toast.makeText(this, "请选择学生", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                if (RolesService.studentVerify(row.sid, key.text.toString())) {
                    dialog.dismiss()
                    start(TeacherActivity.MODE_STUDENT) {
                        putString(TeacherActivity.EXTRA_SID, row.sid)
                        putString(TeacherActivity.EXTRA_NAME, row.name)
                        putString(TeacherActivity.EXTRA_CLASS, classSpinner.selectedItem.toString())
                    }
                } else Toast.makeText(this, "密钥不正确", Toast.LENGTH_SHORT).show()
            }
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                val row = students.getOrNull(studentSpinner.selectedItemPosition) ?: return@setOnClickListener
                changeKeyDialog("修改 ${row.name} 的学生密钥",
                    { RolesService.studentVerify(row.sid, it) },
                    { RolesService.studentSetKey(row.sid, it) })
            }
        }
        dialog.show()
    }

    private fun dutyLogin() {
        val students = allClasses().flatMap { cls ->
            ScoreService.studentRows(cls).map { row -> Triple(cls, row, "${row.sid} ${row.name}") }
        }
        val studentSpinner = espinner(students.map { it.third })
        var duties = emptyList<Map<String, Any?>>()
        val dutySpinner = espinner(emptyList())
        val key = eedit("专用密钥", true)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(studentSpinner)
            addView(dutySpinner)
            addView(key)
        }
        fun refreshDuties() {
            val row = students.getOrNull(studentSpinner.selectedItemPosition) ?: return
            duties = RolesService.dutiesFor(row.second.sid)
            dutySpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item,
                duties.map { "${it.str("role")} · ${if (it.str("kind") == RolesService.KIND_HYGIENE) "卫生管理" else "积分管理"}" }).apply {
                setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            }
        }
        studentSpinner.setOnItemSelectedListener(object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: android.widget.AdapterView<*>?, v: View?, pos: Int, id: Long) = refreshDuties()
            override fun onNothingSelected(p: android.widget.AdapterView<*>?) {}
        })
        refreshDuties()

        val dialog = AlertDialog.Builder(this).setTitle("值日生端 · 登录").setView(box)
            .setPositiveButton("进入", null)
            .setNeutralButton("忘记密钥", null)
            .setNegativeButton("取消", null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val duty = duties.getOrNull(dutySpinner.selectedItemPosition)
                val row = students.getOrNull(studentSpinner.selectedItemPosition)
                if (duty == null || row == null) {
                    Toast.makeText(this, "该学生没有被任命为值日生", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                if (RolesService.dutyVerify(duty, key.text.toString())) {
                    dialog.dismiss()
                    val mode = if (duty.str("kind") == RolesService.KIND_HYGIENE)
                        TeacherActivity.MODE_DUTY_HYGIENE else TeacherActivity.MODE_DUTY_SCORE
                    start(mode) {
                        putString(TeacherActivity.EXTRA_DUTY_ID, duty.str("id"))
                        putString(TeacherActivity.EXTRA_CLASS, row.first)
                        putString(TeacherActivity.EXTRA_NAME, duty.str("name"))
                        putString(TeacherActivity.EXTRA_ROLE, duty.str("role"))
                    }
                } else Toast.makeText(this, "专用密钥不正确", Toast.LENGTH_SHORT).show()
            }
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                val duty = duties.getOrNull(dutySpinner.selectedItemPosition) ?: return@setOnClickListener
                dialog.dismiss()
                resetDialog("值日生 · 重置密钥", "重置 ${duty.str("name")} 的专用密钥",
                    "重置值日生密钥：${duty.str("name")}", "duty", duty.str("id"))
            }
        }
        dialog.show()
    }

    private fun viewer() = start(TeacherActivity.MODE_VIEW)

    private fun changeKeyDialog(title: String, verify: (String) -> Boolean, save: (String) -> Pair<Boolean, String>) {
        val old = eedit("原密钥", true)
        val new = eedit("新密钥", true)
        val confirm = eedit("确认新密钥", true)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(old); addView(new); addView(confirm)
        }
        AlertDialog.Builder(this).setTitle(title).setView(box)
            .setPositiveButton("保存") { _, _ ->
                when {
                    !verify(old.text.toString()) -> Toast.makeText(this, "原密钥不正确", Toast.LENGTH_SHORT).show()
                    new.text.isBlank() -> Toast.makeText(this, "新密钥不能为空", Toast.LENGTH_SHORT).show()
                    new.text.toString() != confirm.text.toString() -> Toast.makeText(this, "两次输入不一致", Toast.LENGTH_SHORT).show()
                    else -> Toast.makeText(this, save(new.text.toString()).second, Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("取消", null).show()
    }

    private fun resetDialog(title: String, requestTitle: String, detail: String, kind: String, target: String) {
        if (RolesService.phone().isBlank()) {
            Toast.makeText(this, "教师尚未绑定手机号，无法自助重置", Toast.LENGTH_LONG).show()
            return
        }
        val phone = eedit("教师绑定的手机号")
        val newKey = eedit("新密钥", true)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(phone); addView(newKey)
        }
        AlertDialog.Builder(this).setTitle(title).setView(box)
            .setPositiveButton("发送重置请求") { _, _ ->
                if (!RolesService.verifyPhone(phone.text.toString())) {
                    Toast.makeText(this, "手机号与教师绑定的号码不一致", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                if (newKey.text.isBlank()) {
                    Toast.makeText(this, "新密钥不能为空", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                val result = KeyResetService.submit(kind, target, requestTitle, detail, newKey.text.toString())
                val id = result.second
                val waiting = AlertDialog.Builder(this)
                    .setTitle("等待手机确认")
                    .setMessage("已向手机发送「$requestTitle」，请在手机 App 中点击同意。")
                    .setNegativeButton("取消", null).create()
                waiting.show()
                val timer = Timer(true)
                timer.scheduleAtFixedRate(timerTask {
                    val status = KeyResetService.status(id)
                    if (status == "approved" || status == "rejected" || status == "expired" || status == "missing") {
                        timer.cancel()
                        runOnUiThread {
                            waiting.dismiss()
                            if (status == "approved") {
                                val applied = KeyResetService.apply(id)
                                Toast.makeText(this@EntryActivity, applied.second, Toast.LENGTH_LONG).show()
                            } else {
                                Toast.makeText(this@EntryActivity, "重置未生效：$status", Toast.LENGTH_LONG).show()
                            }
                        }
                    }
                }, 1000, 1000)
            }
            .setNegativeButton("取消", null).show()
    }
}
