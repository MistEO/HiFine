"""Exercise the viewer through Qt key, wheel and pointer events."""

import os
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

from PIL import Image
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QImage, QKeySequence, QMovie, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QMessageBox, QTextEdit,
)

from hifine import file_menu, reader
from hifine.app import SAMPLE
from hifine.favorites import FavoriteStore
from hifine.file_clipboard import read_file_clipboard, write_file_clipboard
from hifine.settings import AppSettings
from hifine.settings_dialog import SettingsDialog
from hifine.viewer import MainWindow


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    yield application
    if application.platformName() == "offscreen":
        application.clipboard().clear()


@pytest.fixture()
def settings_store(tmp_path):
    return QSettings(str(tmp_path / "hifine.ini"), QSettings.Format.IniFormat)


@pytest.fixture()
def window(app, settings_store, tmp_path):
    widget = MainWindow(sample_path=SAMPLE, settings_store=settings_store,
                        favorite_store=FavoriteStore(tmp_path / "profile" / "favorites.sqlite3"))
    widget.show()
    widget.activateWindow()
    app.processEvents()
    yield widget
    dispose_window(widget)


def dispose_window(widget):
    widget.close()
    widget._reads.shutdown()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_until(app, predicate):
    deadline = monotonic() + 10
    while not predicate():
        assert monotonic() < deadline, "timed out waiting for the viewer"
        app.processEvents()
        sleep(0.005)


def finish_read(app, window, *, prefetch=False):
    wait_until(app, lambda: not window._reads.loading
               and (not prefetch or not window._reads._active))


def thumbnail_color(row):
    preview = row.data(Qt.ItemDataRole.DecorationRole)
    if preview is not None and not preview.isNull():
        return preview.pixelColor(preview.rect().center()).name()


def request_menu(app, widget, point):
    app.sendEvent(widget, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, widget.mapToGlobal(point)))


def test_star_filter_navigation_bulk_copy_and_unmark(app, window, tmp_path):
    paths = [tmp_path / f"{n}.jpg" for n in range(4)]
    for path in paths:
        Image.new("RGB", (8, 8)).save(path)
    window.open_file(paths[0])
    finish_read(app, window)
    view = window.thumbnail_list
    # A second window may already have starred the photo since this one loaded.
    window._favorite_store.set_favorite(paths[0], True)
    QTest.keyClick(view, Qt.Key.Key_F)
    assert window.favorite_button.isChecked()
    assert window._favorite_store.in_folder(tmp_path) == {paths[0]}
    window.navigate(2)
    finish_read(app, window)
    QTest.mouseClick(window.favorite_button, Qt.MouseButton.LeftButton)
    assert window.favorite_button.isChecked()
    window.open_file(paths[1])
    finish_read(app, window)
    QTest.keyClick(view, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    finish_read(app, window)
    assert window.favorite_filter.isChecked()
    assert window.files == [paths[0], paths[2]] and window.current_path == paths[2]
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert read_file_clipboard(app.clipboard()).paths == (paths[0], paths[2])

    # A mark belongs to the displayed image even when both thumbnails are selected.
    QTest.keyClick(view, Qt.Key.Key_F)
    finish_read(app, window)
    assert window.files == [paths[0]] and window.current_path == paths[0]
    QTest.keyClick(view, Qt.Key.Key_F)
    assert window.files == [] and window.current_path is None
    assert window.state_title.text() == "还没有星标照片"
    description = window.state_description
    for width in (600, 1200):
        window.resize(width, 600)
        app.processEvents()
        assert description.isVisible()
        assert description.height() >= description.heightForWidth(description.width())
        assert abs(description.geometry().center().x() - window.state.rect().center().x()) <= 1
    assert not window.favorite_button.isEnabled()
    QTest.mouseClick(window.favorite_filter, Qt.MouseButton.LeftButton)
    finish_read(app, window)
    assert window.files == paths and window.current_path == paths[1]
    assert not window.favorite_button.isChecked()
    window._apply_settings(AppSettings(keep_zoom_position=True))
    window.canvas.set_zoom(2)
    window.favorite_filter.click()
    assert window.current_path is None
    window.favorite_filter.click()
    finish_read(app, window)
    assert window.current_path == paths[1] and window.canvas.zoom() == 2


def test_read_error_wraps_long_filename_after_resizing(app, window, tmp_path):
    path = tmp_path / ("DSC_" + "0123456789" * 8 + ".png")
    path.write_bytes(b"broken image")
    window.open_file(path)
    finish_read(app, window)
    assert window.state_title.text() == "无法打开这张图片"
    description = window.state_description
    assert path.name in description.toPlainText()
    for width in (600, 1200):
        window.resize(width, 650)
        app.processEvents()
        document = description.document()
        assert document.firstBlock().layout().lineCount() > 1
        assert document.idealWidth() <= description.viewport().width()
        assert document.size().height() <= description.viewport().height()


def test_filtered_rename_refresh_and_explicit_open(app, window, tmp_path, monkeypatch):
    first, last = [tmp_path / name for name in ("a.png", "c.png")]
    for path in (first, last):
        Image.new("RGB", (8, 8)).save(path)
    window.open_file(first)
    finish_read(app, window)
    window.favorite_button.click()
    window.favorite_filter.click()
    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda *args: True)
    window._show_file_menu([first], QPoint())
    renamed = tmp_path / "b.png"
    first.rename(renamed)
    wait_until(app, lambda: window._displayed_path == renamed)
    assert window.files == [renamed] and window.favorite_button.isChecked()
    window.open_file(last)
    finish_read(app, window)
    assert not window.favorite_filter.isChecked()
    assert window.files == [renamed, last] and window.current_path == last
    window.favorite_filter.click()
    finish_read(app, window)
    assert window.current_path == renamed and window.files == [renamed]


