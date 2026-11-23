package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.event.WindowAdapter
import java.awt.event.WindowEvent
import java.io.File
import javax.swing.JFrame
import javax.swing.JLabel
import javax.swing.JMenu
import javax.swing.JMenuBar
import javax.swing.JMenuItem
import javax.swing.JPanel
import javax.swing.JTabbedPane
import javax.swing.SwingConstants
import javax.swing.SwingUtilities
import javax.swing.Timer
import javax.swing.UIManager
import kotlin.system.exitProcess

fun main(args: Array<String>) {
    if (args.isNotEmpty() && !args[0].startsWith("--")) System.setProperty("timetable.data.dir", args[0])
    if (args.contains("--selftest")) {
        println(Json.pretty(SnapshotBuilder.build()))
        return
    }
    if (args.contains("--selftest-lan")) {
        val error = LanServer.start(18765)
        if (error != null) {
            println(error)
            return
        }
        val response = java.net.URL("http://127.0.0.1:18765/api/ping").readText()
        println(response)
        LanServer.stop()
        return
    }
    runCatching { UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName()) }
    Theme.init()
    SwingUtilities.invokeLater {
        DesktopApp().apply {
            size = Dimension(1180, 740)
            setLocationRelativeTo(null)
            isVisible = true
        }
    }
}

class DesktopApp : JFrame("课程表 · Kotlin 桌面版") {
    private val tabs = JTabbedPane()
    private val schedulePanel = SchedulePanel()
    private val scorePanel = ScorePanel()
    private val hygienePanel = HygienePanel()
    private val settingsPanel: SettingsPanel
    private val ball: FloatingBall
    private val reminder: ReminderWindow = ReminderWindow(this)
    private val statusLabel = Theme.label("正在初始化…", Theme.FG_DIM, Theme.FONT_SMALL)
    private var lastVisibleTab = 0

    init {
        contentPane.background = Theme.BG_MAIN
        settingsPanel = SettingsPanel(this)
        ball = FloatingBall(this)

        tabs.apply {
            addTab("课程表", schedulePanel)
            addTab("积分管理", scorePanel)
            addTab("卫生管理", hygienePanel)
            addTab("设置", settingsPanel)
        }
        add(tabs, BorderLayout.CENTER)

        val bottom = JPanel(BorderLayout()).apply {
            background = Theme.BG_PANEL
            add(statusLabel, BorderLayout.WEST)
        }
        statusLabel.border = javax.swing.BorderFactory.createEmptyBorder(6, 12, 6, 12)
        add(bottom, BorderLayout.SOUTH)

        jMenuBar = buildMenuBar()
        defaultCloseOperation = DO_NOTHING_ON_CLOSE
        addWindowListener(object : WindowAdapter() {
            override fun windowClosing(e: WindowEvent?) = exit()
        })

        val settings = DataStore.settings()
        if (settings.flag("lan_autostart")) {
            LanServer.start(LanServer.configuredPort())
        }
        if (!settings.flag("floating_ball_hidden")) ball.showBall()

        Thread({
            while (true) {
                runCatching { CloudService.tick() }
                Thread.sleep(2000)
            }
        }, "cloud-sync").apply { isDaemon = true }.start()
        Timer(500) { tick() }.start()
        tick()
    }

    private fun buildMenuBar(): JMenuBar {
        val fileMenu = JMenu("文件").apply {
            add(JMenuItem("导出课程表 PNG").apply {
                addActionListener { Exporter.schedulePng(this@DesktopApp) }
            })
            add(JMenuItem("导出积分 CSV").apply {
                addActionListener { Exporter.scoresCsv(this@DesktopApp) }
            })
            add(JMenuItem("导出卫生 CSV").apply {
                addActionListener { Exporter.hygieneCsv(this@DesktopApp) }
            })
            addSeparator()
            add(JMenuItem("退出").apply { addActionListener { exit() } })
        }
        val toolMenu = JMenu("工具").apply {
            add(JMenuItem("显示/隐藏悬浮球").apply { addActionListener { ball.toggle() } })
            add(JMenuItem("刷新数据").apply {
                addActionListener {
                    schedulePanel.refresh()
                    scorePanel.refresh()
                    hygienePanel.refresh()
                }
            })
        }
        return JMenuBar().apply { add(fileMenu); add(toolMenu) }
    }

    private fun tick() {
        val info = ScheduleService.state()
        statusLabel.text = "${ScheduleService.stateLine(info)}    |    " +
            "数据目录：${DataStore.dataDir}    |    " +
            if (LanServer.running) "局域网：${LanServer.url()}" else "局域网服务未启动"
        schedulePanel.updateState(info)
        ball.update(info)
        reminder.update(info)
        LanServer.checkAndPublish()
        settingsPanel.tick()
        if (tabs.selectedIndex == 1 && lastVisibleTab != 1) scorePanel.refresh()
        if (tabs.selectedIndex == 2 && lastVisibleTab != 2) hygienePanel.refresh()
        lastVisibleTab = tabs.selectedIndex
    }

    fun showScoreTab() {
        scorePanel.refresh()
        tabs.selectedIndex = 1
        isVisible = true
        toFront()
    }

    fun showPanel() {
        isVisible = true
        toFront()
    }

    fun toggleBall() = ball.toggle()

    fun exit() {
        val settings = DataStore.settings()
        settings["floating_ball_hidden"] = !ball.isShowing
        DataStore.saveSettings(settings)
        ball.dispose()
        reminder.dispose()
        LanServer.stop()
        dispose()
        exitProcess(0)
    }
}
