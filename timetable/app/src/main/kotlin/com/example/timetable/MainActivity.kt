package com.example.timetable

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
import android.content.Intent        // 新增：导出时选择保存目录
import android.util.Log              // 新增
import android.widget.EditText       // 新增
import android.widget.Toast          // 新增
import androidx.core.view.ViewCompat          // 新增：系统栏内边距
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import org.json.JSONArray            // 新增：解析局域网 JSON
import org.json.JSONObject
import java.io.File                  // 新增
import java.net.HttpURLConnection     // 新增：SSE 长连接
import java.net.URL
import kotlin.math.min

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
    private lateinit var topBar: LinearLayout
    private var currentTab = 0
    private var approvalWatcher: ApprovalWatcher? = null

    private val uiHandler = Handler(Looper.getMainLooper())
    private var pendingSnapshot: JSONObject? = null
    private val renderPending = Runnable {
        pendingSnapshot?.let { renderSnapshot(it) }
    }

    private val prefs by lazy { getSharedPreferences("lan_config", MODE_PRIVATE) }
    private val client = LanClient(
        onSnapshot = { json -> runOnUiThread { applySnapshot(json) } },
        onStatus = { text, ok -> runOnUiThread { updateStatus(text, ok) } }
    )

    companion object {
        private const val KEY_URL = "server_url"
        internal const val REQ_EXPORT_DIR = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestWindowFeature(android.view.Window.FEATURE_NO_TITLE)
        // targetSdk 36 在 Android 15+ 默认 edge-to-edge，需自行处理系统栏内边距
        WindowCompat.setDecorFitsSystemWindows(window, false)
        try {
            val root = buildRoot()
            setContentView(root)
            applyWindowInsets(root)
        } catch (t: Throwable) {
            showCrash(t)
        }
    }

    /** 系统栏内边距：内容不再被状态栏/导航栏遮挡（targetSdk 36 强制 edge-to-edge）。 */
    private fun applyWindowInsets(root: View) {
        // 状态栏压在蓝色标题栏上 → 用白色图标；导航栏压在浅色页面上 → 用深色图标
        WindowInsetsControllerCompat(window, root).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = true
        }
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or
                        WindowInsetsCompat.Type.displayCutout()
            )
            // 左右/底部留给页面，顶部让蓝色标题栏延伸到状态栏后面
            view.updatePadding(left = bars.left, right = bars.right, bottom = bars.bottom)
            topBar.updatePadding(top = dp2px(14) + bars.top)
            insets
        }
        ViewCompat.requestApplyInsets(root)
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
        approvalWatcher?.stop()
        approvalWatcher = null
        uiHandler.removeCallbacks(renderPending)
        super.onStop()
    }

    override fun onDestroy() {
        client.stop()
        approvalWatcher?.stop()
        approvalWatcher = null
        uiHandler.removeCallbacks(renderPending)
        super.onDestroy()
    }

    // 收到电脑端推送：200ms 防抖，避免连点加分导致界面狂闪
    private fun applySnapshot(json: JSONObject) {
        if (!::pageContainer.isInitialized) return
        pendingSnapshot = json
        uiHandler.removeCallbacks(renderPending)
        uiHandler.postDelayed(renderPending, 200)
    }

    private fun renderSnapshot(json: JSONObject) {
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
        startApprovalWatcher(url)
    }

    // 轮询电脑端“待手机确认”的重置请求
    private fun startApprovalWatcher(base: String) {
        approvalWatcher?.stop()
        approvalWatcher = ApprovalWatcher(base) { id, title, detail ->
            runOnUiThread { askApproval(id, title, detail) }
        }.also { it.start() }
    }

    private fun askApproval(id: String, title: String, detail: String) {
        if (isFinishing) return
        val text = (if (title.isBlank()) "电脑端请求重置一个密钥" else title) +
                (if (detail.isBlank()) "" else "\n\n" + detail) +
                "\n\n只有你本人确认时才点击「同意」。"
        try {
            AlertDialog.Builder(this)
                .setTitle("电脑端请求确认")
                .setMessage(text)
                .setPositiveButton("同意") { _, _ ->
                    approvalWatcher?.postDecision(id, true)
                }
                .setNegativeButton("拒绝") { _, _ ->
                    approvalWatcher?.postDecision(id, false)
                }
                .setCancelable(false)
                .show()
        } catch (_: Throwable) {
        }
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

        topBar = LinearLayout(ctx).apply {
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
        topBar.addView(TextView(ctx).apply {
            text = "⇩ 导出"; setTextColor(Color.WHITE); textSizeSp(13)
            setPadding(ctx.dp2px(10), 0, 0, 0)
            setOnClickListener { startExportFlow(this@MainActivity) }
        })
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

    // 导出：系统文件选择器返回目标目录
    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_EXPORT_DIR && resultCode == Activity.RESULT_OK) {
            val uri = data?.data ?: return
            try {
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
            } catch (_: Throwable) {
            }
            runExport(this, uri)
        }
    }
}