def test_pending_navigation_cannot_star_the_wrong_photo(app, window, blocked_prefetch):
    slow, release, _ = blocked_prefetch
    previous = window.current_path
    window.navigate(1)
    assert window.current_path == slow and window._displayed_path == previous
    QTest.keyClick(window.thumbnail_list, Qt.Key.Key_F)
    assert not window._favorites
    release.set()
    finish_read(app, window)
    QTest.keyClick(window.thumbnail_list, Qt.Key.Key_F)
    assert window._favorites == {slow}


def test_cut_to_another_folder_keeps_star_on_actual_destination(app, window, tmp_path):
    photo = tmp_path / "photo.png"
    folder = tmp_path / "精选"
    folder.mkdir()
    existing = folder / photo.name
    for path in (photo, existing):
        Image.new("RGB", (8, 8)).save(path)
    window.open_file(photo)
    finish_read(app, window)
    window.favorite_button.click()
    window.copy_files([photo], cut=True)
    window.open_file(existing)
    finish_read(app, window)
    window.favorite_filter.click()
    assert not window.files
    window.paste_files()
    moved = folder / "photo (2).png"
    wait_until(app, lambda: window._displayed_path == moved)
    assert window.files == [moved] and window.favorite_button.isChecked()
    assert window._favorite_store.in_folder(tmp_path) == set()


def test_rename_starred_thumbnail_while_viewing_another_photo(app, window, tmp_path, monkeypatch):
    first, second, other = [tmp_path / name for name in ("a.png", "b.png", "c.png")]
    for photo in (first, second, other):
        Image.new("RGB", (32, 16)).save(photo)
    window.open_file(second)
    finish_read(app, window)
    window.favorite_button.click()
    window.navigate(-1)
    finish_read(app, window)
    window.favorite_button.click()
    window.favorite_filter.click()
    assert window.current_path == first and window.files == [first, second]

    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda *args: True)
    view = window.thumbnail_list
    request_menu(app, view.viewport(), view.visualRect(view.model().index(1, 0)).center())
    assert view.selected_paths() == [second] and window.current_path == first
    renamed = tmp_path / "renamed.png"
    second.rename(renamed)
    wait_until(app, lambda: renamed in window._folder_files)
    assert window._displayed_path == first and window.current_path == first
    assert window.files == [first, renamed] and view.selected_paths() == [renamed]
    assert window._favorite_store.in_folder(tmp_path) == {first, renamed}
    assert other not in {Path(p) for p in window._menu_watch.files()}


def test_open_sample_shows_three_bundled_thumbnails(app, window):
    window.open_sample()
    finish_read(app, window)
    view = window.thumbnail_list
    model = view.model()
    assert window.current_path == SAMPLE
    assert view.currentIndex().data() == SAMPLE.name
    assert model.rowCount() == 3
    rows = [model.index(row, 0) for row in range(3)]
    wait_until(app, lambda: all(thumbnail_color(row) for row in rows))


def test_settings_descriptions_fit_when_dialog_is_shrunk(app, window):
    dialog = SettingsDialog(AppSettings(), window)
    dialog.show()
    dialog.resize(dialog.minimumWidth(), 1)
    app.processEvents()
    assert dialog.height() >= dialog.layout().totalHeightForWidth(dialog.width())
    for label in dialog.findChildren(QLabel, "description"):
        assert label.height() >= label.heightForWidth(label.width())
    dialog.close()


def test_settings_save_cancel_and_reopen(app, window, settings_store, tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (32, 16), "red").save(photo)
    window.open_file(photo)
    finish_read(app, window)
    window.canvas.set_zoom(2)
    initial = []
    tab_moved = []

    def edit(entries, mib, cdk, keep_zoom_position, button):
        dialog = app.activeModalWidget()
        initial.append((dialog.cache_max_entries.value(), dialog.cache_max_mib.value(),
                        dialog.mirrorchyan_cdk.text(), dialog.mirrorchyan_cdk.echoMode(),
                        dialog.keep_zoom_position.isChecked()))
        dialog.cache_max_entries.setFocus()
        before = dialog.focusWidget()
        QTest.keyClick(before, Qt.Key.Key_Tab)
        tab_moved.append(dialog.focusWidget() is not before)
        dialog.cache_max_entries.setValue(entries)
        dialog.cache_max_mib.setValue(mib)
        dialog.mirrorchyan_cdk.setText(cdk)
        dialog.keep_zoom_position.setChecked(keep_zoom_position)
        QTest.mouseClick(dialog.buttons.button(button), Qt.MouseButton.LeftButton)

    buttons = QDialogButtonBox.StandardButton
    QTimer.singleShot(0, lambda: edit(3, 64, " example-cdk ", True, buttons.Save))
    QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
    assert AppSettings.load(settings_store) == AppSettings(3, 64, "example-cdk", True)
    cache = window._reads._cache
    assert (cache.max_entries, cache.max_bytes) == (3, 64 * 1024**2)
    assert window.current_path == photo and window.canvas.zoom() == 2

    QTimer.singleShot(0, lambda: edit(1, 1, "", False, buttons.Cancel))
    QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
    masked = QLineEdit.EchoMode.Password
    assert initial == [(8, 256, "", masked, False), (3, 64, "example-cdk", masked, True)]
    assert all(tab_moved) and window.info_panel.isVisible()
    assert (cache.max_entries, cache.max_bytes) == (3, 64 * 1024**2)

    reopened = MainWindow(settings_store=QSettings(settings_store.fileName(), QSettings.Format.IniFormat))
    try:
        cache = reopened._reads._cache
        assert (cache.max_entries, cache.max_bytes) == (3, 64 * 1024**2)
        assert reopened._settings.mirrorchyan_cdk == "example-cdk"
        assert reopened._settings.keep_zoom_position
    finally:
        dispose_window(reopened)


