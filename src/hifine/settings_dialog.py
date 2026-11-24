"""Desktop preferences for HiFine."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QVBoxLayout,
)

from .settings import MAX_SETTING_INT, AppSettings


STYLE = """
QDialog { background: #232426; }
QLabel, QGroupBox, QSpinBox, QLineEdit, QPushButton { color: #eeeae4; font-size: 13px; }
QGroupBox { font-weight: 600; border: 1px solid #454548; border-radius: 7px;
    margin-top: 9px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #f1bc86; }
QLabel#description { color: #b5b1ac; }
QSpinBox, QLineEdit { background: #191a1c; border: 1px solid #635f5a; border-radius: 4px;
    padding: 4px 6px; selection-background-color: #f0b47b; selection-color: #251c14; }
QPushButton { background: #323335; border: 1px solid #535254; border-radius: 5px;
    padding: 5px 16px; }
QPushButton:hover { background: #404043; }
QPushButton#save { background: #f0b47b; border-color: #f1bd8b; color: #251c14; }
QPushButton#save:hover { background: #fac58f; }
QSpinBox:focus, QLineEdit:focus, QPushButton:focus { border-color: #f1bc86; }
QPushButton#save:focus { border-color: #fff3e7; }
"""


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("设置")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)
        layout.addWidget(self._cache_group())
        layout.addWidget(self._update_group())
        layout.addStretch()

        button = QDialogButtonBox.StandardButton
        self.buttons = QDialogButtonBox(button.Save | button.Cancel)
        save = self.buttons.button(button.Save)
        save.setObjectName("save")
        save.setText("保存")
        save.setDefault(True)
        self.buttons.button(button.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _cache_group(self):
        group = QGroupBox("图片缓存")
        form = QFormLayout(group)
        form.setContentsMargins(16, 22, 16, 16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        description = QLabel("缓存已解码的图片，加快前后翻页。")
        description.setObjectName("description")
        description.setWordWrap(True)
        form.addRow(description)
        self.cache_max_entries = self._spin_box(self._settings.cache_max_entries, " 张")
        self.cache_max_mib = self._spin_box(self._settings.cache_max_mib, " MiB")
        form.addRow("图片数量上限", self.cache_max_entries)
        form.addRow("缓存内存上限", self.cache_max_mib)
        return group

    @staticmethod
    def _spin_box(value, suffix):
        field = QSpinBox()
        field.setRange(1, MAX_SETTING_INT)
        field.setSuffix(suffix)
        field.setValue(value)
        return field

    def _update_group(self):
        group = QGroupBox("软件更新")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(12)
        description = QLabel("启动时检查更新。填写 CDK 后，发现新版本会自动下载并打开安装包。")
        description.setObjectName("description")
        description.setWordWrap(True)
        layout.addWidget(description)

        row = QHBoxLayout()
        self.mirrorchyan_cdk = QLineEdit()
        self.mirrorchyan_cdk.setAccessibleName("Mirror 酱 CDK")
        self.mirrorchyan_cdk.setEchoMode(QLineEdit.EchoMode.Password)
        self.mirrorchyan_cdk.setText(self._settings.mirrorchyan_cdk)
        label = QLabel('<a style="color: #f1bc86" href="https://mirrorchyan.com/zh?source=HiFine-settings">'
                       'Mirror 酱</a> CDK')
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        label.setBuddy(self.mirrorchyan_cdk)
        row.addWidget(label)
        row.addWidget(self.mirrorchyan_cdk, 1)
        layout.addLayout(row)
        return group

    def settings(self) -> AppSettings:
        return replace(self._settings, cache_max_entries=self.cache_max_entries.value(),
                       cache_max_mib=self.cache_max_mib.value(), mirrorchyan_cdk=self.mirrorchyan_cdk.text().strip())
