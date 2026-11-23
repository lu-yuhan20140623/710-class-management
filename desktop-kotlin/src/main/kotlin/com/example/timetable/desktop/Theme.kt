package com.example.timetable.desktop

import java.awt.Color
import java.awt.Component
import java.awt.Font
import javax.swing.table.TableCellRenderer
import java.awt.Insets
import javax.swing.BorderFactory
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JTable
import javax.swing.UIManager
import javax.swing.table.DefaultTableCellRenderer
import javax.swing.table.TableModel

/** 沿用原 Python 版暗色配色，保证视觉连续。 */
object Theme {
    val BG_MAIN = Color(0x1E1E2E)
    val BG_PANEL = Color(0x2A2A3A)
    val BG_CELL = Color(0x3A3A4A)
    val BG_CELL_ALT = Color(0x444458)
    val BG_IN_CLASS = Color(0x3B6B3B)
    val BG_COUNTING = Color(0x8B5A2B)
    val BG_PREBELL = Color(0xB5651D)
    val FG_TEXT = Color(0xE8E8F0)
    val FG_DIM = Color(0x9090A0)
    val FG_ACCENT = Color(0x7AB8FF)
    val FG_WARN = Color(0xFFCC66)
    val FG_OK = Color(0x66CC88)
    val FG_DANGER = Color(0xFF6B6B)

    val FONT: Font = Font("Microsoft YaHei UI", Font.PLAIN, 14)
    val FONT_SMALL: Font = FONT.deriveFont(12f)
    val FONT_TITLE: Font = FONT.deriveFont(Font.BOLD, 18f)
    val FONT_BIG: Font = FONT.deriveFont(Font.BOLD, 32f)

    fun init() {
        UIManager.put("Panel.background", BG_PANEL)
        UIManager.put("OptionPane.background", BG_PANEL)
        UIManager.put("OptionPane.messageForeground", FG_TEXT)
        UIManager.put("Label.foreground", FG_TEXT)
        UIManager.put("Button.background", BG_CELL)
        UIManager.put("Button.foreground", FG_TEXT)
        UIManager.put("TextField.background", BG_CELL)
        UIManager.put("TextField.foreground", FG_TEXT)
        UIManager.put("TextField.caretForeground", FG_TEXT)
        UIManager.put("PasswordField.background", BG_CELL)
        UIManager.put("PasswordField.foreground", FG_TEXT)
        UIManager.put("ComboBox.background", BG_CELL)
        UIManager.put("ComboBox.foreground", FG_TEXT)
        UIManager.put("ComboBox.selectionBackground", FG_ACCENT)
        UIManager.put("ComboBox.selectionForeground", BG_MAIN)
        UIManager.put("Spinner.background", BG_CELL)
        UIManager.put("Spinner.foreground", FG_TEXT)
        UIManager.put("Table.background", BG_PANEL)
        UIManager.put("Table.foreground", FG_TEXT)
        UIManager.put("Table.selectionBackground", Color(0x4A6FA5))
        UIManager.put("Table.selectionForeground", Color.WHITE)
        UIManager.put("Table.gridColor", Color(0x555568))
        UIManager.put("TableHeader.background", BG_CELL)
        UIManager.put("TableHeader.foreground", FG_TEXT)
        UIManager.put("List.background", BG_PANEL)
        UIManager.put("List.foreground", FG_TEXT)
        UIManager.put("List.selectionBackground", Color(0x4A6FA5))
        UIManager.put("CheckBox.background", BG_PANEL)
        UIManager.put("CheckBox.foreground", FG_TEXT)
        UIManager.put("TabbedPane.background", BG_MAIN)
        UIManager.put("TabbedPane.foreground", FG_TEXT)
        UIManager.put("MenuBar.background", BG_PANEL)
        UIManager.put("Menu.background", BG_PANEL)
        UIManager.put("Menu.foreground", FG_TEXT)
        UIManager.put("MenuItem.background", BG_PANEL)
        UIManager.put("MenuItem.foreground", FG_TEXT)
    }

    fun panel(background: Color = BG_PANEL): JPanel = JPanel().apply {
        this.background = background
        font = FONT
    }

    fun label(text: String, foreground: Color = FG_TEXT, font: Font = FONT): JLabel =
        JLabel(text).apply { this.foreground = foreground; this.font = font }

    fun button(text: String, onClick: () -> Unit): JButton = JButton(text).apply {
        font = FONT
        margin = Insets(6, 12, 6, 12)
        isFocusPainted = false
        addActionListener { onClick() }
    }

    fun titled(title: String): JPanel = panel().apply {
        border = BorderFactory.createTitledBorder(
            BorderFactory.createLineBorder(BG_CELL_ALT), title,
            0, 0, FONT.deriveFont(Font.BOLD, 13f), FG_ACCENT,
        )
    }

    fun table(model: TableModel): JTable = object : JTable(model) {
        override fun prepareRenderer(renderer: TableCellRenderer, row: Int, column: Int): Component {
            val c = super.prepareRenderer(renderer, row, column)
            c.font = FONT_SMALL
            return c
        }
    }.apply {
        rowHeight = 28
        gridColor = Color(0x555568)
        selectionBackground = Color(0x4A6FA5)
        fillsViewportHeight = true
    }

    fun centerRenderer(): DefaultTableCellRenderer = object : DefaultTableCellRenderer() {
        override fun getTableCellRendererComponent(
            table: JTable?, value: Any?, isSelected: Boolean, hasFocus: Boolean, row: Int, column: Int
        ): Component {
            val c = super.getTableCellRendererComponent(table, value, isSelected, hasFocus, row, column)
            horizontalAlignment = JLabel.CENTER
            return c
        }
    }
}