def test_file_menu_uses_the_hit_image_and_preserves_preview(app, window, tmp_path, monkeypatch):
    first, second = [tmp_path / f"照片 {i}.png" for i in (1, 2)]
    for path in (first, second):
        Image.new("RGB", (80, 60)).save(path)
    calls = []
    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda parent, path, pos: calls.append((path, pos)))
    window.resize(850, 600)
    window.open_file(first)
    finish_read(app, window)
    canvas = window.canvas
    center = canvas.rect().center()
    view = window.thumbnail_list
    other = view.visualRect(view.model().index(1, 0)).center()

    request_menu(app, canvas, center)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.RightButton, pos=other)
    request_menu(app, view.viewport(), other)
    request_menu(app, canvas, QPoint(2, 2))
    request_menu(app, view.viewport(), view.viewport().rect().bottomLeft())
    assert calls == [([first], canvas.mapToGlobal(center)), ([second], view.viewport().mapToGlobal(other))]
    assert window.current_path == first
    assert view.selected_paths() == [second]


def test_multiselection_clipboard_shortcuts_and_menu(app, window, tmp_path, monkeypatch):
    first, middle, last = [tmp_path / f"{i}.png" for i in range(3)]
    for path, color in zip((first, middle, last), ("red", "lime", "blue")):
        Image.new("RGB", (16, 12), color).save(path)
    window.resize(850, 630)
    window.open_file(first)
    finish_read(app, window)
    view = window.thumbnail_list
    ctrl = Qt.KeyboardModifier.ControlModifier
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, ctrl,
                     view.visualRect(view.model().index(2, 0)).center())
    finish_read(app, window)
    assert view.selected_paths() == [first, last]
    assert window.position.text() == "3 / 3"
    assert "已选 2 张" in window.selection_label.text()
    calls = []
    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda parent, paths, point: calls.append(paths))
    request_menu(app, view.viewport(), view.visualRect(view.model().index(0, 0)).center())
    assert calls == [[first, last]]
    QTest.keyClick(view, Qt.Key.Key_C, ctrl)
    copied = read_file_clipboard(app.clipboard())
    assert copied.paths == (first, last) and not copied.cut
    QTest.keyClick(view, Qt.Key.Key_V, ctrl)
    wait_until(app, lambda: len(window.files) == 5)
    for original in (first, last):
        assert (tmp_path / f"{original.stem} (2).png").read_bytes() == original.read_bytes()
    assert view.selected_paths() == [first, last]
    QTest.keyClick(view, Qt.Key.Key_A, ctrl)
    QTest.keyClick(view, Qt.Key.Key_X, ctrl)
    cut = read_file_clipboard(app.clipboard())
    assert cut.cut and list(cut.paths) == window.files
    assert all(path.is_file() for path in cut.paths)

    destination = tmp_path / "另一组"
    destination.mkdir()
    cover = destination / "封面.png"
    Image.new("RGB", (8, 8)).save(cover)
    window.open_file(cover)
    finish_read(app, window)
    QTest.keyClick(view, Qt.Key.Key_V, ctrl)
    wait_until(app, lambda: len(window.files) == 6)
    assert all((destination / path.name).is_file() and not path.exists() for path in cut.paths)
    assert read_file_clipboard(app.clipboard()) is None
    assert window.current_path == cover


