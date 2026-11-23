package com.example.timetable.desktop

import java.awt.BorderLayout
import java.awt.Desktop
import java.awt.Dimension
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Insets
import javax.swing.BorderFactory
import javax.swing.JButton
import javax.swing.JCheckBox
import javax.swing.JComboBox
import javax.swing.JLabel
import javax.swing.JOptionPane
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JTextArea
import javax.swing.JTextField

class SettingsPanel(private val app: DesktopApp) : JPanel(BorderLayout()) {
    private val portField = JTextField(LanServer.configuredPort().toString(), 8)
    private val lanAutoBox = JCheckBox("启动时自动开启局域网服务", DataStore.settings().flag("lan_autostart"))
    private val ballAutoBox = JCheckBox("启动时显示悬浮球", !DataStore.settings().flag("floating_ball_hidden"))
    private val skinCombo = JComboBox(arrayOf("蓝色", "绿色", "橙色"))
    private val cloudBox = JCheckBox("启用官网云端同步", DataStore.settings()["cloud_api"].asMap().flag("enabled"))
    private val phoneField = JTextField(18)
    private val statusArea = JTextArea().apply {
        isEditable = false
        font = Theme.FONT_SMALL
        background = Theme.BG_PANEL
        foreground = Theme.FG_TEXT
    }
    private var lastStatusUpdate = 0L

    init {
        background = Theme.BG_MAIN
        border = BorderFactory.createEmptyBorder(16, 16, 16, 16)

        val settings = DataStore.settings()
        skinCombo.selectedIndex = (settings["floating_ball"]?.asMap()?.num("skin") ?: 1).coerceIn(0, 2)
        portField.font = Theme.FONT

        val form = JPanel(GridBagLayout()).apply { background = Theme.BG_PANEL }
        form.border = BorderFactory.createCompoundBorder(
            BorderFactory.createLineBorder(Theme.BG_CELL_ALT),
            BorderFactory.createEmptyBorder(18, 18, 18, 18),
        )
        var row = 0
        form.add(Theme.label("局域网端口"), gbc(0, row)); form.add(portField, gbc(1, row++))
        form.add(lanAutoBox, gbc(0, row, 2)); row++
        form.add(ballAutoBox, gbc(0, row, 2)); row++
        form.add(JLabel("悬浮球皮肤"), gbc(0, row)); form.add(skinCombo, gbc(1, row++))
        form.add(cloudBox, gbc(0, row, 2)); row++
        form.add(JLabel("手机设备 ID"), gbc(0, row)); form.add(phoneField, gbc(1, row++))
        form.add(Theme.button("发起云端绑定") { bindPhone() }, gbc(0, row, 2)); row++
        form.add(Theme.button("保存设置") { save() }, gbc(0, row))
        form.add(Theme.button(if (LanServer.running) "停止局域网服务" else "启动局域网服务") {
            if (LanServer.running) LanServer.stop() else startLan()
            refreshStatus(true)
        }, gbc(1, row++))
        form.add(Theme.button("打开数据目录") { openDataDir() }, gbc(0, row, 2))

        val info = Theme.titled("运行状态").apply {
            layout = BorderLayout()
            add(JScrollPane(statusArea), BorderLayout.CENTER)
        }
        add(form, BorderLayout.NORTH)
        add(info, BorderLayout.CENTER)
        refreshStatus(true)
    }

    private fun gbc(x: Int, y: Int, width: Int = 1) = GridBagConstraints().apply {
        gridx = x
        gridy = y
        gridwidth = width
        anchor = GridBagConstraints.WEST
        insets = Insets(6, 6, 6, 6)
        fill = if (width > 1) GridBagConstraints.HORIZONTAL else GridBagConstraints.NONE
    }

    private fun save() {
        val port = portField.text.trim().toIntOrNull()
        if (port == null || port !in 1024..65535) {
            JOptionPane.showMessageDialog(this, "端口需在 1024–65535 之间", "提示", JOptionPane.WARNING_MESSAGE)
            return
        }
        val settings = DataStore.settings()
        settings["lan_port"] = port
        settings["lan_autostart"] = lanAutoBox.isSelected
        settings["floating_ball_hidden"] = !ballAutoBox.isSelected
        val cloudSettings = settings["cloud_api"].asMutableMap()
        cloudSettings["enabled"] = cloudBox.isSelected
        settings["cloud_api"] = cloudSettings
        val ballSettings = settings["floating_ball"].asMutableMap()
        ballSettings["skin"] = skinCombo.selectedIndex + 1
        settings["floating_ball"] = ballSettings
        DataStore.saveSettings(settings)
        if (LanServer.running && LanServer.port != port) {
            LanServer.stop()
            startLan()
        }
        JOptionPane.showMessageDialog(this, "设置已保存", "提示", JOptionPane.INFORMATION_MESSAGE)
        refreshStatus(true)
    }

    private fun startLan() {
        val error = LanServer.start(portField.text.trim().toIntOrNull() ?: LanServer.configuredPort())
        if (error != null) JOptionPane.showMessageDialog(this, error, "启动失败", JOptionPane.ERROR_MESSAGE)
    }

    private fun bindPhone() {
        val phoneId = phoneField.text.trim()
        if (phoneId.isBlank()) {
            JOptionPane.showMessageDialog(this, "请先填写手机设备 ID", "提示", JOptionPane.INFORMATION_MESSAGE)
            return
        }
        val message = CloudService.bindPhone(phoneId)
        JOptionPane.showMessageDialog(this, message, "云端绑定", JOptionPane.INFORMATION_MESSAGE)
    }

    private fun openDataDir() {
        runCatching { Desktop.getDesktop().open(DataStore.dataDir.toFile()) }.onFailure {
            JOptionPane.showMessageDialog(this, DataStore.dataDir.toString(), "数据目录", JOptionPane.INFORMATION_MESSAGE)
        }
    }

    fun tick() {
        if (System.currentTimeMillis() - lastStatusUpdate >= 1000) refreshStatus(false)
    }

    private fun refreshStatus(force: Boolean) {
        if (!force && System.currentTimeMillis() - lastStatusUpdate < 1000) return
        lastStatusUpdate = System.currentTimeMillis()
        val state = ScheduleService.state()
        val classes = allClasses().joinToString("、")
        statusArea.text = buildString {
            appendLine("Kotlin 桌面版 2.0.0")
            appendLine("数据目录：${DataStore.dataDir}")
            appendLine("已识别班级：$classes")
            appendLine("课节状态：${ScheduleService.stateLine(state)}")
            appendLine("局域网服务：${if (LanServer.running) "运行中 · ${LanServer.url()}" else "未启动"}")
            appendLine("云端同步：${CloudService.status}")
            appendLine("手机端连接：同一 Wi-Fi 下打开上面的地址，或使用原安卓 App 自动发现")
            appendLine("数据文件：student_data.txt / group_data.txt / hygiene_data.txt / overrides.json")
            appendLine("兼容说明：与 Python 版共用同一份数据，手机端接口保持原样")
        }
        statusArea.caretPosition = 0
    }
}
