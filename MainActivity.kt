package com.example.timetable

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.app.Activity          // 新增
import android.app.AlertDialog       // 新增：填写电脑端地址
import android.util.Log              // 新增
import android.widget.EditText       // 新增
import android.widget.Toast          // 新增
import org.json.JSONArray            // 新增：解析局域网 JSON
import org.json.JSONObject
import java.io.File                  // 新增
import java.net.HttpURLConnection     // 新增：SSE 长连接
import java.net.URL
import kotlin.math.min

// ============================================================================
// 一、数据层（来自电脑端局域网接口）
// ============================================================================

data class Period(
    val id: Int, val name: String, val start: String, val end: String
)

data class CourseCell(
    val dayIndex: Int, val periodId: Int, val subject: String, val classroom: String
)

data class ScoreRecord(
    val time: String, val reason: String, val delta: Int
)

data class GroupScore(
    val name: String, val leader: String, val total: Int, val records: List<ScoreRecord>
)

data class HygieneRecord(
    val group: String, val member: String, val reason: String, val score: Int, val time: String
)

/**
 * 全局数据仓库：内容全部来自电脑端的 /api/snapshot。
 * 电脑端没连上时只保留固定作息骨架，课表、积分、卫生都为空。
 */
object AppData {

    var className = "七年级10班"
    var stateLine = "等待电脑端数据…"
    var currentDayIndex = -1
    var currentPeriodId = -1
    var currentName = ""
    var isInClass = false

    var periods: List<Period> = listOf(
        Period(1, "第1节", "08:00", "08:45"),
        Period(2, "第2节", "09:00", "09:45"),
        Period(3, "第3节", "10:15", "11:00"),
        Period(4, "第4节", "11:10", "11:50"),
        Period(5, "第5节", "13:45", "14:30"),
        Period(6, "第6节", "14:45", "15:30"),
        Period(7, "第7节", "15:45", "16:30"),
    )

    var extraSlots: List<Period> = listOf(
        Period(99, "午间小练", "12:25", "12:50"),
        Period(100, "晚辅", "17:10", "18:10"),
    )

    var schedule: List<CourseCell> = emptyList()

    val weekDayNames = listOf("周一", "周二", "周三", "周四", "周五")

    var groupScores: List<GroupScore> = emptyList()

    var hygieneRecords: List<HygieneRecord> = emptyList()
    var hygieneTotalRecords = 0
    var hygieneTotalDeduct = 0
    var hygieneByGroup: List<Pair<String, Int>> = emptyList()
    var hygieneByReason: List<Pair<String, Int>> = emptyList()

    fun buildSchedule(): List<CourseCell> = schedule

    /** 把电脑端 /api/snapshot 返回的 JSON 写入界面数据。 */
    fun applySnapshot(root: JSONObject) {
        root.optString("class_name").takeIf { it.isNotBlank() }?.let { className = it }

        root.optJSONObject("state")?.let { st ->
            currentDayIndex = st.optInt("day", -1)
            val period = st.opt("current_period")
            currentPeriodId = if (period is Number) period.toInt() else -1
            currentName = st.optString("current_name")
            isInClass = st.optString("state") == "in_class"
            val next = st.optString("next_subject")
            stateLine = when (st.optString("state")) {
                "in_class" -> "正在上课 · ${st.optString("current_name")} ${st.optString("current_subject")}"
                "before_class" -> "上课前 · 下一节 $next"
                "between_class" -> "课间 · 下一节 $next"
                "after_school" -> "已放学"
                "weekend" -> "周末"
                "disabled" -> "暂停提醒 · ${st.optString("disabled_note")}"
                else -> stateLine
            }
        }

        root.optJSONArray("periods")?.let { arr ->
            val list = ArrayList<Period>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                list.add(Period(o.optInt("id"), o.optString("name"),
                    o.optString("start"), o.optString("end")))
            }
            if (list.isNotEmpty()) periods = list
        }
        root.optJSONArray("extra_slots")?.let { arr ->
            val list = ArrayList<Period>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                list.add(Period(o.optInt("id"), o.optString("name"),
                    o.optString("start"), o.optString("end")))
            }
            if (list.isNotEmpty()) extraSlots = list
        }

        val cells = ArrayList<CourseCell>()
        listOf("schedule", "extra_schedule").forEach { key ->
            root.optJSONArray(key)?.let { arr ->
                for (i in 0 until arr.length()) {
                    val o = arr.optJSONObject(i) ?: continue
                    cells.add(CourseCell(
                        o.optInt("day_index"), o.optInt("period_id"),
                        o.optString("subject"), o.optString("classroom")))
                }
            }
        }
        schedule = cells

        root.optJSONArray("groups")?.let { arr ->
            val list = ArrayList<GroupScore>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val recs = ArrayList<ScoreRecord>()
                o.optJSONArray("records")?.let { rs ->
                    for (j in 0 until rs.length()) {
                        val r = rs.optJSONObject(j) ?: continue
                        recs.add(ScoreRecord(r.optString("time"),
                            r.optString("reason"), r.optInt("delta")))
                    }
                }
                list.add(GroupScore(o.optString("name"), o.optString("leader"),
                    o.optInt("total"), recs))
            }
            groupScores = list.sortedByDescending { it.total }
        }

        root.optJSONObject("hygiene")?.let { hy ->
            hygieneTotalRecords = hy.optInt("total_records", 0)
            hygieneTotalDeduct = hy.optInt("total_deduct", 0)
            hygieneByGroup = parsePairs(hy.optJSONArray("by_group"))
            hygieneByReason = parsePairs(hy.optJSONArray("by_reason"))
            val recs = ArrayList<HygieneRecord>()
            hy.optJSONArray("records")?.let { arr ->
                for (i in 0 until arr.length()) {
                    val o = arr.optJSONObject(i) ?: continue
                    recs.add(HygieneRecord(o.optString("group"), o.optString("member"),
                        o.optString("reason"), o.optInt("score"), o.optString("time")))
                }
            }
            hygieneRecords = recs
        }
    }

    /** [["第一组",5], ...] → List<Pair<String,Int>> */
    private fun parsePairs(arr: JSONArray?): List<Pair<String, Int>> {
        if (arr == null) return emptyList()
        val list = ArrayList<Pair<String, Int>>()
        for (i in 0 until arr.length()) {
            val pair = arr.optJSONArray(i) ?: continue
            list.add(pair.optString(0) to pair.optInt(1))
        }
        return list
    }

    fun hygieneTotalsByGroup(): List<Pair<String, Int>> {
        if (hygieneByGroup.isNotEmpty()) return hygieneByGroup
        val map = linkedMapOf<String, Int>()
        hygieneRecords.forEach { r -> map[r.group] = (map[r.group] ?: 0) + r.score }
        return map.entries.sortedByDescending { it.value }.map { it.key to it.value }
    }

    fun hygieneCountsByReason(): List<Pair<String, Int>> {
        if (hygieneByReason.isNotEmpty()) return hygieneByReason
        val map = linkedMapOf<String, Int>()
        hygieneRecords.forEach { r -> map[r.reason] = (map[r.reason] ?: 0) + 1 }
        return map.entries.sortedByDescending { it.value }.map { it.key to it.value }
    }
}

