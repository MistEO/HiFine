"""Show file actions for a selection of images."""

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from .file_clipboard import clipboard_files


def reveal_files(window, paths):
    """Show images from one folder in the platform file manager."""
    paths = tuple(paths)
    if not paths or not all(path.is_file() for path in paths):
        return
    folder = QUrl.fromLocalFile(str(paths[0].parent))
    if sys.platform == "win32":
        from .windows_menu import select_files

        try:
            select_files(paths)
        except OSError:
            QDesktopServices.openUrl(folder)
        return
    if sys.platform == "darwin":
        started, _ = QProcess.startDetached("/usr/bin/open", ["-R", *map(str, paths)])
        if not started:
            QDesktopServices.openUrl(folder)
        return

    from PySide6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher

    service = "org.freedesktop.FileManager1"
    message = QDBusMessage.createMethodCall(service, "/org/freedesktop/FileManager1", service, "ShowItems")
    message.setArguments([[path.as_uri() for path in paths], ""])
    call = QDBusConnection.sessionBus().asyncCall(message)
    watcher = QDBusPendingCallWatcher(call, window)

    def finished():
        if watcher.isError():
            QDesktopServices.openUrl(folder)
        watcher.deleteLater()

    if watcher.isFinished():
        finished()
    else:
        watcher.finished.connect(finished)


def show_file_menu(window, paths, global_pos):
    paths = (paths,) if isinstance(paths, Path) else tuple(paths or ())
    if not paths or not all(path.is_file() for path in paths):
        return False
    can_paste = bool(clipboard_files(QApplication.clipboard()))
    if sys.platform == "win32":
        from .windows_menu import show_shell_menu

        try:
            return show_shell_menu(window, paths, global_pos, paste=window.paste_files if can_paste else None)
        except OSError as exc:
            if exc.winerror not in (-2147023673, -2147467260):  # ERROR_CANCELLED, E_ABORT
                target = paths[0].name if len(paths) == 1 else f"{len(paths)} 个文件"
                QMessageBox.warning(window, "文件操作", f"{target}\n{exc}")
            return False

    menu = QMenu(window)
    reveal = menu.addAction("在 Finder 中显示" if sys.platform == "darwin" else "在文件管理器中显示")
    menu.addSeparator()
    copy = menu.addAction("复制")
    cut = menu.addAction("剪切")
    paste = menu.addAction("粘贴到当前文件夹")
    paste.setEnabled(can_paste)
    menu.addSeparator()
    trash = menu.addAction("移到废纸篓" if sys.platform == "darwin" else "移到回收站")
    selected = menu.exec(global_pos)
    menu.deleteLater()
    if selected is reveal:
        reveal_files(window, paths)
    elif selected is copy or selected is cut:
        window.copy_files(paths, cut=selected is cut)
    elif selected is paste:
        window.paste_files()
    elif selected is trash:
        window.trash_files(paths)
    return selected is not None
