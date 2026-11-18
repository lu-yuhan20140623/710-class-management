package com.example.timetable

import android.content.Context
import android.util.TypedValue
import android.widget.TextView

// ============================================================================
// 二、UI 工具
// ============================================================================

fun Context.dp2px(dp: Int): Int =
    TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, dp.toFloat(), resources.displayMetrics).toInt()

fun Context.sp2px(sp: Int): Float =
    TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, sp.toFloat(), resources.displayMetrics)

fun TextView.textSizeSp(sp: Int) { textSize = sp.toFloat() }