/**
 * 局域网客户端：与电脑端的 /api/events 建立 SSE 长连接。
 * 电脑端在打分、扣分、调课、上下课时会立即推送 snapshot；断线后每 3 秒自动重连。
 */
class LanClient(
    private val onSnapshot: (JSONObject) -> Unit,
    private val onStatus: (String, Boolean) -> Unit
) {
    @Volatile private var running = false
    @Volatile private var active: HttpURLConnection? = null
    private var worker: Thread? = null

    fun start(baseUrl: String) {
        stop()
        running = true
        val base = baseUrl.trimEnd('/')
        worker = Thread({ loop(base) }, "lan-client").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running = false
        try {
            active?.disconnect()
        } catch (_: Exception) {
        }
        active = null
        worker?.interrupt()
        worker = null
    }

    private fun loop(base: String) {
        while (running) {
            var conn: HttpURLConnection? = null
            try {
                onStatus("连接中…", false)
                conn = (URL("$base/api/events").openConnection() as HttpURLConnection).apply {
                    connectTimeout = 4000
                    readTimeout = 0
                    requestMethod = "GET"
                    setRequestProperty("Accept", "text/event-stream")
                    setRequestProperty("Cache-Control", "no-cache")
                }
                active = conn
                if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                    throw java.io.IOException("HTTP ${conn.responseCode}")
                }
                onStatus("已连接", true)

                // SSE 格式：event: snapshot / data: {...} / 空行
                conn.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                    var event = "message"
                    val data = StringBuilder()
                    while (running) {
                        val line = reader.readLine() ?: break
                        when {
                            line.isEmpty() -> {
                                if (data.isNotEmpty()) handle(event, data.toString())
                                event = "message"
                                data.setLength(0)
                            }
                            line.startsWith("event:") -> event = line.substring(6).trim()
                            line.startsWith("data:") -> {
                                if (data.isNotEmpty()) data.append('\n')
                                data.append(line.substring(5).trim())
                            }
                            // 以 ":" 开头的是心跳注释，忽略
                        }
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("LanClient", "连接 $base 失败", e)
                if (running) {
                    onStatus("连接失败：${e.message ?: e.javaClass.simpleName}", false)
                    try {
                        Thread.sleep(3000)
                    } catch (_: InterruptedException) {
                        return
                    }
                }
            } finally {
                try {
                    conn?.disconnect()
                } catch (_: Exception) {
                }
                active = null
            }
        }
    }

    private fun handle(event: String, raw: String) {
        if (event != "snapshot") return
        try {
            onSnapshot(JSONObject(raw))
        } catch (_: Exception) {
            // 单条数据解析失败时忽略，等待下一次推送
        }
    }
}

// ============================================================================
// 二、UI 工具
// ============================================================================

fun Context.dp2px(dp: Int): Int =
    TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, dp.toFloat(), resources.displayMetrics).toInt()

fun Context.sp2px(sp: Int): Float =
    TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, sp.toFloat(), resources.displayMetrics)

fun TextView.textSizeSp(sp: Int) { textSize = sp.toFloat() }

// ============================================================================
// 三、MainActivity —— 顶部导航 + 三个 Tab
// ============================================================================

class MainActivity : Activity() {
    private lateinit var pageContainer: FrameLayout
    private lateinit var schedulePage: View
    private lateinit var scorePage: View
    private lateinit var hygienePage: View
    private lateinit var tabButtons: List<Button>
    private lateinit var classLabel: TextView
    private lateinit var statusLabel: TextView
    private var currentTab = 0

    private val prefs by lazy { getSharedPreferences("lan_config", MODE_PRIVATE) }
    private val client = LanClient(
        onSnapshot = { json -> runOnUiThread { applySnapshot(json) } },
        onStatus = { text, ok -> runOnUiThread { updateStatus(text, ok) } }
    )

    companion object {
        private const val KEY_URL = "server_url"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestWindowFeature(android.view.Window.FEATURE_NO_TITLE)
        try {
            setContentView(buildRoot())
        } catch (t: Throwable) {
            showCrash(t)
        }
    }

    override fun onStart() {
        super.onStart()
        val url = prefs.getString(KEY_URL, "") ?: ""
        if (url.isBlank()) {
            updateStatus("未连接 · 点此设置电脑地址", false)
        } else {
            connect(url)
        }
    }

