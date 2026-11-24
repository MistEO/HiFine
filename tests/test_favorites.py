from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from hifine.favorites import FavoriteStore
from hifine.thumbnails import ThumbnailList


def test_browsing_does_not_create_database(tmp_path):
    database = tmp_path / "settings" / "favorites.sqlite3"
    store = FavoriteStore(database)
    path = tmp_path / "photo.png"
    assert store.in_folder(tmp_path) == set()
    store.move_stars({path: path.with_name("new.png")})
    store.set_favorite(path, False)
    assert not database.parent.exists()


def test_stars_are_persistent_and_scoped_to_absolute_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "settings" / "favorites.sqlite3"
    first = FavoriteStore(database)
    second = FavoriteStore(database)
    a = Path("春") / "01.png"
    b = Path("秋") / "01.png"
    first.set_favorite(a, True)
    second.set_favorite(b, True)
    first.set_favorite(Path("春") / ".." / a, True)
    assert second.in_folder(a.parent) == {tmp_path / a}
    assert first.in_folder(b.parent) == {tmp_path / b}
    second.set_favorite(a, False)
    assert first.in_folder(a.parent) == set()
    assert FavoriteStore(database).in_folder(b.parent) == {tmp_path / b}


def test_rename_preserves_only_existing_stars(tmp_path):
    store = FavoriteStore(tmp_path / "db")
    source = tmp_path / "photo.png"
    target = tmp_path / "elsewhere" / "new.png"
    store.set_favorite(source, True)
    store.move_stars({source: target})
    assert store.in_folder(source.parent) == set()
    assert store.in_folder(target.parent) == {target}
    store.move_stars({source: tmp_path / "unmarked.png"})
    assert store.in_folder(source.parent) == set()
    upper = target.with_name(target.name.upper())
    store.move_stars({target: upper})
    assert [p.name for p in store.in_folder(target.parent)] == [upper.name]


def test_batch_moves_transfer_original_stars_even_when_paths_overlap(tmp_path):
    a, b, c, d, e = [tmp_path / name for name in ("a", "b", "c", "d", "e")]
    store = FavoriteStore(tmp_path / "db")
    store.set_favorite(a, True)
    store.set_favorite(d, True)
    store.set_favorite(e, True)
    store.move_stars({a: b, b: c, c: d, d: a, e: e})
    assert store.in_folder(tmp_path) == {a, b, e}


def test_simultaneous_windows_preserve_independent_stars(tmp_path):
    database = tmp_path / "db"
    first, second = (tmp_path / name for name in ("01.png", "02.png"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(FavoriteStore(database).set_favorite, photo, True)
                   for photo in (first, second, first)]
        for future in futures:
            future.result()
    assert FavoriteStore(database).in_folder(tmp_path) == {first, second}


def test_database_error_is_reported_without_touching_the_photo(tmp_path):
    database = tmp_path / "broken"
    database.write_bytes(b"invalid sqlite database")
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"photo")
    store = FavoriteStore(database)
    with pytest.raises(OSError):
        store.set_favorite(photo, True)
    with pytest.raises(OSError):
        store.in_folder(tmp_path)
    assert photo.read_bytes() == b"photo"


def test_thumbnail_marks_preserve_selection_and_follow_files(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    view = ThumbnailList()
    files = [tmp_path / "a.png", tmp_path / "b.png"]
    view.set_files(files)
    view.selectAll()
    view.set_favorites({files[1]})
    model = view.model()
    assert model.index(0).data(Qt.ItemDataRole.AccessibleTextRole) == "a.png"
    assert model.index(1).data(Qt.ItemDataRole.AccessibleTextRole) == "b.png · 已加星标"
    assert view.selected_paths() == files
    view.set_files(list(reversed(files)))
    assert model.index(0).data(Qt.ItemDataRole.ToolTipRole) == "b.png · 已加星标"
    view.set_favorites([])
    assert model.index(0).data(Qt.ItemDataRole.ToolTipRole) == "b.png"
    view.close()
    view.shutdown()
    app.processEvents()