@pytest.mark.parametrize("via_keyboard", [False, True], ids=["button", "F1"])
def test_shortcut_help_preserves_thumbnail_selection_and_focus(app, window, tmp_path, via_keyboard):
    paths = [tmp_path / f"{i}.png" for i in range(8)]
    for path in paths:
        Image.new("RGB", (16, 8)).save(path)
    window.resize(600, 380)
    window.open_file(paths[-1])
    finish_read(app, window)
    view = window.thumbnail_list
    hint = window.thumbnail_hint
    assert view.verticalScrollBar().value() > 0
    assert hint.isVisible() and hint.text() == "快捷键"
    assert hint.mapTo(window, QPoint()).y() >= view.mapTo(window, QPoint(0, view.height())).y()
    assert hint.width() >= hint.sizeHint().width()
    previous = view.model().index(len(paths) - 2, 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     view.visualRect(previous).center())
    finish_read(app, window)
    assert view.selected_paths() == paths[-2:]

    help_pages = []

    def read_hint():
        dialog = app.activeModalWidget()
        if dialog is not None:
            title = dialog.windowTitle()
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            help_pages.append((title, labels, not dialog.isVisible()))
            if dialog.isVisible():
                dialog.reject()

    timer = QTimer(window)
    timer.timeout.connect(read_hint)
    timer.start(10)
    if via_keyboard:
        QTest.keyClick(view, Qt.Key.Key_F1)
    else:
        QTest.mouseClick(hint, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: bool(help_pages))
    timer.stop()
    (title, labels, escaped), = help_pages
    assert title == "快捷键" and escaped
    assert window.focusWidget() is view
    window.activateWindow()
    wait_until(app, view.hasFocus)
    keys = QKeySequence.StandardKey
    for key in (keys.SelectAll, keys.Copy, keys.Cut, keys.Paste, keys.Delete,
                keys.Open, "Tab", "F6", "Shift+F", "F11"):
        native = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
        assert any(native in label for label in labels)
    assert any("星标" in label for label in labels)
    assert any("点击" in label for label in labels)
    assert window.current_path == paths[-2] and view.selected_paths() == paths[-2:]
    QTest.keyClick(app.focusWidget(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert view.selected_paths() == paths
    assert window.position.text() == "7 / 8"
    assert "已选 8 张" in window.selection_label.text()


def test_thumbnail_shortcuts_preserve_copying_metadata(app, window, tmp_path):
    path = tmp_path / ("DSC_" + "0123456789" * 6 + ".png")
    Image.new("RGB", (8, 8)).save(path)
    window.resize(600, 600)
    window.open_file(path)
    finish_read(app, window)
    value = next(value for value in window.info_panel.findChildren(QTextEdit, "metaValue")
                 if value.toPlainText() == path.name)
    assert value.document().firstBlock().layout().lineCount() > 1
    assert value.document().size().height() <= value.viewport().height()
    value.setFocus()
    value.selectAll()
    QTest.keySequence(value, QKeySequence(QKeySequence.StandardKey.Copy))
    assert app.clipboard().text() == path.name


def test_toolbar_click_does_not_target_the_thumbnail_selection(app, window, tmp_path, monkeypatch):
    first, second = (tmp_path / name for name in ("1.png", "2.png"))
    for path in (first, second):
        Image.new("RGB", (8, 8)).save(path)
    window.open_file(first)
    finish_read(app, window)
    view = window.thumbnail_list
    view.selectAll()
    deleted = []
    monkeypatch.setattr(window, "trash_files", deleted.append)

    QTest.mouseClick(window.plus_button, Qt.MouseButton.LeftButton)
    QTest.keySequence(app.focusWidget(), QKeySequence(QKeySequence.StandardKey.Delete))
    assert deleted == []

    QTest.mouseClick(window.favorite_button, Qt.MouseButton.LeftButton)
    assert window.canvas.hasFocus() and view.selected_paths() == [first, second]
    QTest.keySequence(window.canvas, QKeySequence(QKeySequence.StandardKey.Delete))
    assert deleted == [[first]]


def test_paste_in_bundled_samples_keeps_cut_photo_on_clipboard(app, window, tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    window.sample_path = samples / "demo.jpg"
    photo = tmp_path / "original.jpg"
    for path in (window.sample_path, photo):
        Image.new("RGB", (8, 8)).save(path)
    window.open_sample()
    finish_read(app, window)
    write_file_clipboard(app.clipboard(), [photo], cut=True)
    snapshot = read_file_clipboard(app.clipboard())

    QTest.keyClick(window.thumbnail_list, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    wait_until(app, lambda: not window._file_busy)
    assert photo.is_file() and not (samples / photo.name).exists()
    assert read_file_clipboard(app.clipboard()) == snapshot
    assert "目标文件夹" in window.statusBar().currentMessage()
    assert window.statusBar().toolTip() == window.statusBar().currentMessage()


@pytest.fixture
def fake_trash(tmp_path, monkeypatch):
    trash = tmp_path / "回收站"
    trash.mkdir()

    class TestTrashFile:
        def __init__(self, name):
            self.path = Path(name)

        def moveToTrash(self):
            self.path = self.path.rename(trash / self.path.name)
            return True

        def fileName(self):
            return str(self.path)

    monkeypatch.setattr("hifine.trash.QFile", TestTrashFile)
    monkeypatch.setattr("hifine.trash._info_path", lambda path: None)
    return trash


def test_trash_selection_then_paste_in_empty_folder(app, window, tmp_path, monkeypatch, fake_trash):
    folder = tmp_path / "照片"
    trash = fake_trash
    folder.mkdir()
    photos = [folder / f"{i}.png" for i in (1, 2)]
    for path in photos:
        Image.new("RGB", (8, 8)).save(path)
    window.open_file(photos[0])
    finish_read(app, window)
    view = window.thumbnail_list
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

    errors = []
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: errors.append(dialog.text()))
    answers = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: next(answers))
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.selected_paths() == photos and all(path.exists() for path in photos)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    wait_until(app, lambda: window.current_path is None or errors)
    assert not errors
    assert all((trash / path.name).exists() for path in photos)

    write_file_clipboard(app.clipboard(), [trash / photos[1].name])
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    wait_until(app, lambda: window.current_path == photos[1] and not window._reads.loading)
    assert view.selected_paths() == [photos[1]]


def test_trash_range_continues_with_next_surviving_photo(app, window, tmp_path, monkeypatch, fake_trash):
    photos = [tmp_path / f"{n}.jpg" for n in range(5)]
    for path in photos:
        Image.new("RGB", (8, 8)).save(path)
    window.open_file(photos[1])
    finish_read(app, window)
    view = window.thumbnail_list
    view.set_selected_paths(photos[:2])
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    wait_until(app, lambda: window.files == photos[2:] and not window._reads.loading)
    assert window._displayed_path == photos[2]


def test_canvas_delete_uses_displayed_photo_and_undo(app, window, tmp_path, monkeypatch, fake_trash):
    photos = [tmp_path / f"{i}.png" for i in range(3)]
    for path in photos:
        Image.new("RGB", (16, 16), "red").save(path)
    trash = fake_trash
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("unexpected confirmation"))
    window.open_file(photos[1])
    finish_read(app, window)
    window.thumbnail_list.selectAll()
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton)
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    wait_until(app, lambda: window._displayed_path == photos[2])
    assert window.files == [photos[0], photos[2]]
    assert window.undo_trash_button.isVisible()
    QTest.mouseClick(window.undo_trash_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: window.files == photos)
    assert window.current_path == photos[2] and not window.undo_trash_button.isVisible()
    assert not list(trash.iterdir())
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    wait_until(app, lambda: window._displayed_path == photos[1])
    undo = QKeySequence(QKeySequence.StandardKey.Undo)
    QTest.keySequence(window.canvas, undo)
    wait_until(app, lambda: window.files == photos)
    assert not list(trash.iterdir())


def test_canvas_menu_uses_visible_pixels_during_navigation(app, window, blocked_prefetch, monkeypatch):
    slow, release, _ = blocked_prefetch
    displayed = window.current_path
    calls = []
    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda parent, path, pos: calls.append(path))
    window.navigate(1)
    assert window.current_path == slow
    request_menu(app, window.canvas, window.canvas.rect().center())
    window._show_loading()
    request_menu(app, window.canvas, window.canvas.rect().center())
    assert calls == [[displayed]]
    release.set()
    finish_read(app, window)