    override fun onStop() {
        client.stop()
        super.onStop()
    }

    override fun onDestroy() {
        client.stop()
        super.onDestroy()
    }

    // 收到电脑端推送后刷新数据与页面
    private fun applySnapshot(json: JSONObject) {
        if (!::pageContainer.isInitialized) return
        AppData.applySnapshot(json)
        classLabel.text = "  ·  ${AppData.className}"
        updateStatus("已连接 · ${AppData.className}", true)
        rebuildPages()
    }

    // 数据变化后重建三个页面（当前 Tab 保持不变）
    private fun rebuildPages() {
        val index = currentTab
        pageContainer.removeAllViews()
        schedulePage = buildSchedulePage(this)
        scorePage = buildScorePage(this)
        hygienePage = buildHygienePage(this)
        pageContainer.addView(schedulePage)
        pageContainer.addView(scorePage)
        pageContainer.addView(hygienePage)
        switchPage(index)
    }

    private fun connect(rawUrl: String) {
        val url = normalizeUrl(rawUrl)
        if (url.isEmpty()) return
        updateStatus("连接中…", false)
        client.start(url)
    }

    private fun updateStatus(text: String, ok: Boolean) {
        if (!::statusLabel.isInitialized) return
        statusLabel.text = text
        statusLabel.setTextColor(
            Color.parseColor(if (ok) "#B9F6CA" else "#FFE0B2")
        )
    }

    // 弹出地址设置框：电脑端「更多功能 → 局域网连接（手机）」里有地址
    private fun showServerDialog() {
        val input = EditText(this).apply {
            hint = "http://192.168.1.23:8765"
            setText(prefs.getString(KEY_URL, ""))
            setSingleLine()
            inputType = android.text.InputType.TYPE_CLASS_TEXT or
                    android.text.InputType.TYPE_TEXT_VARIATION_URI
            setTextColor(Color.parseColor("#1A1A2E"))
            setPadding(dp2px(16), dp2px(8), dp2px(16), dp2px(8))
        }
        AlertDialog.Builder(this)
            .setTitle("电脑端地址")
            .setMessage("在电脑上打开「更多功能 → 局域网连接（手机）」，把显示的地址填到这里。手机需与电脑连接同一个 Wi-Fi。")
            .setView(input)
            .setPositiveButton("连接") { _, _ ->
                val url = normalizeUrl(input.text.toString())
                if (url.isEmpty()) {
                    Toast.makeText(this, "地址不能为空", Toast.LENGTH_SHORT).show()
                } else {
                    prefs.edit().putString(KEY_URL, url).apply()
                    connect(url)
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun normalizeUrl(raw: String): String {
        var url = raw.trim()
        if (url.isEmpty()) return ""
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://$url"
        }
        url = url.trimEnd('/')
        // 只填了 IP 没填端口时，补上电脑端默认端口
        if (!url.substringAfter("://").contains(":")) {
            url = "$url:8765"
        }
        return url
    }

    // 把崩溃信息显示在屏幕上，防止直接闪退
    private fun showCrash(t: Throwable) {
        val msg = android.util.Log.getStackTraceString(t)
        // 顺便存一份到本地文件
        try {
            val file = java.io.File(filesDir, "crash.txt")
            file.writeText(msg)
        } catch (e: Exception) {
        }

        val tv = TextView(this).apply {
            text = msg
            setTextColor(android.graphics.Color.RED)
            textSize = 10f
            setPadding(20, 100, 20, 20)
            setTextIsSelectable(true) // 允许长按复制报错文本
        }
        // 用 ScrollView 包裹，防止报错太长看不全
        val scroll = ScrollView(this).apply { addView(tv) }
        setContentView(scroll)
    }
    private fun buildRoot(): View {
        val ctx = this
        val root = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#F5F6FA"))
        }

        val topBar = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(Color.parseColor("#1B5E8C"))
            setPadding(ctx.dp2px(16), ctx.dp2px(14), ctx.dp2px(16), ctx.dp2px(6))
            elevation = ctx.dp2px(4).toFloat()
        }
        topBar.addView(TextView(ctx).apply {
            text = "课程表管理"; setTextColor(Color.WHITE)
            typeface = Typeface.DEFAULT_BOLD; textSizeSp(20)
        })
        classLabel = TextView(ctx).apply {
            text = "  ·  ${AppData.className}"
            setTextColor(Color.parseColor("#B0D4EA")); textSizeSp(13)
        }
        topBar.addView(classLabel)
        statusLabel = TextView(ctx).apply {
            text = "未连接"
            setTextColor(Color.parseColor("#FFE0B2")); textSizeSp(11)
            gravity = Gravity.END
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(ctx.dp2px(8), 0, 0, 0)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener { showServerDialog() }
        }
        topBar.addView(statusLabel)
        root.addView(topBar)

        val tabBar = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(Color.parseColor("#1B5E8C"))
            setPadding(0, 0, 0, ctx.dp2px(10))
        }
        tabButtons = listOf(
            makeTabButton("📅 课表", 0),
            makeTabButton("⭐ 积分", 1),
            makeTabButton("🧹 卫生", 2),
        )
        tabButtons.forEach { tabBar.addView(it) }
        root.addView(tabBar)

        pageContainer = FrameLayout(ctx).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        root.addView(pageContainer)

        schedulePage = buildSchedulePage(ctx)
        scorePage    = buildScorePage(ctx)
        hygienePage  = buildHygienePage(ctx)
        pageContainer.addView(schedulePage)
        pageContainer.addView(scorePage)
        pageContainer.addView(hygienePage)

