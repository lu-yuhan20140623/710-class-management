package com.example.timetable

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

// ============================================================================
// 六、卫生页
// ============================================================================

internal fun buildHygienePage(ctx: Context): View {
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