def test_finder_menu_reveals_only_when_chosen(app, window, tmp_path, monkeypatch):
    photo = tmp_path / "图片 #01.png"
    photo.touch()
    monkeypatch.setattr(file_menu, "sys", SimpleNamespace(platform="darwin"))
    launched = []

    def launch(program, args):
        launched.append((program, args))
        return True, 1

    monkeypatch.setattr(file_menu.QProcess, "startDetached", launch)
    pos = window.mapToGlobal(QPoint(30, 30))
    QTimer.singleShot(0, lambda: app.activePopupWidget().close())
    assert not file_menu.show_file_menu(window, photo, pos)
    assert not launched

    def choose_reveal():
        menu = app.activePopupWidget()
        menu.setActiveAction(menu.actions()[0])
        QTest.keyClick(menu, Qt.Key.Key_Return)

    QTimer.singleShot(0, choose_reveal)
    assert file_menu.show_file_menu(window, photo, pos)
    assert launched == [("/usr/bin/open", ["-R", str(photo)])]


def test_rename_and_delete_after_menu_closes(app, window, tmp_path, monkeypatch):
    first, second, renamed = [tmp_path / name for name in ("01.png", "02.png", "末尾.png")]
    for path in (first, second):
        Image.new("RGB", (64, 32)).save(path)
    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda *args: True)
    window.open_file(first)
    finish_read(app, window, prefetch=True)
    center = window.canvas.rect().center()
    request_menu(app, window.canvas, center)
    first.rename(renamed)
    wait_until(app, lambda: window.current_path == renamed and not window._reads.loading)
    assert window.files == [second, renamed]
    assert window.thumbnail_list.currentIndex().data() == renamed.name

    upper = renamed.with_suffix(".PNG")
    renamed.rename(upper)
    wait_until(app, lambda: window.current_path.name == upper.name and not window._reads.loading)
    renamed = upper

    window.canvas.set_zoom(2)
    view = window.thumbnail_list
    request_menu(app, view.viewport(), view.visualRect(view.model().index(0, 0)).center())
    second.unlink()
    wait_until(app, lambda: window.files == [renamed])
    assert window.canvas.zoom() == 2
    request_menu(app, window.canvas, center)
    renamed.unlink()
    wait_until(app, lambda: window.current_path is None)
    assert window.stage.currentWidget() is window.state
    assert view.model().rowCount() == 0
    assert not window.next_button.isEnabled()
    assert not window.reveal_button.isEnabled()


@pytest.mark.parametrize("save_method", ["atomic", "file-removed", "folder-empty"])
def test_menu_edit_reloads_a_replaced_file(app, window, tmp_path, monkeypatch, save_method):
    photo = tmp_path / "照片.png"
    edited = tmp_path / "edited.tmp"
    Image.new("RGB", (64, 32), "red").save(photo)
    Image.new("RGB", (80, 40), "blue").save(edited, "PNG")
    window.open_file(photo)
    finish_read(app, window)
    wait_until(app, lambda: thumbnail_color(window.thumbnail_list.currentIndex()) == "#ff0000")
    monkeypatch.setattr("hifine.viewer.show_file_menu", lambda *args: True)
    window._menu_refresh.setInterval(250)
    request_menu(app, window.canvas, window.canvas.rect().center())
    assert str(photo) in window._menu_watch.files()
    if save_method == "atomic":
        edited.replace(photo)
    else:
        photo.unlink()
        wait_until(app, lambda: str(photo) not in window._menu_watch.files())
        if save_method == "folder-empty":
            wait_until(app, lambda: window.current_path is None)
        photo.write_bytes(edited.read_bytes())
    wait_until(app, lambda: window.canvas._image.size().toTuple() == (80, 40))
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    assert window.current_path == photo
    assert str(photo) in window._menu_watch.files()
    wait_until(app, lambda: thumbnail_color(window.thumbnail_list.currentIndex()) == "#0000ff")


def test_thumbnail_click_and_keyboard_follow_the_same_selection(app, window, tmp_path):
    first, middle, last = [tmp_path / f"照片{i}.png" for i in (1, 2, 10)]
    for path, color in ((last, "blue"), (first, "red"), (middle, "lime")):
        Image.new("RGB", (32, 16), color).save(path)
    window.open_file(first)
    finish_read(app, window)

    view = window.thumbnail_list
    model = view.model()
    assert view.isVisible()
    assert view.mapTo(window, view.rect().topRight()).x() < window.stage.mapTo(window, QPoint()).x()
    rows = [model.index(row, 0) for row in range(model.rowCount())]
    assert [row.data() for row in rows] == [first.name, middle.name, last.name]
    assert view.selectionModel().selectedIndexes() == [rows[0]]

    wait_until(app, lambda: thumbnail_color(rows[2]) == "#0000ff")
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualRect(rows[2]).center())
    finish_read(app, window)
    assert window.current_path == last
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    assert view.selectionModel().selectedIndexes() == [rows[2]]

    QTest.keyClick(app.focusWidget() or window, Qt.Key.Key_Left)
    finish_read(app, window)
    assert window.current_path == middle
    assert window.canvas._image.pixelColor(0, 0).green() == 255
    assert view.currentIndex() == rows[1]
    assert view.selectionModel().selectedIndexes() == [rows[1]]


