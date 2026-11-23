package com.example.timetable.desktop

import java.awt.Color
import java.awt.Component
import java.awt.Font
import java.awt.Graphics2D
import java.awt.RenderingHints
import java.awt.image.BufferedImage
import java.io.File
import javax.swing.JFileChooser
import javax.swing.JOptionPane
import javax.swing.filechooser.FileNameExtensionFilter

object Exporter {
    fun schedulePng(parent: Component) {
        val file = choose(parent, "课程表.png", "png") ?: return
        val image = BufferedImage(1080, 660, BufferedImage.TYPE_INT_RGB)
        val g = image.createGraphics()
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
        g.color = Theme.BG_MAIN
        g.fillRect(0, 0, image.width, image.height)
        g.color = Theme.FG_TEXT
        g.font = Font("Microsoft YaHei UI", Font.BOLD, 26)
        g.drawString("${DataStore.className()} 课程表", 32, 48)

        val left = 40
        val top = 80
        val colWidth = 140
        val rowHeight = 58
        val headers = listOf("节次", "时间") + ScheduleService.weekdayNames
        headers.forEachIndexed { col, text ->
            g.color = Theme.BG_CELL_ALT
            g.fillRoundRect(left + col * colWidth, top, colWidth - 6, rowHeight - 4, 8, 8)
            g.color = Theme.FG_ACCENT
            g.font = Font("Microsoft YaHei UI", Font.BOLD, 16)
            g.drawString(text, left + col * colWidth + 14, top + 32)
        }
        val rows = ScheduleService.periods.map { it.name to it.clock } +
            listOf(ScheduleService.practice.name to ScheduleService.practice.clock,
                ScheduleService.evening.name to ScheduleService.evening.clock)
        rows.forEachIndexed { row, (name, clock) ->
            val y = top + (row + 1) * rowHeight
            val values = listOf(name, clock) + (0 until 5).map { day ->
                if (row < ScheduleService.periods.size) {
                    ScheduleService.subject(day, row + 1)
                } else if (row == ScheduleService.periods.size) {
                    ScheduleService.practiceSubjects[day] ?: "小练"
                } else "晚辅"
            }
            values.forEachIndexed { col, text ->
                g.color = if (row % 2 == 0) Theme.BG_PANEL else Theme.BG_CELL
                g.fillRoundRect(left + col * colWidth, y, colWidth - 6, rowHeight - 4, 8, 8)
                g.color = Theme.FG_TEXT
                g.font = Font("Microsoft YaHei UI", Font.PLAIN, 16)
                g.drawString(text, left + col * colWidth + 14, y + 32)
            }
        }
        g.color = Theme.FG_DIM
        g.font = Font("Microsoft YaHei UI", Font.PLAIN, 13)
        g.drawString("导出时间：${java.time.LocalDateTime.now().format(DATE_TIME)}", left, image.height - 24)
        g.dispose()

        runCatching { javax.imageio.ImageIO.write(image, "png", file) }
            .onSuccess { JOptionPane.showMessageDialog(parent, "已导出：$file", "完成", JOptionPane.INFORMATION_MESSAGE) }
            .onFailure { JOptionPane.showMessageDialog(parent, "导出失败：${it.message}", "错误", JOptionPane.ERROR_MESSAGE) }
    }

    fun scoresCsv(parent: Component) {
        val file = choose(parent, "积分记录.csv", "csv") ?: return
        val cls = DataStore.className()
        val lines = mutableListOf("小组,学号,姓名,时间,原因,增减")
        ScoreService.pointRows(cls).forEach { row ->
            lines.add(listOf(row.group, row.sid, row.name, row.time, row.reason, row.delta).joinToString(",") { csv(it) })
        }
        writeCsv(parent, file, lines)
    }

    fun hygieneCsv(parent: Component) {
        val file = choose(parent, "卫生记录.csv", "csv") ?: return
        val cls = DataStore.className()
        val lines = mutableListOf("时间,小组,姓名,原因,扣分,备注,操作人")
        HygieneService.records(cls).forEach { row ->
            lines.add(listOf(row.time, row.group, row.name, row.reason, row.score, row.note, row.by)
                .joinToString(",") { csv(it) })
        }
        writeCsv(parent, file, lines)
    }

    private fun choose(parent: Component, name: String, ext: String): File? {
        val chooser = JFileChooser().apply {
            dialogTitle = "保存文件"
            selectedFile = File(name)
            fileFilter = FileNameExtensionFilter(ext.uppercase(), ext)
        }
        return if (chooser.showSaveDialog(parent) == JFileChooser.APPROVE_OPTION) {
            var file = chooser.selectedFile
            if (!file.name.endsWith(".$ext", ignoreCase = true)) file = File(file.absolutePath + ".$ext")
            file
        } else null
    }

    private fun writeCsv(parent: Component, file: File, lines: List<String>) {
        runCatching {
            file.writeText("\uFEFF" + lines.joinToString("\r\n"), Charsets.UTF_8)
        }.onSuccess {
            JOptionPane.showMessageDialog(parent, "已导出：$file", "完成", JOptionPane.INFORMATION_MESSAGE)
        }.onFailure {
            JOptionPane.showMessageDialog(parent, "导出失败：${it.message}", "错误", JOptionPane.ERROR_MESSAGE)
        }
    }

    private fun csv(value: Any?): String {
        val text = value?.toString() ?: ""
        return if (text.any { it == ',' || it == '"' || it == '\n' }) {
            "\"" + text.replace("\"", "\"\"") + "\""
        } else text
    }
}
