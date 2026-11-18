package com.example.timetable

import android.app.Activity
import android.app.AlertDialog
import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.net.Uri
import android.provider.DocumentsContract
import android.view.View
import android.widget.Toast
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

// ============================================================================
// 九、导出：把手机端已收到的快照写成 CSV / PNG / SVG
// ============================================================================

internal const val EXPORT_SCORES = 0
internal const val EXPORT_HYGIENE = 1
internal const val EXPORT_SCHEDULE = 2
internal const val EXPORT_STUDENTS = 3
internal const val EXPORT_CHARTS = 4

private const val CHART_PNG = 0
private const val CHART_SVG = 1
private const val CHART_BOTH = 2

internal class ExportPlan(val contents: BooleanArray, val chartFormat: Int)

internal var pendingExportPlan: ExportPlan? = null

/** 进入导出流程：先选内容，再选图表格式，最后用系统文件选择器选目录。 */
internal fun startExportFlow(activity: Activity) {
    if (AppData.students.isEmpty() && AppData.groupScores.isEmpty() &&
        AppData.hygieneRecords.isEmpty()
    ) {
        Toast.makeText(activity, "还没有收到电脑端数据，请先连接", Toast.LENGTH_SHORT).show()
        return
    }

    val items = arrayOf("积分记录", "卫生记录", "课程表", "学生名单", "数据图表")
    val checked = booleanArrayOf(true, true, true, true, true)

    AlertDialog.Builder(activity)
        .setTitle("导出数据")
        .setMultiChoiceItems(items, checked, null)
        .setPositiveButton("下一步") { _, _ ->
            if (checked.none { it }) {
                Toast.makeText(activity, "请至少选择一项内容", Toast.LENGTH_SHORT).show()
                return@setPositiveButton
            }
            if (checked[EXPORT_CHARTS]) askChartFormat(activity, checked)
            else startPickDirectory(activity, ExportPlan(checked.copyOf(), CHART_PNG))
        }
        .setNegativeButton("取消", null)
        .show()
}

private fun askChartFormat(activity: Activity, checked: BooleanArray) {
    val names = arrayOf("PNG 图片", "SVG 矢量图", "PNG + SVG")
    var choice = 0
    AlertDialog.Builder(activity)
        .setTitle("图表格式")
        .setSingleChoiceItems(names, 0) { _, which -> choice = which }
        .setPositiveButton("选择保存位置") { _, _ ->
            startPickDirectory(activity, ExportPlan(checked.copyOf(), choice))
        }
        .setNegativeButton("取消", null)
        .show()
}

private fun startPickDirectory(activity: Activity, plan: ExportPlan) {
    pendingExportPlan = plan
    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
        addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )
    }
    activity.startActivityForResult(intent, MainActivity.REQ_EXPORT_DIR)
}

/** 目录选定后调用：在后台线程生成并写入文件。 */
internal fun runExport(activity: Activity, treeUri: Uri) {
    val plan = pendingExportPlan ?: return
    pendingExportPlan = null

    // 在 UI 线程拍一份快照，避免导出过程中数据被推送刷新
    val snap = ExportSnapshot(
        className = AppData.className,
        students = AppData.students.toList(),
        groups = AppData.groupScores.toList(),
        hygiene = AppData.hygieneRecords.toList(),
        schedule = AppData.schedule.toList(),
        periods = AppData.periods.toList(),
        extraSlots = AppData.extraSlots.toList(),
        hygieneByGroup = AppData.hygieneTotalsByGroup(),
        hygieneByReason = AppData.hygieneCountsByReason(),
        scoreByReason = AppData.scoreCountsByReason()
    )
    val appContext = activity.applicationContext
    Toast.makeText(activity, "正在导出…", Toast.LENGTH_SHORT).show()

    Thread {
        var ok = 0
        var fail = 0
        try {
            val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.CHINA).format(Date())
            val resolver = appContext.contentResolver
            val dir = pickDir(resolver, treeUri, "课程表导出_$stamp")
            if (dir == null) {
                fail = 1
            } else {
                fun put(name: String, mime: String, bytes: ByteArray) {
                    if (writeDocument(resolver, dir, name, mime, bytes)) ok++ else fail++
                }

                val prefix = safeName(snap.className) + "_" + stamp
                if (plan.contents[EXPORT_SCORES]) {
                    put("${prefix}_积分记录.csv", "text/csv", csvBytes(scoreRows(snap)))
                }
                if (plan.contents[EXPORT_HYGIENE]) {
                    put("${prefix}_卫生记录.csv", "text/csv", csvBytes(hygieneRows(snap)))
                }
                if (plan.contents[EXPORT_SCHEDULE]) {
                    put("${prefix}_课程表.csv", "text/csv", csvBytes(scheduleRows(snap)))
                }
                if (plan.contents[EXPORT_STUDENTS]) {
                    put("${prefix}_学生名单.csv", "text/csv", csvBytes(studentRows(snap)))
                }
                if (plan.contents[EXPORT_CHARTS]) {
                    val wantPng = plan.chartFormat != CHART_SVG
                    val wantSvg = plan.chartFormat != CHART_PNG
                    val charts = listOf(
                        ChartJob("小组积分排行", snap.groups.map { it.name to it.total }, negative = false),
                        ChartJob("小组卫生扣分排行", snap.hygieneByGroup, negative = true),
                        ChartJob("卫生扣分理由分布", snap.hygieneByReason.take(8), negative = true),
                        ChartJob("积分理由分布", snap.scoreByReason, negative = false)
                    )
                    charts.forEach { job ->
                        if (job.data.isEmpty() || job.data.all { it.second == 0 }) return@forEach
                        if (wantPng) {
                            put("${prefix}_${job.title}.png", "image/png", chartPng(appContext, job))
                        }
                        if (wantSvg) {
                            put("${prefix}_${job.title}.svg", "image/svg+xml",
                                svgChart(job).toByteArray(Charsets.UTF_8))
                        }
                    }
                }
            }
        } catch (t: Throwable) {
            fail++
        }

        val msg = when {
            fail == 0 -> "已导出 $ok 个文件"
            ok == 0 -> "导出失败，请换一个目录重试"
            else -> "导出完成：成功 $ok 个，失败 $fail 个"
        }
        activity.runOnUiThread {
            if (!activity.isFinishing && !activity.isDestroyed) {
                Toast.makeText(activity, msg, Toast.LENGTH_LONG).show()
            }
        }
    }.start()
}