        switchPage(0)
        return root
    }

    private fun makeTabButton(text: String, index: Int): Button {
        val ctx = this
        return Button(ctx).apply {
            this.text = text; tag = index; setTextColor(Color.WHITE)
            textSizeSp(14); typeface = Typeface.DEFAULT_BOLD
            setPadding(ctx.dp2px(8), ctx.dp2px(8), ctx.dp2px(8), ctx.dp2px(8))
            setBackgroundColor(Color.TRANSPARENT); background = null
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener { switchPage(index) }; isAllCaps = false
        }
    }

    private fun switchPage(index: Int) {
        currentTab = index
        schedulePage.visibility = if (index == 0) View.VISIBLE else View.GONE
        scorePage.visibility    = if (index == 1) View.VISIBLE else View.GONE
        hygienePage.visibility  = if (index == 2) View.VISIBLE else View.GONE
        tabButtons.forEachIndexed { i, btn ->
            val selected = i == index
            btn.setTextColor(if (selected) Color.parseColor("#FFD54F") else Color.parseColor("#C0DBEE"))
            btn.typeface = if (selected) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        }
    }
}


// ============================================================================
// 四、课表页
// ============================================================================

private fun buildSchedulePage(ctx: Context): View {
    val scrollView = ScrollView(ctx).apply {
        setBackgroundColor(Color.parseColor("#F5F6FA")); isFillViewport = true
    }
    val container = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(ctx.dp2px(12), ctx.dp2px(12), ctx.dp2px(12), ctx.dp2px(12))
    }

    container.addView(makeCard(ctx).apply {
        addView(TextView(ctx).apply {
            text = "本周课程表"; setTextColor(Color.parseColor("#1B5E8C"))
            typeface = Typeface.DEFAULT_BOLD; textSizeSp(18)
            setPadding(ctx.dp2px(16), ctx.dp2px(14), ctx.dp2px(16), ctx.dp2px(4))
        })
        addView(TextView(ctx).apply {
            text = AppData.stateLine
            setTextColor(Color.parseColor("#2E7D32")); textSizeSp(12)
            setPadding(ctx.dp2px(16), 0, ctx.dp2px(16), ctx.dp2px(2))
        })
        addView(TextView(ctx).apply {
            text = "共 5 天 · 每天 7 节正课 + 午间小练 + 晚辅"
            setTextColor(Color.parseColor("#707080")); textSizeSp(12)
            setPadding(ctx.dp2px(16), 0, ctx.dp2px(16), ctx.dp2px(12))
        })
    })

    val hsv = HorizontalScrollView(ctx)
    val gridCard = makeCard(ctx).apply { setPadding(ctx.dp2px(6), ctx.dp2px(6), ctx.dp2px(6), ctx.dp2px(6)) }
    val cellW = ctx.dp2px(96); val cellH = ctx.dp2px(60); val labelW = ctx.dp2px(56)

    // 外层垂直容器：表头一行 + 每节课一行
    val grid = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }

    // 表头行
    val headerRow = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
    headerRow.addView(makeHeaderCell(ctx, "节次", labelW, cellH, bold = true))
    AppData.weekDayNames.forEach { headerRow.addView(makeHeaderCell(ctx, it, cellW, cellH, bold = true, isDayHeader = true)) }
    grid.addView(headerRow)

    val subjectsRow = AppData.buildSchedule()
    AppData.periods.forEach { period ->
        val row = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(makePeriodLabel(ctx, period, labelW, cellH))
        for (day in 0..4) {
            val c = subjectsRow.firstOrNull { it.dayIndex == day && it.periodId == period.id }
            val isNow = AppData.isInClass && AppData.currentDayIndex == day &&
                    AppData.currentPeriodId == period.id
            row.addView(makeCourseCell(ctx, c?.subject ?: "", c?.classroom ?: "",
                cellW, cellH, period.id, isNow = isNow))
        }
        grid.addView(row)
    }
    AppData.extraSlots.forEach { slot ->
        val row = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(makePeriodLabel(ctx, slot, labelW, cellH, extra = true))
        for (day in 0..4) {
            val c = subjectsRow.firstOrNull { it.dayIndex == day && it.periodId == slot.id }
            val serverSubject = c?.subject.orEmpty()
            val subj = when {
                serverSubject.isNotBlank() ->
                    if (slot.name == "午间小练" && !serverSubject.contains("小练")) "${serverSubject}小练"
                    else serverSubject
                slot.name == "午间小练" && day == 2 -> "英语小练"
                slot.name == "午间小练" -> "数学小练"
                else -> slot.name
            }
            val isNow = AppData.isInClass && AppData.currentName == slot.name
            row.addView(makeCourseCell(ctx, subj, "", cellW, cellH, slot.id,
                extra = true, isNow = isNow))
        }
        grid.addView(row)
    }
    gridCard.addView(grid)
    hsv.addView(gridCard)
    container.addView(hsv)

    container.addView(makeCard(ctx).apply {
        setPadding(ctx.dp2px(16), ctx.dp2px(12), ctx.dp2px(16), ctx.dp2px(12))
        val legend = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        listOf(
            "#E3F2FD" to "正课（语文 / 数学 / 英语 …）",
            "#E8F5E9" to "体育课 / 信息课 / 音乐 / 美术",
            "#FFF3E0" to "午间小练 / 晚辅（非正课）",
        ).forEach { (c, t) ->
            legend.addView(LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                setPadding(0, ctx.dp2px(2), 0, ctx.dp2px(2))
                addView(View(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(ctx.dp2px(16), ctx.dp2px(16))
                    setBackgroundColor(Color.parseColor(c))
                })
                addView(TextView(ctx).apply {
                    text = t; setTextColor(Color.parseColor("#1A1A2E")); textSizeSp(12)
                    setPadding(ctx.dp2px(8), 0, 0, 0)
                })
            })
        }
        addView(legend)
    })

    scrollView.addView(container)
    return scrollView
}