def test_opening_folder_scrolls_to_selection_and_replaces_thumbnail_list(app, window, tmp_path):
    paths = [tmp_path / f"{i}.png" for i in range(18)]
    for path in paths:
        Image.new("RGB", (8, 8), "red").save(path)
    window.open_file(paths[-1])
    finish_read(app, window)
    view = window.thumbnail_list
    assert view.currentIndex().row() == len(paths) - 1
    wait_until(app, lambda: view.viewport().rect().contains(
        view.visualRect(view.currentIndex()).center()))
    wait_until(app, lambda: thumbnail_color(view.currentIndex()) == "#ff0000")

    other = tmp_path / "other" / paths[-1].name
    other.parent.mkdir()
    Image.new("RGB", (8, 8), "blue").save(other)
    window.open_file(other)
    finish_read(app, window)
    assert view.model().rowCount() == 1
    current = view.currentIndex()
    assert current.row() == 0
    assert current.data() == other.name
    assert view.selectionModel().selectedIndexes() == [current]
    assert window.current_path == other
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    wait_until(app, lambda: thumbnail_color(current) == "#0000ff")


def test_keyboard_navigation_details_and_bad_image(app, window, tmp_path):
    first, second, bad = (tmp_path / name for name in ("图1.png", "图2.png", "图10.jpg"))
    Image.new("RGB", (13, 7), "red").save(first)
    Image.new("RGBA", (7, 4), (10, 25, 45, 125)).save(second)
    bad.write_bytes(b"broken")
    window.open_file(first)
    finish_read(app, window)
    assert window.position.text() == "1 / 3"
    assert not window.prev_button.isEnabled()
    assert window.canvas._image.pixelColor(0, 0).red() == 255
    window.thumbnail_list.setFocus()
    QTest.keyClick(window.thumbnail_list, Qt.Key.Key_Tab)
    assert window.thumbnail_list.hasFocus() and not window.info_panel.isVisible()
    window.info_button.setFocus()
    QTest.keyClick(window.info_button, Qt.Key.Key_Tab)
    assert window.info_button.hasFocus() and window.info_panel.isVisible()
    QTest.keyClick(window.info_button, Qt.Key.Key_F6)
    assert not window.info_button.hasFocus()
    QTest.keyClick(app.focusWidget(), Qt.Key.Key_F6, Qt.KeyboardModifier.ShiftModifier)
    assert window.info_button.hasFocus() and window.info_panel.isVisible()
    QTest.keyClick(window.info_button, Qt.Key.Key_Space)
    assert not window.info_panel.isVisible()
    QTest.keyClick(window.info_button, Qt.Key.Key_Space)
    assert window.info_panel.isVisible()
    window.settings_button.setFocus()
    QTest.keyClick(window.settings_button, Qt.Key.Key_Right)
    QTest.keyClick(window.settings_button, Qt.Key.Key_Down)
    finish_read(app, window)
    assert window.current_path == bad
    assert window.state_title.text() == "无法打开这张图片"
    assert not window.next_button.isEnabled()
    QTest.keyClick(window.settings_button, Qt.Key.Key_Up)
    finish_read(app, window)
    assert window.current_path == second
    assert window.canvas._image.pixelColor(0, 0).alpha() == 125
    assert window.position.text() == "2 / 3"
    QTest.keyClick(window, Qt.Key.Key_F11)
    assert window.isFullScreen()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isFullScreen()