// ===================== 快照与文件写入 =====================
private class ExportSnapshot(
    val className: String,
    val students: List<StudentRow>,
    val groups: List<GroupScore>,
    val hygiene: List<HygieneRecord>,
    val schedule: List<CourseCell>,
    val periods: List<Period>,
    val extraSlots: List<Period>,
    val hygieneByGroup: List<Pair<String, Int>>,
    val hygieneByReason: List<Pair<String, Int>>,
    val scoreByReason: List<Pair<String, Int>>
)

private fun pickDir(resolver: ContentResolver, treeUri: Uri, name: String): Uri? {
    val root = try {
        DocumentsContract.buildDocumentUriUsingTree(
            treeUri, DocumentsContract.getTreeDocumentId(treeUri))
    } catch (t: Throwable) {
        return null
    }
    return try {
        DocumentsContract.createDocument(
            resolver, root, DocumentsContract.Document.MIME_TYPE_DIR, name) ?: root
    } catch (t: Throwable) {
        root
    }
}

private fun writeDocument(
    resolver: ContentResolver, dir: Uri, name: String, mime: String, bytes: ByteArray
): Boolean {
    return try {
        val file = DocumentsContract.createDocument(resolver, dir, mime, name) ?: return false
        resolver.openOutputStream(file)?.use { it.write(bytes) } ?: return false
        true
    } catch (t: Throwable) {
        false
    }
}

// ===================== CSV =====================
private fun scoreRows(s: ExportSnapshot): List<List<String>> {
    val rows = mutableListOf(listOf("小组", "学生", "时间", "理由", "分值"))
    s.groups.forEach { g ->
        g.records.forEach { r ->
            rows.add(listOf(g.name, r.member, r.time, r.reason,
                if (r.delta >= 0) "+${r.delta}" else "${r.delta}"))
        }
    }
    return rows
}

private fun hygieneRows(s: ExportSnapshot): List<List<String>> {
    val rows = mutableListOf(listOf("小组", "学生", "时间", "理由", "扣分", "记录人"))
    s.hygiene.forEach { r ->
        rows.add(listOf(r.group, r.member, r.time, r.reason,
            "-${r.score}", r.by.ifBlank { "未记录" }))
    }
    return rows
}

private fun scheduleRows(s: ExportSnapshot): List<List<String>> {
    val rows = mutableListOf(listOf("星期", "节次", "科目"))
    for (day in 0 until 5) {
        val dayName = AppData.weekDayNames.getOrElse(day) { "周${day + 1}" }
        s.periods.forEach { p ->
            val subject = s.schedule.firstOrNull {
                it.dayIndex == day && it.periodId == p.id
            }?.subject ?: ""
            rows.add(listOf(dayName, p.name, subject))
        }
        s.extraSlots.forEach { p ->
            val subject = s.schedule.firstOrNull {
                it.dayIndex == day && it.periodId == p.id
            }?.subject ?: ""
            rows.add(listOf(dayName, p.name, subject))
        }
    }
    return rows
}