private fun makeCard(ctx: Context): LinearLayout = LinearLayout(ctx).apply {
    orientation = LinearLayout.VERTICAL
    setBackgroundColor(Color.WHITE)
    elevation = ctx.dp2px(2).toFloat()
    layoutParams = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = ctx.dp2px(8) }
}

private fun makeHeaderCell(
    ctx: Context, text: String, w: Int, h: Int,
    bold: Boolean = false, isDayHeader: Boolean = false
): TextView {
    val bg = if (isDayHeader) "#1B5E8C" else "#37474F"
    val tc = if (isDayHeader) "#FFFFFF" else "#ECEFF1"
    return TextView(ctx).apply {
        this.text = text; setTextColor(Color.parseColor(tc))
        typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        textSizeSp(13); gravity = Gravity.CENTER
        setBackgroundColor(Color.parseColor(bg))
        layoutParams = LinearLayout.LayoutParams(w, h)
        setPadding(ctx.dp2px(4), ctx.dp2px(4), ctx.dp2px(4), ctx.dp2px(4))
    }
}

private fun makePeriodLabel(ctx: Context, p: Period, w: Int, h: Int, extra: Boolean = false): LinearLayout {
    return LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
        setBackgroundColor(android.graphics.Color.parseColor(if (extra) "#FFF3E0" else "#ECEFF1"))
        layoutParams = LinearLayout.LayoutParams(w, h)
        addView(TextView(ctx).apply {
            text = p.name; setTextColor(Color.parseColor("#1B5E8C"))
            typeface = Typeface.DEFAULT_BOLD; textSizeSp(12); gravity = Gravity.CENTER
        })
        addView(TextView(ctx).apply {
            text = "${p.start}-${p.end}"
            setTextColor(Color.parseColor("#607D8B")); textSizeSp(10); gravity = Gravity.CENTER
        })
    }
}

private fun makeCourseCell(
    ctx: Context, subject: String, classroom: String, w: Int, h: Int,
    periodId: Int, extra: Boolean = false, isNow: Boolean = false
): LinearLayout {
    val subjectColors = mapOf(
        "语文" to "#E3F2FD", "数学" to "#E8EAF6", "英语" to "#FCE4EC",
        "体育" to "#E8F5E9", "信息" to "#E0F7FA", "音乐" to "#FFF8E1",
        "美术" to "#F3E5F5", "劳动" to "#F1F8E9", "地理" to "#E0F2F1",
        "历史" to "#FFEBEE", "生物" to "#E6F4EA", "道法" to "#E8EAF6",
        "班会" to "#FFF3E0", "选修课" to "#F3E5F5",
    )
    val bg = when {
        isNow -> "#C8E6C9"
        extra -> "#FFF3E0"
        subjectColors.containsKey(subject) -> subjectColors[subject]!!
        else -> "#FFFFFF"
    }
    return LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
        setBackgroundColor(Color.parseColor(bg))
        layoutParams = LinearLayout.LayoutParams(w, h)
        setPadding(ctx.dp2px(4), ctx.dp2px(4), ctx.dp2px(4), ctx.dp2px(4))
        addView(TextView(ctx).apply {
            text = subject.ifEmpty { "—" }; setTextColor(Color.parseColor("#1A1A2E"))
            typeface = Typeface.DEFAULT_BOLD; textSizeSp(13); gravity = Gravity.CENTER; maxLines = 2
        })
        if (classroom.isNotEmpty()) {
            addView(TextView(ctx).apply {
                text = "📍 $classroom"; setTextColor(Color.parseColor("#546E7A"))
                textSizeSp(10); gravity = Gravity.CENTER
            })
        }
    }
}

// ============================================================================
// 五、积分页
// ============================================================================

private fun buildScorePage(ctx: Context): View {
    val scrollView = ScrollView(ctx).apply {
        setBackgroundColor(Color.parseColor("#F5F6FA")); isFillViewport = true
    }
    val container = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(ctx.dp2px(12), ctx.dp2px(12), ctx.dp2px(12), ctx.dp2px(12))
    }

    val summaryCard = makeCard(ctx).apply {
        setPadding(ctx.dp2px(16), ctx.dp2px(14), ctx.dp2px(16), ctx.dp2px(14))
    }
    summaryCard.addView(TextView(ctx).apply {
        text = "小组积分榜"; setTextColor(Color.parseColor("#1B5E8C"))
        typeface = Typeface.DEFAULT_BOLD; textSizeSp(18)
    })
    val totalPos = AppData.groupScores.sumOf { maxOf(it.total, 0) }
    val totalNeg = AppData.groupScores.sumOf { minOf(it.total, 0) }
    summaryCard.addView(LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL; setPadding(0, ctx.dp2px(8), 0, 0)
        addView(buildStatChip(ctx, "参与小组", "${AppData.groupScores.size} 组"))
        addView(buildStatChip(ctx, "累计加分", "+$totalPos", "#2E7D32"))
        addView(buildStatChip(ctx, "累计扣分", "$totalNeg", "#C62828"))
    })
    container.addView(summaryCard)

    AppData.groupScores.sortedByDescending { it.total }.forEachIndexed { idx, g ->
        container.addView(buildGroupCard(ctx, idx, g))
    }
    if (AppData.groupScores.isEmpty()) {
        container.addView(makeCard(ctx).apply {
            setPadding(ctx.dp2px(16), ctx.dp2px(18), ctx.dp2px(16), ctx.dp2px(18))
            addView(TextView(ctx).apply {
                text = "等待电脑端数据…\n请确认手机与电脑连接同一个 Wi-Fi，并点击顶部「未连接」填写电脑地址。"
                setTextColor(Color.parseColor("#707080")); textSizeSp(13)
                gravity = Gravity.CENTER
            })
        })
    }
    scrollView.addView(container)
    return scrollView
}

