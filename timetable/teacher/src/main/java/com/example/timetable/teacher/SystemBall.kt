package com.example.timetable.teacher

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast

/** 跨应用系统悬浮球：需要 SYSTEM_ALERT_WINDOW 权限。 */
object SystemBall {
    private var windowManager: WindowManager? = null
    private var ballView: TextView? = null
    private var params: WindowManager.LayoutParams? = null

    fun canDraw(context: Context): Boolean = Settings.canDrawOverlays(context)

    fun requestPermission(activity: Activity) {
        if (canDraw(activity)) {
            Toast.makeText(activity, "悬浮窗权限已开启", Toast.LENGTH_SHORT).show()
            show(activity)
            return
        }
        runCatching {
            activity.startActivity(
                Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${activity.packageName}"))
            )
        }.onFailure {
            Toast.makeText(activity, "无法打开权限设置：${it.message}", Toast.LENGTH_LONG).show()
        }
    }

    fun show(context: Context) {
        if (!canDraw(context) || ballView != null) return
        val density = context.resources.displayMetrics.density
        val size = (64 * density).toInt()
        val view = TextView(context).apply {
            text = "710"
            textSize = 20f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.rgb(0x3F, 0xA6, 0x6B))
                setStroke(2, Color.argb(100, 255, 255, 255))
            }
            alpha = 0.9f
        }
        val lp = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = (16 * density).toInt()
            y = (120 * density).toInt()
        }
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var moved = false
        view.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX; downY = event.rawY
                    startX = lp.x; startY = lp.y
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    if (kotlin.math.abs(event.rawX - downX) > 6 || kotlin.math.abs(event.rawY - downY) > 6) moved = true
                    if (moved) {
                        lp.x = startX + (event.rawX - downX).toInt()
                        lp.y = startY + (event.rawY - downY).toInt()
                        runCatching { windowManager?.updateViewLayout(view, lp) }
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!moved) openApp(context)
                    true
                }
                else -> true
            }
        }
        val manager = context.getSystemService(Context.WINDOW_SERVICE) as? WindowManager ?: return
        runCatching {
            manager.addView(view, lp)
            windowManager = manager
            ballView = view
            params = lp
        }.onFailure {
            Toast.makeText(context, "悬浮球显示失败：${it.message}", Toast.LENGTH_LONG).show()
        }
    }

    fun hide() {
        val view = ballView ?: return
        runCatching { windowManager?.removeViewImmediate(view) }
        ballView = null
        params = null
        windowManager = null
    }

    fun toggle(context: Context) {
        if (ballView != null) hide() else show(context)
    }

    fun isShowing(): Boolean = ballView != null

    fun update(info: Map<*, *>) {
        val view = ballView ?: return
        val text = when (info.str("state")) {
            "in_class" -> "课"
            "disabled" -> "停"
            "weekend" -> "休"
            else -> "710"
        }
        if (view.text.toString() != text) view.text = text
    }

    private fun openApp(context: Context) {
        val intent = context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        runCatching { context.startActivity(intent) }
    }
}