private fun studentRows(s: ExportSnapshot): List<List<String>> {
    val rows = mutableListOf(listOf("学号", "姓名", "小组", "积分"))
    s.students.forEach { rows.add(listOf(it.sid, it.name, it.group, it.total.toString())) }
    return rows
}

private fun csvEscape(value: String): String {
    val text = value.replace("\"", "\"\"")
    return if (text.contains(',') || text.contains('"') ||
        text.contains('\n') || text.contains('\r')) "\"$text\"" else text
}

private fun csvBytes(rows: List<List<String>>): ByteArray {
    val sb = StringBuilder("\ufeff") // BOM：让 Excel 正确识别 UTF-8 中文
    rows.forEach { row ->
        sb.append(row.joinToString(",") { csvEscape(it) }).append("\r\n")
    }
    return sb.toString().toByteArray(Charsets.UTF_8)
}

private fun safeName(text: String): String =
    text.replace(Regex("[\\\\/:*?\"<>|\\s]+"), "_").trim('_').ifBlank { "班级" }

// ===================== 图表 PNG =====================
private class ChartJob(
    val title: String, val data: List<Pair<String, Int>>, val negative: Boolean
)

private fun chartPng(ctx: Context, job: ChartJob): ByteArray {
    val widthPx = 1080
    val pad = ctx.dp2px(14)
    val contentW = widthPx - pad * 2

    val chart: View = if (job.title.contains("理由分布")) {
        PieChartView(ctx, job.data)
    } else {
        BarChartView(ctx, job.data, job.negative)
    }
    chart.measure(
        View.MeasureSpec.makeMeasureSpec(contentW, View.MeasureSpec.EXACTLY),
        View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
    )
    chart.layout(0, 0, chart.measuredWidth, chart.measuredHeight)

    val titleH = ctx.dp2px(40)
    val bmp = Bitmap.createBitmap(
        widthPx, pad + titleH + chart.measuredHeight + pad, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bmp)
    canvas.drawColor(Color.WHITE)

    val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1A1A2E")
        textSize = ctx.sp2px(18)
        typeface = Typeface.DEFAULT_BOLD
    }
    canvas.drawText(job.title, pad.toFloat(), pad + titlePaint.textSize, titlePaint)
    canvas.translate(pad.toFloat(), (pad + titleH).toFloat())
    chart.draw(canvas)

    return ByteArrayOutputStream().use { out ->
        bmp.compress(Bitmap.CompressFormat.PNG, 100, out)
        out.toByteArray()
    }
}

// ===================== 图表 SVG =====================
private val SVG_PALETTE = arrayOf(
    "#7AB8FF", "#66BB6A", "#FFB74D", "#FF8A65", "#BA68C8", "#4DD0E1",
    "#F06292", "#AED581", "#FFD54F", "#9575CD", "#4DB6AC", "#E57373"
)

private fun svgChart(job: ChartJob): String =
    if (job.title.contains("理由分布")) svgPie(job.title, job.data)
    else svgBar(job.title, job.data, job.negative)

private fun svgBar(title: String, data: List<Pair<String, Int>>, negative: Boolean): String {
    val width = 760
    val pad = 24
    val titleH = 46
    val rowH = 46
    val labelW = 180
    val valueW = 80
    val plotL = pad + labelW
    val plotR = width - pad - valueW
    val plotW = plotR - plotL
    val height = pad + titleH + data.size * rowH + 44

    val values = data.map { it.second }
    val minV = if (negative) 0 else minOf(0, values.minOrNull() ?: 0)
    val maxV = if (negative) (values.maxOrNull() ?: 1).coerceAtLeast(1)
               else (values.maxOrNull() ?: 0).coerceAtLeast(1)
    val span = (maxV - minV).coerceAtLeast(1)
    val zeroX = plotL + (0 - minV).toDouble() / span * plotW

    val sb = StringBuilder()
    sb.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
    sb.append("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"$width\" height=\"$height\" ")
    sb.append("viewBox=\"0 0 $width $height\">\n")
    sb.append("<rect width=\"$width\" height=\"$height\" fill=\"#FFFFFF\"/>\n")
    sb.append("<text x=\"$pad\" y=\"${pad + 24}\" font-family=\"Microsoft YaHei,sans-serif\" ")
    sb.append("font-size=\"20\" font-weight=\"bold\" fill=\"#1A1A2E\">${xml(title)}</text>\n")
    sb.append("<line x1=\"${fmt(zeroX)}\" y1=\"${pad + titleH}\" x2=\"${fmt(zeroX)}\" ")
    sb.append("y2=\"${height - 34}\" stroke=\"#90A4AE\" stroke-width=\"2\"/>\n")

    data.forEachIndexed { i, (name, value) ->
        val cy = pad + titleH + i * rowH + rowH / 2
        sb.append("<text x=\"$pad\" y=\"${cy + 5}\" font-family=\"Microsoft YaHei,sans-serif\" ")
        sb.append("font-size=\"14\" fill=\"#1A1A2E\">${xml(name)}</text>\n")

        val barEnd = plotL + (value - minV).toDouble() / span * plotW
        val left = min(zeroX, barEnd)
        val barW = abs(barEnd - zeroX)
        val color = if (negative || value < 0) "#EF5350" else "#66BB6A"
        if (value != 0) {
            sb.append("<rect x=\"${fmt(left)}\" y=\"${cy - 14}\" width=\"${fmt(barW)}\" ")
            sb.append("height=\"28\" rx=\"6\" fill=\"$color\"/>\n")
        }

        val label = when {
            value == 0 -> "0"
            negative -> "-$value"
            value > 0 -> "+$value"
            else -> "$value"
        }
        val labelColor = when {
            value == 0 -> "#909090"
            negative -> "#C62828"
            value > 0 -> "#2E7D32"
            else -> "#C62828"
        }
        val labelX = if (value < 0) left - 6 else min(zeroX, barEnd) + barW + 6
        val anchor = if (value < 0) "end" else "start"
        sb.append("<text x=\"${fmt(labelX)}\" y=\"${cy + 5}\" font-family=\"Microsoft YaHei,sans-serif\" ")
        sb.append("font-size=\"14\" font-weight=\"bold\" fill=\"$labelColor\" ")
        sb.append("text-anchor=\"$anchor\">$label</text>\n")
    }

    sb.append("</svg>\n")
    return sb.toString()
}