private fun buildStatChip(ctx: Context, label: String, value: String, valueColor: String = "#1A1A2E"): LinearLayout {
    return LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            .apply { marginEnd = ctx.dp2px(6) }
        setBackgroundColor(Color.parseColor("#EAF2FA"))
        setPadding(ctx.dp2px(10), ctx.dp2px(10), ctx.dp2px(10), ctx.dp2px(10))
        addView(TextView(ctx).apply { text = label; setTextColor(Color.parseColor("#707080")); textSizeSp(11) })
        addView(TextView(ctx).apply {
            text = value; setTextColor(Color.parseColor(valueColor))
            typeface = Typeface.DEFAULT_BOLD; textSizeSp(16)
            setPadding(0, ctx.dp2px(2), 0, 0)
        })
    }
}

private fun buildGroupCard(ctx: Context, index: Int, g: GroupScore): LinearLayout {
    val medal = when (index) {
        0 -> "🥇"; 1 -> "🥈"; 2 -> "🥉"; else -> "　"
    }
    val card = makeCard(ctx).apply {
        setPadding(ctx.dp2px(16), ctx.dp2px(14), ctx.dp2px(16), ctx.dp2px(14))
    }

    // 第一行：排名 + 组名 + 组长 + 总分
    val row1 = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }
    row1.addView(TextView(ctx).apply {
        text = medal; textSizeSp(20); setPadding(0, 0, ctx.dp2px(6), 0)
    })
    row1.addView(TextView(ctx).apply {
        text = g.name; setTextColor(Color.parseColor("#1A1A2E"))
        typeface = Typeface.DEFAULT_BOLD; textSizeSp(17)
    })
    row1.addView(TextView(ctx).apply {
        text = "  组长：${g.leader}"; setTextColor(Color.parseColor("#707080")); textSizeSp(12)
    })
    row1.addView(TextView(ctx).apply {
        text = "${if (g.total >= 0) "+" else ""}${g.total}"
        setTextColor(if (g.total >= 0) Color.parseColor("#2E7D32") else Color.parseColor("#C62828"))
        typeface = Typeface.DEFAULT_BOLD; textSizeSp(22); gravity = Gravity.END
        layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
    })
    card.addView(row1)

    // 第二行：加/扣分统计
    val addSum = g.records.filter { it.delta > 0 }.sumOf { it.delta }
    val subSum = g.records.filter { it.delta < 0 }.sumOf { it.delta }
    val row2 = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        setPadding(0, ctx.dp2px(6), 0, ctx.dp2px(4))
    }
    row2.addView(makeMiniTag(ctx, "加分 +$addSum", "#E8F5E9", "#2E7D32"))
    val subTag = makeMiniTag(ctx, "扣分 $subSum", "#FFEBEE", "#C62828")
    row2.addView(subTag)
    (subTag.layoutParams as LinearLayout.LayoutParams).marginStart = ctx.dp2px(8)
    row2.addView(TextView(ctx).apply {
        text = "共 ${g.records.size} 条记录"; setTextColor(Color.parseColor("#707080"))
        textSizeSp(11); gravity = Gravity.END
        layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
    })
    card.addView(row2)

    // 分割线
    card.addView(View(ctx).apply {
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ctx.dp2px(1)
        ).apply { topMargin = ctx.dp2px(4); bottomMargin = ctx.dp2px(8) }
        setBackgroundColor(Color.parseColor("#E0E0E0"))
    })

    // 第三行：每条记录
    g.records.take(4).forEach { rec ->
        val recordRow = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, ctx.dp2px(2), 0, ctx.dp2px(2))
        }
        recordRow.addView(TextView(ctx).apply {
            text = rec.time; setTextColor(Color.parseColor("#909090")); textSizeSp(11)
            layoutParams = LinearLayout.LayoutParams(ctx.dp2px(70), ViewGroup.LayoutParams.WRAP_CONTENT)
        })
        recordRow.addView(TextView(ctx).apply {
            text = rec.reason; setTextColor(Color.parseColor("#1A1A2E")); textSizeSp(12)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            maxLines = 1
        })
        recordRow.addView(TextView(ctx).apply {
            val color = if (rec.delta >= 0) "#2E7D32" else "#C62828"
            val bg2 = if (rec.delta >= 0) "#E8F5E9" else "#FFEBEE"
            text = "${if (rec.delta >= 0) "+" else ""}${rec.delta}"
            setTextColor(Color.parseColor(color)); typeface = Typeface.DEFAULT_BOLD
            textSizeSp(12); gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor(bg2))
            setPadding(ctx.dp2px(10), ctx.dp2px(3), ctx.dp2px(10), ctx.dp2px(3))
        })
        card.addView(recordRow)
    }

    if (g.records.size > 4) {
        card.addView(TextView(ctx).apply {
            text = "… 还有 ${g.records.size - 4} 条记录"
            setTextColor(Color.parseColor("#909090")); textSizeSp(11)
            gravity = Gravity.CENTER; setPadding(0, ctx.dp2px(4), 0, 0)
        })
    }
    return card
}

private fun makeMiniTag(ctx: Context, text: String, bgColor: String, fgColor: String): TextView = TextView(ctx).apply {
    this.text = text; setTextColor(Color.parseColor(fgColor)); textSizeSp(11)
    typeface = Typeface.DEFAULT_BOLD; setBackgroundColor(Color.parseColor(bgColor))
    setPadding(ctx.dp2px(8), ctx.dp2px(3), ctx.dp2px(8), ctx.dp2px(3))
}


// ============================================================================
// 六、卫生页
// ============================================================================

