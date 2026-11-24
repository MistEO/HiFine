import os

from PIL import Image
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from hifine.thumbnails import ThumbnailList


@pytest.fixture
def thumbnails(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    files = [tmp_path / f"{row}.png" for row in range(5)]
    for path in files:
        Image.new("RGB", (8, 8)).save(path)
    view = ThumbnailList()
    view.resize(150, 650)
    view.show()
    view.set_files(files)
    view.select_row(0)
    app.processEvents()
    yield view, files
    view.close()
    view.shutdown()


def point_for(view, row):
    return view.visualRect(view.model().index(row, 0)).center()


def click(view, row, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifiers, point_for(view, row))


def test_thumbnail_selection_gestures(thumbnails):
    view, files = thumbnails
    ctrl = Qt.KeyboardModifier.ControlModifier
    click(view, 3, ctrl)
    click(view, 1, ctrl)
    assert view.selected_paths() == [files[0], files[1], files[3]]
    assert view.currentIndex().row() == 1
    view.select_row(1)
    click(view, 0, ctrl)
    assert view.selected_paths() == [files[1], files[3]]
    click(view, 4)
    assert view.selected_paths() == [files[4]]
    click(view, 1, Qt.KeyboardModifier.ShiftModifier)
    assert view.selected_paths() == files[1:]
    QTest.keyClick(view, Qt.Key.Key_A, ctrl)
    assert view.selected_paths() == files


def test_context_menu_uses_whole_selection_without_navigating(thumbnails):
    view, files = thumbnails
    click(view, 2, Qt.KeyboardModifier.ControlModifier)
    requests = []
    view.file_menu_requested.connect(lambda paths, point: requests.append(paths))

    def menu(row):
        point = point_for(view, row)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.RightButton, pos=point)
        QApplication.sendEvent(view.viewport(), QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, point, view.viewport().mapToGlobal(point)))

    menu(0)
    assert requests[-1] == [files[0], files[2]]
    menu(3)
    assert requests[-1] == [files[3]]
    assert view.currentIndex().row() == 2
    view.select_row(2)
    assert view.selected_paths() == [files[3]]
    point = point_for(view, 2)
    QApplication.sendEvent(view.viewport(), QContextMenuEvent(
        QContextMenuEvent.Reason.Keyboard, point, view.viewport().mapToGlobal(point)))
    assert requests[-1] == [files[3]]


def test_selection_survives_folder_refresh_by_path(thumbnails):
    view, files = thumbnails
    view.selectAll()
    selection = view.selected_paths()
    view.set_files(files[2:])
    view.select_row(0)
    view.set_selected_paths(selection)
    assert view.selected_paths() == files[2:]
    view.set_selected_paths([])
    view.select_row(0)
    assert view.currentIndex().row() == 0
    assert view.selected_paths() == []
