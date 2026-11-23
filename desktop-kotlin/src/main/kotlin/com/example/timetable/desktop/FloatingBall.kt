package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Color
import java.awt.Cursor
import java.awt.Dimension
import java.awt.Font
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Point
import java.awt.RenderingHints
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.JFrame
import javax.swing.JMenuItem
import javax.swing.JPanel
import javax.swing.JPopupMenu
import javax.swing.JWindow
import javax.swing.SwingUtilities

/** 桌面悬浮球：可拖动、右键菜单，位置与皮肤写回 settings.json。 */
class FloatingBall(private val app: DesktopApp) : JWindow(app) {
    private val skins = listOf(
        Color(0x4C8BF5) to Color(0x8AB4F8),
        Color(0x3FA66B) to Color(0x81C995),
        Color(0xD98320) to Color(0xF6B26B),
    )
    private val content = BallPanel()
    private var dragOrigin: Point? = null
    private var skinIndex = 1

    init {
        val settings = DataStore.settings()
        val ballSettings = settings["floating_ball"].asMap()
        skinIndex = (ballSettings.num("skin") - 1).coerceIn(0, skins.lastIndex)
        content.skin = skins[skinIndex]
        val x = ballSettings.num("x")
        val y = ballSettings.num("y")
        val screen = graphicsConfiguration.bounds
        val initial = if (x == 0 && y == 0) {
            Point(screen.x + screen.width - 110, screen.y + screen.height - 180)
        } else Point(x, y)

        content.layout = BorderLayout()
        content.add(Theme.label("710", Color.WHITE, Font("Microsoft YaHei UI", Font.BOLD, 20)).apply {
            horizontalAlignment = javax.swing.SwingConstants.CENTER
        }, BorderLayout.CENTER)
        content.addMouseListener(object : MouseAdapter() {
            override fun mousePressed(e: MouseEvent?) = maybePopup(e)
            override fun mouseReleased(e: MouseEvent?) {
                maybePopup(e)
                dragOrigin = null
                savePosition()
            }
        })
        content.addMouseMotionListener(object : MouseAdapter() {
            override fun mouseDragged(e: MouseEvent?) {
                val origin = dragOrigin ?: return
                val event = e ?: return
                location = Point(location.x + event.x - origin.x, location.y + event.y - origin.y)
            }
        })

        contentPane.add(content)
        pack()
        location = initial
        isAlwaysOnTop = true
    }

    private fun maybePopup(e: MouseEvent?) {
        val event = e ?: return
        if (SwingUtilities.isRightMouseButton(event) && event.id == MouseEvent.MOUSE_RELEASED) {
            JPopupMenu().apply {
                add(JMenuItem("显示主界面").apply { addActionListener { app.showPanel() } })
                add(JMenuItem("打开积分管理").apply { addActionListener { app.showScoreTab() } })
                addSeparator()
                add(JMenuItem("切换皮肤").apply {
                    addActionListener {
                        skinIndex = (skinIndex + 1) % skins.size
                        content.skin = skins[skinIndex]
                        repaint()
                        savePosition()
                    }
                })
                add(JMenuItem("隐藏悬浮球").apply { addActionListener { hideBall() } })
            }.show(content, event.x, event.y)
        } else if (event.id == MouseEvent.MOUSE_PRESSED) {
            dragOrigin = event.point
        }
    }

    private fun savePosition() {
        val settings = DataStore.settings()
        val ballSettings = settings["floating_ball"].asMutableMap()
        ballSettings["x"] = location.x
        ballSettings["y"] = location.y
        ballSettings["skin"] = skinIndex + 1
        settings["floating_ball"] = ballSettings
        DataStore.saveSettings(settings)
    }

    fun showBall() {
        isVisible = true
        update(ScheduleService.state())
    }

    fun hideBall() {
        isVisible = false
        val settings = DataStore.settings()
        settings["floating_ball_hidden"] = true
        DataStore.saveSettings(settings)
    }

    fun toggle() = if (isShowing) hideBall() else showBall()

    fun update(info: Map<*, *>) {
        if (!isShowing) return
        val text = when (info.str("state")) {
            "in_class" -> "课"
            "is_counting", "before_class" -> "备"
            "disabled" -> "停"
            "weekend" -> "休"
            else -> "710"
        }
        val label = content.getComponent(0) as? javax.swing.JLabel ?: return
        if (label.text != text) label.text = text
    }

    override fun dispose() {
        runCatching { savePosition() }
        super.dispose()
    }

    private inner class BallPanel : JPanel() {
        var skin: Pair<Color, Color> = skins[1]

        init {
            preferredSize = Dimension(72, 72)
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            isOpaque = false
        }

        override fun paintComponent(g: Graphics) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            g2.color = Color(0, 0, 0, 0)
            g2.fillRect(0, 0, width, height)
            g2.paint = java.awt.LinearGradientPaint(
                0f, 0f, 0f, height.toFloat(), floatArrayOf(0f, 1f), arrayOf(skin.first, skin.second),
            )
            g2.fillOval(2, 2, width - 4, height - 4)
            g2.color = Color(255, 255, 255, 90)
            g2.drawOval(2, 2, width - 4, height - 4)
        }
    }
}