private fun buildHygienePage(ctx: Context): View {
    val scrollView = ScrollView(ctx).apply {
        setBackgroundColor(Color.parseColor("#F5F6FA")); isFillViewport = true
    }
    val container = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(ctx.dp2px(12), ctx.dp2px(12), ctx.dp2px(12), ctx.dp2px(12))
    }

    val header = makeCard(ctx).apply { setPadding(ctx.dp2px(16), ctx.dp2px(14), ctx.dp2px(16), ctx.dp2px(14)) }
    header.addView(TextView(ctx).apply {
        text = "🧹 卫生扣分统计"; setTextColor(Color.parseColor("#1B5E8C"))
        typeface = Typeface.DEFAULT_BOLD; textSizeSp(18)
    })
    val totalDeduct = AppData.hygieneTotalDeduct
    header.addView(TextView(ctx).apply {
        text = "共 ${AppData.hygieneTotalRecords} 条记录 · 累计扣分 $totalDeduct 分"
        setTextColor(Color.parseColor("#C62828")); textSizeSp(12)
        setPadding(0, ctx.dp2px(2), 0, 0)
    })
    container.addView(header)

    val barCard = makeCard(ctx).apply { setPadding(ctx.dp2px(12), ctx.dp2px(14), ctx.dp2px(12), ctx.dp2px(14)) }
    barCard.addView(TextView(ctx).apply {
        text = "📊 小组扣分排行（越多越差）"; setTextColor(Color.parseColor("#1A1A2E"))
        typeface = Typeface.DEFAULT_BOLD; textSizeSp(15)
        setPadding(ctx.dp2px(6), 0, ctx.dp2px(6), ctx.dp2px(10))
    })
    barCard.addView(BarChartView(ctx, AppData.hygieneTotalsByGroup()).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    })
    container.addView(barCard)

    val pieCard = makeCard(ctx).apply { setPadding(ctx.dp2px(12), ctx.dp2px(14), ctx.dp2px(12), ctx.dp2px(14)) }
    pieCard.addView(TextView(ctx).apply {
        text = "🥧 扣分理由分布"; setTextColor(Color.parseColor("#1A1A2E"))
        typeface = Typeface.DEFAULT_BOLD; textSizeSp(15)
        setPadding(ctx.dp2px(6), 0, ctx.dp2px(6), ctx.dp2px(10))
    })
    pieCard.addView(PieChartView(ctx, AppData.hygieneCountsByReason()).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    })
    container.addView(pieCard)

    scrollView.addView(container)
    return scrollView
}

// ============================================================================
// 七、BarChartView —— 纯 Canvas 横向条形图
// ============================================================================

class BarChartView(context: Context, private val data: List<Pair<String, Int>>) : View(context) {
    private val rowH = context.dp2px(48)
    private val topPad = context.dp2px(30)
    private val bottomPad = context.dp2px(16)

    init {
        // 构造阶段 layoutParams 还是 null，不能在这里赋值
        // 高度统一由 onMeasure 用 EXACTLY 强制指定
        minimumHeight = topPad + rowH * data.size + bottomPad
    }

    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1A1A2E"); textSize = context.sp2px(12)
    }
    private val dimTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#909090"); textSize = context.sp2px(11)
    }
    private val valuePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#C62828"); textSize = context.sp2px(12); typeface = Typeface.DEFAULT_BOLD
    }
    private val barPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#EF5350"); style = Paint.Style.FILL
    }
    private val axisPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#CFD8DC"); style = Paint.Style.STROKE; strokeWidth = 2f
    }
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#ECEFF1"); style = Paint.Style.STROKE; strokeWidth = 1f
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec,
            MeasureSpec.makeMeasureSpec(topPad + rowH * data.size + bottomPad, MeasureSpec.EXACTLY))
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat(); val h = height.toFloat()
        if (w <= 0f || h <= 0f || data.isEmpty()) return

        val nameCol = context.dp2px(110).toFloat()
        val rightPad = context.dp2px(56).toFloat()
        val plotL = nameCol; val plotR = w - rightPad; val plotW = plotR - plotL
        val maxVal = data.maxOfOrNull { it.second } ?: 1

        canvas.drawLine(plotL, topPad - 4f, plotL, h - bottomPad, axisPaint)
        dimTextPaint.textAlign = Paint.Align.LEFT
        canvas.drawText("0", plotL, h - bottomPad + dimTextPaint.textSize + 2f, dimTextPaint)
        canvas.drawLine(plotR, topPad - 4f, plotR, h - bottomPad, gridPaint)
        dimTextPaint.textAlign = Paint.Align.RIGHT
        canvas.drawText("$maxVal", plotR, h - bottomPad + dimTextPaint.textSize + 2f, dimTextPaint)

        val barHeight = rowH * 0.48f
        data.forEachIndexed { i, (name, value) ->
            val cy = topPad + i * rowH + rowH / 2f
            textPaint.textAlign = Paint.Align.LEFT; textPaint.isFakeBoldText = true
            val maxNameW = nameCol - context.dp2px(10)
            var displayName = name
            while (displayName.isNotEmpty() && textPaint.measureText(displayName) > maxNameW) {
                displayName = displayName.dropLast(2) + "…"
            }
            canvas.drawText(displayName, context.dp2px(8).toFloat(), cy + textPaint.textSize / 2f, textPaint)
            textPaint.isFakeBoldText = false

            val barRight = plotL + (value.toFloat() / maxVal) * plotW
            if (value > 0) {
                canvas.drawRoundRect(RectF(plotL, cy - barHeight / 2f, barRight, cy + barHeight / 2f), 6f, 6f, barPaint)
                valuePaint.textAlign = Paint.Align.LEFT
                canvas.drawText("-$value", barRight + context.dp2px(6).toFloat(), cy + valuePaint.textSize / 2f, valuePaint)
            } else {
                valuePaint.textAlign = Paint.Align.LEFT; valuePaint.color = Color.parseColor("#909090")
                canvas.drawText("0", plotL + context.dp2px(6).toFloat(), cy + valuePaint.textSize / 2f, valuePaint)
                valuePaint.color = Color.parseColor("#C62828")
            }
            if (i < data.size - 1) {
                canvas.drawLine(plotL, cy + rowH / 2f + 2f, plotR, cy + rowH / 2f + 2f, gridPaint)
            }
        }
    }
}


