"""Keyboard reference for HiFine's desktop viewer."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QGroupBox, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from .settings_dialog import STYLE as DIALOG_STYLE


class ShortcutsDialog(QDialog):
    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键")
        self.setStyleSheet(DIALOG_STYLE + """
            QScrollArea, QWidget#shortcutGroups { background: #232426; }
            QLabel#shortcutKeys { background: #303133; color: #edcfaf; font-size: 12px;
                border: 1px solid #514b45; border-radius: 4px; padding: 1px 6px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAccessibleName("快捷键列表")
        content = QWidget()
        content.setObjectName("shortcutGroups")
        stack = QVBoxLayout(content)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self._grid = QGridLayout()
        self._grid.setSpacing(12)
        stack.addLayout(self._grid)
        stack.addStretch()
        self._cards = []
        for title, rows in groups:
            card = QGroupBox(title)
            table = QGridLayout(card)
            table.setContentsMargins(14, 20, 14, 12)
            table.setVerticalSpacing(7)
            table.setHorizontalSpacing(10)
            table.setColumnStretch(0, 1)
            for row, (action, keys) in enumerate(rows):
                label = QLabel(action)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                table.addWidget(label, row, 0)
                keycap = QLabel(keys)
                keycap.setTextFormat(Qt.TextFormat.PlainText)
                keycap.setWordWrap(True)
                keycap.setObjectName("shortcutKeys")
                table.addWidget(keycap, row, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setRowStretch(table.rowCount(), 1)
            self._cards.append(card)
        self._columns = 0
        self._arrange_groups(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        close = QDialogButtonBox.StandardButton.Close
        buttons = QDialogButtonBox(close)
        buttons.button(close).setText("关闭")
        buttons.button(close).setCursor(Qt.CursorShape.PointingHandCursor)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        screen = self.screen().availableGeometry()
        self.resize(min(740, screen.width() - 40), min(590, screen.height() - 80))
        scroll.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_groups(2 if event.size().width() >= 660 else 1)

    def _arrange_groups(self, columns):
        if self._columns == columns:
            return
        self._columns = columns
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, int(columns == 2))
        for i, card in enumerate(self._cards):
            self._grid.removeWidget(card)
            row, column = divmod(i, columns)
            self._grid.addWidget(card, row, column)
