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

    private val uiHandler = Handler(Looper.getMainLooper())
    private var pendingSnapshot: JSONObject? = null
    private val renderPending = Runnable {
        pendingSnapshot?.let { renderSnapshot(it) }
    }

    private val prefs by lazy { getSharedPreferences("lan_config", MODE_PRIVATE) }
    private val manager by lazy {
        ConnectionManager(
            this,
            onSnapshot = { json -> runOnUiThread { applySnapshot(json) } },
            onStatus = { text, ok -> runOnUiThread { updateStatus(text, ok) } },
            onApproval = { id, title, detail ->
                runOnUiThread { askApproval(id, title, detail) }
            },
            onBindRequest = { item -> runOnUiThread { askBindRequest(item) } },
        )
    }

    companion object {
        private const val KEY_URL = "server_url"
        internal const val REQ_EXPORT_DIR = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        RelayLog.init(filesDir)
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
        manager.start()
    }

    override fun onStop() {
        manager.stop()
        uiHandler.removeCallbacks(renderPending)
        super.onStop()
    }

    override fun onDestroy() {
        manager.stop()
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
        val via = manager.modeLabel
        updateStatus(
            "已连接 · ${AppData.className}" + if (via.isEmpty()) "" else " · $via",
            true
        )
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
                    manager.postDecision(id, true)
                }
                .setNegativeButton("拒绝") { _, _ ->
                    manager.postDecision(id, false)
                }
                .setCancelable(false)
                .show()
        } catch (_: Throwable) {
        }
    }

    /** 电脑端发起绑定：手机上点「同意」后才生效，并切换为只订阅这台电脑。 */
    private fun askBindRequest(item: org.json.JSONObject) {
        if (isFinishing) return
        val pcId = item.optString("pcId")
        val rid = item.optString("requestId")
        if (pcId.isBlank() || rid.isBlank()) return
        val pcName = item.optString("pcName").ifBlank { pcId.take(8) }
        try {
            AlertDialog.Builder(this)
                .setTitle("电脑请求绑定")
                .setMessage("「$pcName」想把本机设为确认设备。\n\n" +
                        "同意后会取消订阅其他电脑，只同步这一台。")
                .setPositiveButton("同意") { _, _ -> decideBind(item, true) }
                .setNegativeButton("拒绝") { _, _ -> decideBind(item, false) }
                .setCancelable(false)
                .show()
        } catch (_: Throwable) {
        }
    }

    private fun decideBind(item: org.json.JSONObject, approve: Boolean) {
        val rid = item.optString("requestId")
        Thread({
            try {
                val res = ApiClient.decide(this, rid, approve)
                runOnUiThread {
                    if (approve && res.optString("status") == "approved") {
                        ApiStore.upsertPc(this, BoundPc(
                            res.optString("pcId"),
                            res.optString("pcName"),
                            res.optString("pcPub"),
                        ))
                        ApiStore.setActive(this, res.optString("pcId"))
                        manager.restart()
                        Toast.makeText(this, "已绑定，开始同步", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(this, "已拒绝该电脑的绑定", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "绑定结果上报失败：${e.message}",
                        Toast.LENGTH_LONG).show()
                }
            }
        }, "api-bind-decide").apply { isDaemon = true; start() }
    }

    private var lastErrorText = ""

    private fun updateStatus(text: String, ok: Boolean) {
        if (!::statusLabel.isInitialized) return
        statusLabel.text = text
        statusLabel.setTextColor(
            Color.parseColor(if (ok) "#B9F6CA" else "#FFE0B2")
        )
        // 云同步报错时弹一次详情，避免状态栏截断后看不到原因
        if (!ok && text.startsWith("云同步异常") && text != lastErrorText) {
            lastErrorText = text
            showSyncError(text)
        }
    }

    private fun showSyncError(message: String) {
        if (isFinishing) return
        val tail = RelayLog.read().lines().filter { it.isNotBlank() }
            .takeLast(8).joinToString("\n")
        try {
            AlertDialog.Builder(this)
                .setTitle("云同步失败")
                .setMessage(message + "\n\n最近日志：\n" + tail)
                .setPositiveButton("知道了", null)
                .setNeutralButton("完整日志") { _, _ -> showRelayLog() }
                .show()
        } catch (_: Throwable) {
        }
    }

    // 连接设置：电脑地址（可选）+ Gitee 云同步
    private fun showSettingsDialog() {
        val cfg = manager.cloudConfig()
        val pad = dp2px(16)

        fun field(hintText: String, value: String): EditText = EditText(this).apply {
            hint = hintText
            setText(value)
            setSingleLine()
            setTextColor(Color.parseColor("#1A1A2E"))
            setPadding(pad, dp2px(6), pad, dp2px(6))
        }

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, dp2px(8), pad, 0)
        }
        val eLan = field("电脑地址（可留空）http://192.168.1.23:8765", manager.lanUrl())
        val eRepo = field("Gitee 仓库 用户名/仓库名", "${cfg.owner}/${cfg.repo}")
        val eBranch = field("分支", cfg.branch)
        val eToken = field("Gitee 访问令牌", cfg.token)
        listOf(eLan, eRepo, eBranch, eToken).forEach { layout.addView(it) }
        layout.addView(TextView(this).apply {
            text = "优先尝试局域网直连，探测 1.2 秒不通就自动走云同步。\n" +
                    "官网云端（推荐）：先点下面「云端绑定」，用电脑端的设备 ID 发起申请，\n" +
                    "电脑会弹窗确认；Gitee 令牌留空即可，配了则作为后端不可达时的备用通道。"
            setTextColor(Color.parseColor("#707080"))
            textSizeSp(11)
            setPadding(pad, dp2px(8), pad, 0)
        })
        layout.addView(Button(this).apply {
            text = "📱 云端绑定（官网后端）"
            isAllCaps = false
            setOnClickListener { showBindingDialog() }
        })

        AlertDialog.Builder(this)
            .setTitle("连接设置")
            .setView(layout)
            .setPositiveButton("保存并连接") { _, _ ->
                val lan = normalizeUrl(eLan.text.toString())
                val repoRaw = eRepo.text.toString().trim().trim('/')
                if (repoRaw.isNotBlank() && !repoRaw.contains("/")) {
                    Toast.makeText(this, "仓库要填成 用户名/仓库名", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                val cloud = CloudConfig(
                    owner = repoRaw.substringBefore("/", ""),
                    repo = repoRaw.substringAfter("/", ""),
                    branch = eBranch.text.toString().trim().ifEmpty { "master" },
                    token = eToken.text.toString().trim(),
                )
                manager.saveConfig(lan, cloud)
                manager.restart()
                updateStatus("连接中…", false)
            }
            .setNegativeButton("取消", null)
            .setNeutralButton("同步日志") { _, _ -> showRelayLog() }
            .show()
    }

    /** 云端绑定：显示本机设备 ID，由电脑端输入并发起，本机弹窗确认。 */
    private fun showBindingDialog() {
        val pad = dp2px(16)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, dp2px(8), pad, 0)
        }

        fun tip(text: String, color: String = "#707080", size: Int = 11) =
            TextView(this).apply {
                this.text = text
                setTextColor(Color.parseColor(color))
                textSizeSp(size)
                setPadding(pad, dp2px(6), pad, dp2px(2))
            }

        val eBase = EditText(this).apply {
            hint = "服务器地址"
            setText(ApiStore.base(this@MainActivity))
            setSingleLine()
            setTextColor(Color.parseColor("#1A1A2E"))
            setPadding(pad, dp2px(6), pad, dp2px(6))
        }
        val idView = TextView(this).apply {
            val id = ApiStore.deviceId(this@MainActivity)
            text = if (id.isBlank()) "正在注册…" else id
            setTextColor(Color.parseColor("#1A1A2E"))
            textSizeSp(13)
            setTextIsSelectable(true)
            setPadding(pad, dp2px(6), pad, dp2px(6))
        }
        val progress = tip("", "#1B5E8C", 12)
        val pcBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        if (ApiStore.deviceId(this).isBlank()) {
            // 打开设置时顺手把设备注册上，省得用户等
            Thread({
                try {
                    ApiClient.inbox(this)
                    runOnUiThread { idView.text = ApiStore.deviceId(this) }
                } catch (_: Exception) {
                    runOnUiThread { idView.text = "注册失败，请检查网络后重开设置" }
                }
            }, "api-register").apply { isDaemon = true; start() }
        }

        fun renderPcs() {
            pcBox.removeAllViews()
            val pcs = ApiStore.pcs(this)
            if (pcs.isEmpty()) {
                pcBox.addView(tip("还没有绑定任何电脑"))
                return
            }
            pcBox.addView(tip("已绑定电脑（点一下切换）"))
            val active = ApiStore.activeId(this)
            pcs.forEach { pc ->
                val label = pc.name.ifBlank { pc.id.take(8) }
                pcBox.addView(Button(this).apply {
                    text = if (pc.id == active) "✓ $label" else label
                    isAllCaps = false
                    textSizeSp(13)
                    setOnClickListener {
                        ApiStore.setActive(this@MainActivity, pc.id)
                        manager.restart()
                        renderPcs()
                        progress.text = "已切换到「$label」"
                    }
                })
            }
        }

        layout.addView(tip("服务器地址"))
        layout.addView(eBase)
        layout.addView(tip("本机设备 ID（在电脑端「设置 → 手机绑定」输入它发起绑定）"))
        layout.addView(idView)
        layout.addView(Button(this).apply {
            text = "复制设备 ID"
            isAllCaps = false
            setOnClickListener {
                val id = ApiStore.deviceId(this@MainActivity)
                if (id.isBlank()) {
                    progress.text = "还没有注册成功，请检查网络"
                    return@setOnClickListener
                }
                val cm = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
                cm.setPrimaryClip(android.content.ClipData.newPlainText("deviceId", id))
                progress.text = "已复制，去电脑端粘贴即可"
            }
        })
        layout.addView(Button(this).apply {
            text = "保存服务器地址"
            isAllCaps = false
            setOnClickListener {
                ApiStore.setBase(
                    this@MainActivity,
                    eBase.text.toString().trim().trimEnd('/')
                        .ifBlank { ApiStore.DEFAULT_BASE })
                progress.text = "服务器地址已保存"
                manager.restart()
            }
        })
        layout.addView(progress)
        layout.addView(pcBox)

        renderPcs()
        AlertDialog.Builder(this)
            .setTitle("云端绑定")
            .setView(ScrollView(this).apply { addView(layout) })
            .setPositiveButton("关闭", null)
            .setNeutralButton("解绑当前") { _, _ ->
                val id = ApiStore.activeId(this)
                if (id.isNotBlank()) {
                    ApiStore.removePc(this, id)
                    manager.restart()
                    Toast.makeText(this, "已解绑", Toast.LENGTH_SHORT).show()
                }
            }
            .show()
    }

    /** 云同步诊断日志：只读展示，方便排查“写入失败”这类问题。 */
    private fun showRelayLog() {
        val tv = TextView(this).apply {
            text = RelayLog.read()
            textSizeSp(10)
            setTextIsSelectable(true)
            setTextColor(Color.parseColor("#1A1A2E"))
            setPadding(dp2px(12), dp2px(8), dp2px(12), dp2px(8))
        }
        val scroll = ScrollView(this).apply { addView(tv) }
        AlertDialog.Builder(this)
            .setTitle("云同步日志")
            .setView(scroll)
            .setPositiveButton("关闭", null)
            .setNeutralButton("清空") { _, _ -> RelayLog.clear() }
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
            setOnClickListener { showSettingsDialog() }
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