// ============================================================================
// 八、PieChartView —— 纯 Canvas 甜甜圈饼图 + 图例
// ============================================================================

class PieChartView(context: Context, private val data: List<Pair<String, Int>>) : View(context) {
    private val palette = intArrayOf(
        Color.parseColor("#7AB8FF"), Color.parseColor("#66BB6A"), Color.parseColor("#FFB74D"),
        Color.parseColor("#FF8A65"), Color.parseColor("#BA68C8"), Color.parseColor("#4DD0E1"),
        Color.parseColor("#F06292"), Color.parseColor("#AED581"), Color.parseColor("#FFD54F"),
        Color.parseColor("#9575CD"), Color.parseColor("#4DB6AC"), Color.parseColor("#E57373"),
    )
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1A1A2E"); textSize = context.sp2px(12)
    }
    private val valuePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#707080"); textSize = context.sp2px(11)
    }
    private val swPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }

    private val items = data.filter { it.second > 0 }
    private val total = items.sumOf { it.second }.coerceAtLeast(1)
    private val itemH = context.dp2px(26); private val swSize = context.dp2px(14)

    private val desiredHeight: Int = run {
        val pieSize = (context.resources.displayMetrics.widthPixels * 0.55f).toInt()
        context.dp2px(8) + pieSize + context.dp2px(12) + items.size * itemH + context.dp2px(8)
    }

    init { minimumHeight = desiredHeight }

    override fun onMeasure(w: Int, h: Int) {
        super.onMeasure(w, MeasureSpec.makeMeasureSpec(desiredHeight, MeasureSpec.EXACTLY))
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        if (w <= 0f || items.isEmpty()) {
            textPaint.textAlign = Paint.Align.CENTER; textPaint.color = Color.parseColor("#909090")
            canvas.drawText("暂无数据", w / 2f, height / 2f, textPaint)
            textPaint.color = Color.parseColor("#1A1A2E")
            return
        }

        val pieSize = minOf(w * 0.55f, height * 0.55f)
        val left = (w - pieSize) / 2f; val top = context.dp2px(8).toFloat()
        val oval = RectF(left, top, left + pieSize, top + pieSize)
        val centerX = w / 2f; val centerY = top + pieSize / 2f; val holeR = pieSize * 0.3f

        var currentAngle = -90f
        items.forEachIndexed { i, (_, v) ->
            paint.color = palette[i % palette.size]
            canvas.drawArc(oval, currentAngle, 360f * v / total, true, paint)
            currentAngle += 360f * v / total
        }
        paint.color = Color.parseColor("#FFFFFF")
        canvas.drawCircle(centerX, centerY, holeR, paint)

        textPaint.textAlign = Paint.Align.CENTER; textPaint.color = Color.parseColor("#1A1A2E")
        textPaint.typeface = Typeface.DEFAULT_BOLD; textPaint.textSize = context.sp2px(16)
        canvas.drawText("$total", centerX, centerY - context.dp2px(2).toFloat() + textPaint.textSize / 2f, textPaint)
        textPaint.typeface = Typeface.DEFAULT; textPaint.textSize = context.sp2px(11)
        textPaint.color = Color.parseColor("#707080")
        canvas.drawText("条记录", centerX, centerY + context.dp2px(14).toFloat() + textPaint.textSize / 2f, textPaint)

        val legendTop = top + pieSize + context.dp2px(12).toFloat()
        val maxLabelW = w - context.dp2px(24).toFloat() - swSize - context.dp2px(88).toFloat()

        textPaint.textAlign = Paint.Align.LEFT
        items.forEachIndexed { i, (label, value) ->
            val cy = legendTop + i * itemH + itemH / 2f
            swPaint.color = palette[i % palette.size]
            val swLeft = context.dp2px(12).toFloat(); val swTopY = cy - swSize / 2f
            canvas.drawRect(swLeft, swTopY, swLeft + swSize, swTopY + swSize, swPaint)

            var displayLabel = label; textPaint.textSize = context.sp2px(12)
            while (displayLabel.isNotEmpty() && textPaint.measureText(displayLabel) > maxLabelW) {
                displayLabel = displayLabel.dropLast(2) + "…"
            }
            textPaint.color = Color.parseColor("#1A1A2E")
            canvas.drawText(displayLabel, swLeft + swSize + context.dp2px(8).toFloat(),
                cy + textPaint.textSize / 2f, textPaint)

            val pct = "%.1f%%".format(100.0 * value / total)
            val rightX = w - context.dp2px(12).toFloat()
            textPaint.textAlign = Paint.Align.RIGHT
            textPaint.typeface = Typeface.DEFAULT_BOLD; textPaint.textSize = context.sp2px(12)
            canvas.drawText(pct, rightX, cy + textPaint.textSize / 2f, textPaint)
            textPaint.typeface = Typeface.DEFAULT; valuePaint.textAlign = Paint.Align.RIGHT
            valuePaint.textSize = context.sp2px(11)
            canvas.drawText("($value 次)",
                rightX - textPaint.measureText(pct) - context.dp2px(6).toFloat(),
                cy + valuePaint.textSize / 2f, valuePaint)
            textPaint.textAlign = Paint.Align.LEFT
        }
    }
}