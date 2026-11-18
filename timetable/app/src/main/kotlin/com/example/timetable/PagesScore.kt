package com.example.timetable

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

// ============================================================================
// 五、积分页
// ============================================================================

internal fun buildScorePage(ctx: Context): View {
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
