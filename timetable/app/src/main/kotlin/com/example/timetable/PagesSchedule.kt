package com.example.timetable

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

// ============================================================================
// 四、课表页
// ============================================================================

internal fun buildSchedulePage(ctx: Context): View {
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

internal fun makeCard(ctx: Context): LinearLayout = LinearLayout(ctx).apply {
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
