package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Color
import java.awt.Font
import java.awt.GraphicsEnvironment
import javax.swing.JFrame
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JWindow
import javax.swing.SwingConstants

/** 上课前两分钟的倒计时提醒层，只在状态切换时显示。 */
class ReminderWindow(owner: JFrame) : JWindow(owner) {
    private val title = Theme.label("准备上课", Theme.FG_WARN, Font("Microsoft YaHei UI", Font.BOLD, 56))
    private val detail = Theme.label("", Theme.FG_TEXT, Font("Microsoft YaHei UI", Font.PLAIN, 28))
    private val count = Theme.label("", Theme.FG_ACCENT, Font("Microsoft YaHei UI", Font.BOLD, 96))
    private var wasActive = false

    init {
        val screen = GraphicsEnvironment.getLocalGraphicsEnvironment().defaultScreenDevice.defaultConfiguration.bounds
        bounds = screen
        isAlwaysOnTop = true
        focusableWindowState = false
        contentPane = JPanel(BorderLayout()).apply {
            background = Color(0x10, 0x10, 0x18, 210)
            isOpaque = true
            add(title.apply { horizontalAlignment = SwingConstants.CENTER }, BorderLayout.NORTH)
            add(count.apply { horizontalAlignment = SwingConstants.CENTER }, BorderLayout.CENTER)
            add(detail.apply { horizontalAlignment = SwingConstants.CENTER }, BorderLayout.SOUTH)
            border = javax.swing.BorderFactory.createEmptyBorder(120, 40, 160, 40)
        }
    }

    fun update(info: Map<*, *>) {
        val active = info.flag("is_counting") || info.flag("is_prebell")
        if (active) {
            if (!isVisible) {
                isVisible = true
                toFront()
            }
            val seconds = info.num("seconds_to_prebell").coerceAtLeast(0)
            count.text = "%02d:%02d".format(seconds / 60, seconds % 60)
            if (info.flag("is_prebell")) {
                title.text = "预备铃"
                title.foreground = Theme.FG_DANGER
                detail.text = "下一节：${info.str("next_name")}  ${info.str("next_subject")}"
            } else {
                title.text = "准备上课"
                title.foreground = Theme.FG_WARN
                detail.text = "即将开始：${info.str("next_name")}  ${info.str("next_subject")}"
            }
        } else if (isVisible) {
            isVisible = false
        }
        wasActive = active
    }
}