private fun svgPie(title: String, data: List<Pair<String, Int>>): String {
    val width = 760
    val pad = 24
    val titleH = 56
    val radius = 150.0
    val cx = width / 2.0
    val cy = pad + titleH + radius
    val rowH = 30
    val height = (cy + radius + 30 + data.size * rowH + pad).toInt()

    val items = data.filter { it.second > 0 }
    val total = items.sumOf { it.second }.coerceAtLeast(1)

    val sb = StringBuilder()
    sb.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
    sb.append("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"$width\" height=\"$height\" ")
    sb.append("viewBox=\"0 0 $width $height\">\n")
    sb.append("<rect width=\"$width\" height=\"$height\" fill=\"#FFFFFF\"/>\n")
    sb.append("<text x=\"$pad\" y=\"${pad + 24}\" font-family=\"Microsoft YaHei,sans-serif\" ")
    sb.append("font-size=\"20\" font-weight=\"bold\" fill=\"#1A1A2E\">${xml(title)}</text>\n")

    var angle = -90.0
    items.forEachIndexed { i, (_, value) ->
        val sweep = 360.0 * value / total
        val x1 = cx + radius * cos(Math.toRadians(angle))
        val y1 = cy + radius * sin(Math.toRadians(angle))
        val x2 = cx + radius * cos(Math.toRadians(angle + sweep))
        val y2 = cy + radius * sin(Math.toRadians(angle + sweep))
        val large = if (sweep > 180) 1 else 0
        sb.append("<path d=\"M ${fmt(cx)} ${fmt(cy)} L ${fmt(x1)} ${fmt(y1)} ")
        sb.append("A ${fmt(radius)} ${fmt(radius)} 0 $large 1 ${fmt(x2)} ${fmt(y2)} Z\" ")
        sb.append("fill=\"${SVG_PALETTE[i % SVG_PALETTE.size]}\" stroke=\"#FFFFFF\" stroke-width=\"2\"/>\n")
        angle += sweep
    }

    val legendTop = cy + radius + 30
    items.forEachIndexed { i, (label, value) ->
        val y = legendTop + i * rowH
        val pct = "%.1f%%".format(Locale.US, 100.0 * value / total)
        sb.append("<rect x=\"$pad\" y=\"${y - 12}\" width=\"16\" height=\"16\" ")
        sb.append("fill=\"${SVG_PALETTE[i % SVG_PALETTE.size]}\"/>\n")
        sb.append("<text x=\"${pad + 26}\" y=\"${y + 2}\" font-family=\"Microsoft YaHei,sans-serif\" ")
        sb.append("font-size=\"14\" fill=\"#1A1A2E\">${xml(label)}</text>\n")
        sb.append("<text x=\"${width - pad}\" y=\"${y + 2}\" font-family=\"Microsoft YaHei,sans-serif\" ")
        sb.append("font-size=\"14\" fill=\"#707080\" text-anchor=\"end\">$pct（$value 次）</text>\n")
    }

    sb.append("</svg>\n")
    return sb.toString()
}

private fun fmt(value: Double): String = "%.1f".format(Locale.US, value)

private fun xml(text: String): String = text
    .replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace("\"", "&quot;")
