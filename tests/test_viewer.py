"""Exercise the viewer through Qt key, wheel and pointer events."""

import os
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

from PIL import Image
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QImage, QMovie, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit

from hifine import file_menu, reader
from hifine.app import SAMPLE
from hifine.settings import AppSettings
from hifine.viewer import MainWindow


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def settings_store(tmp_path):
    return QSettings(str(tmp_path / "hifine.ini"), QSettings.Format.IniFormat)


@pytest.fixture()
def window(app, settings_store):
    widget = MainWindow(sample_path=SAMPLE, settings_store=settings_store)
    widget.show()
    widget.activateWindow()
    app.processEvents()
    yield widget
    widget.close()
    widget._reads._pool.waitForDone()


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


def test_settings_save_cancel_and_reopen(app, window, settings_store, tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (32, 16), "red").save(photo)
    window.open_file(photo)
    finish_read(app, window)
    window.canvas.set_zoom(2)
    initial = []

    def edit(entries, mib, cdk, button):
        dialog = app.activeModalWidget()
        initial.append((dialog.cache_max_entries.value(), dialog.cache_max_mib.value(),
                        dialog.mirrorchyan_cdk.text(), dialog.mirrorchyan_cdk.echoMode()))
        dialog.cache_max_entries.setValue(entries)
        dialog.cache_max_mib.setValue(mib)
        dialog.mirrorchyan_cdk.setText(cdk)
        QTest.mouseClick(dialog.buttons.button(button), Qt.MouseButton.LeftButton)

    buttons = QDialogButtonBox.StandardButton
    QTimer.singleShot(0, lambda: edit(3, 64, " example-cdk ", buttons.Save))
    QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
    assert AppSettings.load(settings_store) == AppSettings(3, 64, "example-cdk")
    cache = window._reads._cache
    assert (cache.max_entries, cache.max_bytes) == (3, 64 * 1024**2)
    assert window.current_path == photo and window.canvas.zoom() == 2

    QTimer.singleShot(0, lambda: edit(1, 1, "", buttons.Cancel))
    QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
    masked = QLineEdit.EchoMode.Password
    assert initial == [(8, 256, "", masked), (3, 64, "example-cdk", masked)]
    assert (cache.max_entries, cache.max_bytes) == (3, 64 * 1024**2)

    reopened = MainWindow(settings_store=QSettings(settings_store.fileName(), QSettings.Format.IniFormat))
    try:
        cache = reopened._reads._cache
        assert (cache.max_entries, cache.max_bytes) == (3, 64 * 1024**2)
        assert reopened._settings.mirrorchyan_cdk == "example-cdk"
    finally:
        reopened.close()


def test_file_menu_uses_the_hit_image_and_preserves_selection(app, window, tmp_path, monkeypatch):
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
    assert calls == [(first, canvas.mapToGlobal(center)), (second, view.viewport().mapToGlobal(other))]
    assert window.current_path == first
    assert view.selectionModel().selectedIndexes() == [view.model().index(0, 0)]


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
    assert calls == [displayed]
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
    QTest.keyClick(window, Qt.Key.Key_Tab)
    assert not window.info_panel.isVisible()
    QTest.keyClick(window, Qt.Key.Key_Tab)
    assert window.info_panel.isVisible()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    finish_read(app, window)
    assert window.current_path == bad
    assert window.state_title.text() == "无法打开这张图片"
    assert not window.next_button.isEnabled()
    QTest.keyClick(window, Qt.Key.Key_Left)
    finish_read(app, window)
    assert window.current_path == second
    assert window.canvas._image.pixelColor(0, 0).alpha() == 125
    assert window.position.text() == "2 / 3"
    QTest.keyClick(window, Qt.Key.Key_F11)
    assert window.isFullScreen()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isFullScreen()


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
                       (Qt.Key.Key_Right, 120), (Qt.Key.Key_Left, 80)):
        QTest.keyClick(window, key)
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


def test_pointer_anchored_zoom_and_drag(app, window):
    canvas = window.canvas
    window.stage.setCurrentWidget(canvas)
    image = QImage(3200, 2400, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkGreen)
    canvas.set_image(image)
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
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window._movie.state() == QMovie.MovieState.Paused
    QTest.qWait(200)
    assert window.canvas._image.pixelColor(0, 0).green() > 200
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