def test_toolbar_and_enter_reveal_the_current_file(app, window, tmp_path, monkeypatch):
    revealed = []
    monkeypatch.setattr("hifine.viewer.reveal_files", lambda parent, paths: revealed.extend(paths))
    assert not window.reveal_button.isEnabled()
    for button in window.findChildren(QAbstractButton):
        assert "打开图片" not in (button.text(), button.accessibleName())
    assert window.settings_button.text() == ""
    assert not window.settings_button.icon().isNull()
    assert "设置" in window.settings_button.accessibleName()
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert revealed == []

    first, second = (tmp_path / name for name in ("1.png", "2.png"))
    for photo in (first, second):
        Image.new("RGB", (8, 8)).save(photo)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(first), ""))
    QTest.keySequence(window, QKeySequence(QKeySequence.StandardKey.Open))
    finish_read(app, window)
    assert window.current_path == first
    button = window.reveal_button
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    view = window.thumbnail_list
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.keyClick(view, Qt.Key.Key_Right)
    QTest.keyClick(view, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
    finish_read(app, window)
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    window.info_button.setFocus()
    QTest.keyClick(window.info_button, Qt.Key.Key_Return)
    assert revealed == [first, first, second, second]


def test_neighbors_are_decoded_before_navigation_and_reused(app, window, tmp_path, monkeypatch):
    first, middle, last = [tmp_path / f"{i}.png" for i in range(3)]
    for path, shade in ((first, 40), (middle, 80), (last, 120)):
        Image.new("L", (8, 8), shade).save(path)
    decoded = []
    load_image = reader.load_image

    def record(path, **options):
        decoded.append(path)
        return load_image(path, **options)

    monkeypatch.setattr(reader, "load_image", record)
    window.open_file(middle)
    finish_read(app, window, prefetch=True)
    assert decoded == [middle, last, first]
    assert window.canvas._image.pixelColor(0, 0).red() == 80
    for key, shade in ((Qt.Key.Key_Left, 40), (Qt.Key.Key_Right, 80),
                       (Qt.Key.Key_Down, 120), (Qt.Key.Key_Up, 80)):
        QTest.keyClick(window.thumbnail_list, key)
        finish_read(app, window, prefetch=True)
        assert window.canvas._image.pixelColor(0, 0).red() == shade
    assert len(decoded) == 3


def test_oversized_neighbor_decodes_only_when_selected(app, window, tmp_path, monkeypatch):
    first, large = tmp_path / "1.png", tmp_path / "2.png"
    Image.new("RGB", (1, 1), "red").save(first)
    Image.new("RGB", (20, 20), "blue").save(large)
    window._reads._cache.max_bytes = 64
    decoded = []
    load_image = reader.load_image

    def record(path, **options):
        loaded = load_image(path, **options)
        decoded.append(path)
        return loaded

    monkeypatch.setattr(reader, "load_image", record)
    window.open_file(first)
    finish_read(app, window, prefetch=True)
    assert decoded == [first]
    QTest.keyClick(window, Qt.Key.Key_Right)
    finish_read(app, window)
    assert decoded == [first, large]
    assert window.canvas._image.pixelColor(0, 0).blue() == 255


def test_prefetched_file_can_be_replaced_or_deleted(app, window, tmp_path):
    first, second = tmp_path / "1.png", tmp_path / "2.png"
    Image.new("RGB", (8, 8), "red").save(first)
    Image.new("RGB", (8, 8), "lime").save(second)
    window.open_file(first)
    finish_read(app, window, prefetch=True)
    second_row = window.thumbnail_list.model().index(1, 0)
    wait_until(app, lambda: thumbnail_color(second_row) == "#00ff00")

    replacement = tmp_path / "replacement.tmp"
    Image.new("RGB", (32, 16), "blue").save(replacement, format="PNG")
    replacement.replace(second)
    QTest.keyClick(window, Qt.Key.Key_Right)
    finish_read(app, window)
    assert window.canvas._image.size().toTuple() == (32, 16)
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    wait_until(app, lambda: thumbnail_color(second_row) == "#0000ff")

    QTest.keyClick(window, Qt.Key.Key_Left)
    finish_read(app, window, prefetch=True)
    second.unlink()
    QTest.keyClick(window, Qt.Key.Key_Right)
    finish_read(app, window)
    assert window.stage.currentWidget() is window.state
    assert window.state_title.text() == "无法打开这张图片"
    assert window.canvas._image.isNull()
    wait_until(app, lambda: second_row.data(Qt.ItemDataRole.DecorationRole) == QImage())


@pytest.fixture
def decoder_gates(monkeypatch):
    gates = {}
    reads = []
    load_image = reader.load_image

    def pause(path):
        gates[path] = (Event(), Event())
        return gates[path]

    def slow_read(path, **options):
        reads.append(path)
        if path in gates:
            started, release = gates[path]
            started.set()
            assert release.wait(15), "timed out waiting to release the decoder"
        return load_image(path, **options)

    monkeypatch.setattr(reader, "load_image", slow_read)
    try:
        yield pause, reads
    finally:
        for _, release in gates.values():
            release.set()


@pytest.fixture
def blocked_prefetch(app, window, tmp_path, decoder_gates):
    first, slow = tmp_path / "1.png", tmp_path / "2.png"
    Image.new("RGB", (8, 8), "red").save(first)
    Image.new("RGB", (8, 8), "lime").save(slow)
    pause, reads = decoder_gates
    started, release = pause(slow)
    window.open_file(first)
    wait_until(app, started.is_set)
    return slow, release, reads


def test_navigation_joins_inflight_prefetch(app, window, blocked_prefetch):
    slow, release, reads = blocked_prefetch
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert window.current_path == slow
    release.set()
    finish_read(app, window, prefetch=True)
    assert reads.count(slow) == 1
    assert window.canvas._image.pixelColor(0, 0).green() == 255


@pytest.mark.parametrize(("old_mib", "new_mib"), [(1, 2), (2, 1)])
def test_resizing_cache_during_prefetch(app, window, tmp_path, decoder_gates, old_mib, new_mib):
    first, neighbor = tmp_path / "1.png", tmp_path / "2.png"
    Image.new("RGB", (8, 8), "red").save(first)
    Image.new("RGB", (640, 640), "blue").save(neighbor)
    pause, reads = decoder_gates
    started, release = pause(neighbor)
    window._reads.set_cache_limits(max_entries=8, max_bytes=old_mib * 1024**2)
    window.open_file(first)
    wait_until(app, started.is_set)
    window._reads.set_cache_limits(max_entries=8, max_bytes=new_mib * 1024**2)
    release.set()
    finish_read(app, window, prefetch=True)

    fits = new_mib == 2
    assert (neighbor in window._reads._cache) == fits
    assert reads.count(neighbor) == (2 if fits else 1)
    window.navigate(1)
    finish_read(app, window)
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    assert reads.count(neighbor) == 2


def test_skip_over_inflight_neighbor_keeps_its_pixels(app, window, tmp_path, decoder_gates):
    first, middle, last = [tmp_path / f"{i}.png" for i in range(3)]
    for path, color in ((first, "red"), (middle, "lime"), (last, "blue")):
        Image.new("RGB", (8, 8), color).save(path)
    pause, reads = decoder_gates
    middle_started, release_middle = pause(middle)
    last_started, release_last = pause(last)
    window.open_file(first)
    wait_until(app, middle_started.is_set)
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    wait_until(app, last_started.is_set)
    release_middle.set()
    wait_until(app, lambda: all(job.path != middle for job in window._reads._active.values()))
    release_last.set()
    finish_read(app, window, prefetch=True)
    assert window.current_path == last
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    QTest.keyClick(window, Qt.Key.Key_Left)
    finish_read(app, window, prefetch=True)
    assert window.canvas._image.pixelColor(0, 0).green() == 255
    assert reads.count(middle) == 1


def test_file_replaced_after_prefetch_before_result_delivery(app, window, tmp_path, blocked_prefetch):
    slow, release, _ = blocked_prefetch
    release.set()
    # Leave the completed prefetch's queued Qt signal pending on the GUI thread.
    assert window._reads._pool.waitForDone(5000)
    assert window._reads._active
    replacement = tmp_path / "replacement.tmp"
    Image.new("RGB", (32, 16), "blue").save(replacement, format="PNG")
    replacement.replace(slow)
    window.navigate(1)
    finish_read(app, window)
    assert window.canvas._image.size().toTuple() == (32, 16)
    assert window.canvas._image.pixelColor(0, 0).blue() == 255


def test_new_folder_opens_while_old_prefetch_is_blocked(app, window, tmp_path, blocked_prefetch):
    _, release, _ = blocked_prefetch
    other = tmp_path / "other" / "1.png"
    other.parent.mkdir()
    Image.new("RGB", (8, 8), "blue").save(other)
    window.open_file(other)
    finish_read(app, window)
    assert window.canvas._image.pixelColor(0, 0).blue() == 255
    release.set()
    finish_read(app, window, prefetch=True)
    assert window.files == [other]
    assert window.current_path == other
    assert window.canvas._image.pixelColor(0, 0).blue() == 255


def test_pointer_anchored_zoom_and_drag(app, window, tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (3200, 2400), "darkgreen").save(path)
    window.open_file(path)
    finish_read(app, window)
    canvas = window.canvas
    QTest.keyClick(window, Qt.Key.Key_1)
    assert canvas.zoom() == 1
    center = QPointF(canvas.width() / 2, canvas.height() / 2)
    anchor = center + QPointF(40, 20)
    wheel = QWheelEvent(anchor, canvas.mapToGlobal(anchor), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(canvas, wheel)
    assert canvas.zoom() == pytest.approx(1.2)
    assert canvas._offset.x() == pytest.approx(-8)
    assert canvas._offset.y() == pytest.approx(-4)
    start = QPoint(100, 110)
    end = QPoint(150, 140)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas._offset == QPointF(42, 26)
    QTest.keyClick(window, Qt.Key.Key_0)
    assert canvas.zoom() == canvas.fit_zoom()
    assert canvas._offset.isNull()
    canvas.set_zoom(32)
    assert window.zoom_button.text() == "3200%"
    wait_until(app, lambda: window.zoom_button.width() >= window.zoom_button.sizeHint().width())


@pytest.mark.parametrize("keep_view", [False, True])
def test_navigation_zoom_and_position(app, window, tmp_path, decoder_gates, keep_view):
    first, second, tiny = [tmp_path / f"{i}.png" for i in range(3)]
    Image.new("RGB", (800, 600)).save(first)
    Image.new("RGB", (600, 900)).save(second)
    Image.new("RGB", (16, 16)).save(tiny)
    pause, _ = decoder_gates
    started, release = pause(second)
    window._apply_settings(AppSettings(keep_zoom_position=keep_view))
    window.open_file(first)
    wait_until(app, started.is_set)
    canvas = window.canvas
    canvas.set_zoom(4)
    start = canvas.rect().center()
    end = start + QPoint(32, 20)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas._offset == QPointF(32, 20)

    QTest.keyClick(window, Qt.Key.Key_Right)
    wait_until(app, lambda: window.state.isVisible())
    release.set()
    finish_read(app, window)
    assert window.current_path == second
    if keep_view:
        assert canvas.zoom() == 4
        assert canvas._offset == QPointF(24, 30)
    else:
        assert window.fit_button.isChecked()
        assert canvas._offset.isNull()

    window.navigate(1)
    finish_read(app, window)
    assert window.current_path == tiny
    assert canvas._offset.isNull()
    window.navigate(-1)
    finish_read(app, window)
    assert canvas._offset == (QPointF(24, 30) if keep_view else QPointF())
    # Opening another file explicitly starts a fresh view, including in this folder.
    window.open_file(first)
    finish_read(app, window)
    assert window.fit_button.isChecked()
    window.navigate(1)
    finish_read(app, window)
    assert window.fit_button.isChecked()


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_animated_playback_keeps_zoom(app, window, tmp_path, extension):
    path = tmp_path / f"01.{extension}"
    frames = [Image.new("RGB", (320, 240), color) for color in ("red", "lime")]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=140, loop=0,
                   lossless=True)
    frames[0].save(tmp_path / "02.png")
    window.open_file(path)
    finish_read(app, window)
    assert window._movie.state() == QMovie.MovieState.Running
    assert window.play_button.isVisible()
    window.canvas.set_zoom(6.0, QPointF(80, 60))
    offset = QPointF(window.canvas._offset)
    deadline = monotonic() + 3
    while window.canvas._image.pixelColor(0, 0).green() < 200:
        assert monotonic() < deadline, "the second frame never reached the canvas"
        app.processEvents()
        sleep(0.005)
    assert window.canvas.zoom() == 6.0
    assert window.canvas._offset == offset
    window.thumbnail_list.setFocus()
    QTest.keyClick(window.thumbnail_list, Qt.Key.Key_Space)
    assert window._movie.state() == QMovie.MovieState.Paused
    QTest.qWait(200)
    assert window.canvas._image.pixelColor(0, 0).green() > 200
    window.info_button.setFocus()
    QTest.keyClick(window.info_button, Qt.Key.Key_Space)
    assert not window.info_panel.isVisible()
    assert window._movie.state() == QMovie.MovieState.Paused
    window.play_button.click()
    assert window._movie.state() == QMovie.MovieState.Running
    QTest.keyClick(window, Qt.Key.Key_Right)
    finish_read(app, window)
    assert window._movie is None
    assert not window.play_button.isVisible()
    QTest.keyClick(window, Qt.Key.Key_Left)
    finish_read(app, window)
    assert window._movie.state() == QMovie.MovieState.Running
    assert window.play_button.isVisible()


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_playing_image_can_be_moved(app, window, tmp_path, extension):
    photo = tmp_path / f"动画.{extension}"
    frames = [Image.new("RGB", (16, 8), color) for color in ("red", "lime")]
    frames[0].save(photo, save_all=True, append_images=frames[1:], duration=140, loop=0, lossless=True)
    window.open_file(photo)
    finish_read(app, window)
    movie = window._movie
    assert movie.state() == QMovie.MovieState.Running
    photo.rename(tmp_path / f"moved.{extension}")
    frame = movie.currentFrameNumber()
    wait_until(app, lambda: movie.currentFrameNumber() != frame)
    assert movie.state() == QMovie.MovieState.Running
