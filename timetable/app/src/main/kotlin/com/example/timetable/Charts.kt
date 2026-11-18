package com.example.timetable

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.view.View

// ============================================================================
// 七、BarChartView —— 纯 Canvas 横向条形图
// ============================================================================

/**
 * 横向条形图。
 * [negative] = true 时按“扣分”语义绘制（红色、显示 -N）；
 * = false 时用于积分，正分为绿色、负分为红色，并以 0 为基线双向展开。
 */
class BarChartView(
    context: Context,
    private val data: List<Pair<String, Int>>,
    private val negative: Boolean = true
) : View(context) {
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

        val values = data.map { it.second }
        val minVal = if (negative) 0 else minOf(0, values.minOrNull() ?: 0)
        val maxVal = if (negative) (values.maxOrNull() ?: 1).coerceAtLeast(1)
                     else (values.maxOrNull() ?: 0).coerceAtLeast(1)
        val span = (maxVal - minVal).coerceAtLeast(1)
        val zeroX = plotL + (0 - minVal).toFloat() / span * plotW

        // 0 轴与刻度
        canvas.drawLine(zeroX, topPad - 4f, zeroX, h - bottomPad, axisPaint)
        canvas.drawLine(plotR, topPad - 4f, plotR, h - bottomPad, gridPaint)
        val tickY = h - bottomPad + dimTextPaint.textSize + 2f
        dimTextPaint.textAlign = Paint.Align.CENTER
        canvas.drawText("0", zeroX, tickY, dimTextPaint)
        if (minVal < 0) {
            dimTextPaint.textAlign = Paint.Align.LEFT
            canvas.drawText("$minVal", plotL, tickY, dimTextPaint)
        }
        dimTextPaint.textAlign = Paint.Align.RIGHT
        canvas.drawText("$maxVal", plotR, tickY, dimTextPaint)

        val colorPlus = Color.parseColor("#43A047")
        val colorMinus = Color.parseColor("#C62828")
        val barPlus = Color.parseColor("#66BB6A")
        val barMinus = Color.parseColor("#EF5350")
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

            val barEnd = plotL + (value - minVal).toFloat() / span * plotW
            val left = minOf(zeroX, barEnd)
            val right = maxOf(zeroX, barEnd)
            if (value != 0) {
                barPaint.color = if (negative || value < 0) barMinus else barPlus
                canvas.drawRoundRect(RectF(left, cy - barHeight / 2f, right, cy + barHeight / 2f), 6f, 6f, barPaint)
            }

            when {
                value == 0 -> {
                    valuePaint.textAlign = Paint.Align.LEFT
                    valuePaint.color = Color.parseColor("#909090")
                    canvas.drawText("0", zeroX + context.dp2px(6).toFloat(),
                        cy + valuePaint.textSize / 2f, valuePaint)
                }
                negative -> {
                    valuePaint.textAlign = Paint.Align.LEFT
                    valuePaint.color = colorMinus
                    canvas.drawText("-$value", right + context.dp2px(6).toFloat(),
                        cy + valuePaint.textSize / 2f, valuePaint)
                }
                value > 0 -> {
                    valuePaint.textAlign = Paint.Align.LEFT
                    valuePaint.color = colorPlus
                    canvas.drawText("+$value", right + context.dp2px(6).toFloat(),
                        cy + valuePaint.textSize / 2f, valuePaint)
                }
                else -> {
                    valuePaint.textAlign = Paint.Align.RIGHT
                    valuePaint.color = colorMinus
                    canvas.drawText("$value", left - context.dp2px(6).toFloat(),
                        cy + valuePaint.textSize / 2f, valuePaint)
                }
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
        // 限制最大高度，防止平板/横屏下产出超出 Canvas 上限的位图而崩溃
        val pieSize = minOf((context.resources.displayMetrics.widthPixels * 0.55f).toInt(),
                            context.dp2px(300))
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
