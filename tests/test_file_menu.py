"""Check the portable menu hands the entire selection to file actions."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from hifine import file_menu


@pytest.mark.parametrize("action", ["在 Finder 中显示", "复制", "剪切", "粘贴到当前文件夹", "移到废纸篓"])
def test_selected_files_menu(monkeypatch, tmp_path, action):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.copy_files, window.paste_files, window.trash_files = Mock(), Mock(), Mock()
    paths = (tmp_path / "照片 #01.png", tmp_path / "照片 02.png")
    for path in paths:
        path.touch()
    monkeypatch.setattr(file_menu, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(file_menu, "clipboard_files", lambda clipboard: list(paths))
    reveal = Mock(return_value=(True, 1))
    monkeypatch.setattr(file_menu.QProcess, "startDetached", reveal)

    def choose():
        menu = app.activePopupWidget()
        for item in menu.actions():
            if item.text() == action and item.isEnabled():
                menu.setActiveAction(item)
                QTest.keyClick(menu, Qt.Key.Key_Return)
                return
        menu.close()

    QTimer.singleShot(0, choose)
    assert file_menu.show_file_menu(window, paths, QPoint())
    if action == "在 Finder 中显示":
        reveal.assert_called_once_with("/usr/bin/open", ["-R", *map(str, paths)])
    elif action in ("复制", "剪切"):
        window.copy_files.assert_called_once_with(paths, cut=action == "剪切")
    elif action == "粘贴到当前文件夹":
        window.paste_files.assert_called_once_with()
    else:
        window.trash_files.assert_called_once_with(paths)
