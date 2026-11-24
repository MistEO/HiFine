import errno
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QUrl

from hifine import file_clipboard
from hifine.file_clipboard import (
    clipboard_files, finish_file_paste, read_file_clipboard, transfer_files, write_file_clipboard,
)


class Clipboard:
    def __init__(self):
        self.mime = None

    def mimeData(self):
        return self.mime

    def setMimeData(self, mime):
        self.mime = mime

    def clear(self):
        self.mime = None


def test_copy_twice_with_name_collisions(tmp_path):
    clipboard = Clipboard()
    first, second, existing = [tmp_path / name for name in ("原图 #1.png", "图 2.HEIC", "原图 #1 (2).png")]
    for path in (first, second, existing):
        path.write_text(path.name, encoding="utf-8")
    write_file_clipboard(clipboard, [first, second])

    assert clipboard_files(clipboard) == [first, second]
    snapshot = read_file_clipboard(clipboard)
    for suffix in (3, 4):
        result = transfer_files(snapshot, tmp_path)
        finish_file_paste(clipboard, snapshot, result)
        assert not result.errors
        assert result.destinations == [tmp_path / f"原图 #1 ({suffix}).png", tmp_path / f"图 2 ({suffix - 1}).HEIC"]
        assert [p.read_text(encoding="utf-8") for p in result.destinations] == [first.name, second.name]
        assert clipboard_files(clipboard) == [first, second]
    assert existing.read_text(encoding="utf-8") == existing.name


@pytest.mark.parametrize("source_format", ["windows", "gnome", "kde"])
def test_external_cut_retains_failed_and_unsupported_items(tmp_path, source_format):
    clipboard = Clipboard()
    directory = tmp_path / "destination"
    directory.mkdir()
    ok, missing, notes = [tmp_path / name for name in ("图 #1.png", "missing.jpg", "notes.txt")]
    ok.write_bytes(b"original")
    notes.write_text("notes")
    (directory / ok.name).write_bytes(b"existing")
    urls = [QUrl.fromLocalFile(str(path)) for path in (ok, missing, notes)]
    mime = QMimeData()
    if source_format == "gnome":
        mime.setData("x-special/gnome-copied-files", b"cut\n" + b"\n".join(bytes(url.toEncoded()) for url in urls))
    else:
        mime.setUrls(urls)
        if source_format == "windows":
            mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b"\x02\0\0\0")
        else:
            mime.setData("application/x-kde-cutselection", b"1")
    clipboard.setMimeData(mime)
    snapshot = read_file_clipboard(clipboard)
    assert snapshot.cut and snapshot.paths == (ok, missing)
    result = transfer_files(snapshot, directory)
    finish_file_paste(clipboard, snapshot, result)

    assert result.destinations == [directory / "图 #1 (2).png"]
    assert len(result.errors) == 1 and missing.name in result.errors[0]
    assert result.destinations[0].read_bytes() == b"original"
    assert (directory / ok.name).read_bytes() == b"existing"
    assert not ok.exists() and notes.exists()
    assert clipboard.mimeData().urls() == urls[1:]
    assert read_file_clipboard(clipboard).cut
    assert clipboard_files(clipboard) == [missing]


def test_viewer_selection_includes_nonstandard_extensions_after_partial_cut(tmp_path):
    clipboard = Clipboard()
    directory = tmp_path / "destination"
    directory.mkdir()
    first, second = [tmp_path / name for name in ("first.photo", "second")]
    write_file_clipboard(clipboard, [first, second], cut=True)
    first.write_bytes(b"first image")
    snapshot = read_file_clipboard(clipboard)
    assert snapshot.paths == (first, second)
    result = transfer_files(snapshot, directory)
    finish_file_paste(clipboard, snapshot, result)
    assert result.destinations == [directory / first.name] and len(result.errors) == 1
    assert clipboard_files(clipboard) == [second]

    second.write_bytes(b"second image")
    snapshot = read_file_clipboard(clipboard)
    result = transfer_files(snapshot, directory)
    finish_file_paste(clipboard, snapshot, result)
    assert result.destinations == [directory / second.name] and not result.errors
    assert not clipboard_files(clipboard)


def test_cut_to_same_folder_and_clipboard_replacement(tmp_path):
    clipboard = Clipboard()
    source = tmp_path / "image.png"
    source.touch()
    write_file_clipboard(clipboard, [source], cut=True)
    snapshot = read_file_clipboard(clipboard)
    result = transfer_files(snapshot, tmp_path)
    assert result.destinations == [source] and list(tmp_path.iterdir()) == [source]
    finish_file_paste(clipboard, snapshot, result)
    assert not clipboard_files(clipboard)

    write_file_clipboard(clipboard, [source], cut=True)
    directory = tmp_path / "destination"
    directory.mkdir()
    result = transfer_files(snapshot, directory)
    clipboard.setMimeData(QMimeData())
    clipboard.mimeData().setText("copied during paste")
    finish_file_paste(clipboard, snapshot, result)
    assert clipboard.mimeData().text() == "copied during paste"


def test_failed_cross_volume_move_removes_partial_copy(tmp_path, monkeypatch):
    clipboard = Clipboard()
    source = tmp_path / "image.png"
    source.write_bytes(b"original")
    directory = tmp_path / "destination"
    directory.mkdir()
    write_file_clipboard(clipboard, [source], cut=True)
    snapshot = read_file_clipboard(clipboard)

    def cross_volume(*args):
        raise OSError(errno.EXDEV, "different volume")

    def interrupted_copy(src, dst, **kwargs):
        dst.write_bytes(b"partial")
        raise OSError("copy interrupted")

    monkeypatch.setattr(Path, "replace", cross_volume)
    monkeypatch.setattr(file_clipboard.shutil, "copy2", interrupted_copy)
    result = transfer_files(snapshot, directory)
    finish_file_paste(clipboard, snapshot, result)
    assert not result.destinations and len(result.errors) == 1
    assert not list(directory.iterdir()) and source.read_bytes() == b"original"
    assert read_file_clipboard(clipboard) == snapshot


def test_cross_volume_cut_avoids_directory_collision_and_keeps_partial_success(tmp_path, monkeypatch):
    clipboard = Clipboard()
    moved, changed = [tmp_path / name for name in ("image.png", "changed.jpg")]
    for path in (moved, changed):
        path.write_bytes(b"photo")
    directory = tmp_path / "destination"
    directory.mkdir()
    (directory / moved.name).mkdir()
    write_file_clipboard(clipboard, [moved, changed], cut=True)
    snapshot = read_file_clipboard(clipboard)
    replace, copy = Path.replace, file_clipboard.shutil.copy2

    def cross_volume(src, dst):
        if src.parent == tmp_path:
            raise OSError(errno.EXDEV, "different volume")
        return replace(src, dst)

    def copy_while_editing(src, dst, **kwargs):
        copy(src, dst, **kwargs)
        if src == changed:
            src.write_bytes(b"updated photo")

    monkeypatch.setattr(Path, "replace", cross_volume)
    monkeypatch.setattr(file_clipboard.shutil, "copy2", copy_while_editing)
    result = transfer_files(snapshot, directory)
    finish_file_paste(clipboard, snapshot, result)
    assert result.destinations == [directory / "image (2).png"]
    assert result.destinations[0].read_bytes() == b"photo" and not moved.exists()
    assert (directory / moved.name).is_dir() and not (directory / changed.name).exists()
    assert changed.read_bytes() == b"updated photo"
    assert len(result.errors) == 1 and changed.name in result.errors[0]
    assert clipboard_files(clipboard) == [changed]


@pytest.mark.parametrize("edit", ["in_place", "replace", "replace_both"])
def test_cross_volume_cut_preserves_edits_during_publication(tmp_path, monkeypatch, edit):
    clipboard = Clipboard()
    source = tmp_path / "image.png"
    source.write_bytes(b"original")
    directory = tmp_path / "destination"
    directory.mkdir()
    write_file_clipboard(clipboard, [source], cut=True)
    snapshot = read_file_clipboard(clipboard)
    publish = file_clipboard._publish

    def edit_during_publish(staged, folder, desired):
        if staged == source:
            raise OSError(errno.EXDEV, "different volume")
        target = publish(staged, folder, desired)
        if staged.name == "file" and folder == directory:
            if edit == "in_place":
                source.write_bytes(b"edited in place")
            else:
                replacement = tmp_path / "replacement"
                replacement.write_bytes(b"edited")
                replacement.replace(source)
            if edit == "replace_both":
                target.write_bytes(b"edited destination")
        return target

    monkeypatch.setattr(file_clipboard, "_publish", edit_during_publish)
    result = transfer_files(snapshot, directory)
    finish_file_paste(clipboard, snapshot, result)
    assert not result.destinations and len(result.errors) == 1
    assert source.read_bytes() == (b"edited in place" if edit == "in_place" else b"edited")
    assert set(tmp_path.iterdir()) == {source, directory}
    if edit == "replace_both":
        assert (directory / source.name).read_bytes() == b"edited destination"
    else:
        assert not list(directory.iterdir())
    assert read_file_clipboard(clipboard) == snapshot


def test_cross_volume_cut_preserves_new_file_after_claim(tmp_path, monkeypatch):
    source = tmp_path / "image.png"
    source.write_bytes(b"original")
    directory = tmp_path / "destination"
    directory.mkdir()
    publish, unlink = file_clipboard._publish, Path.unlink

    def cross_volume(staged, folder, desired):
        if staged == source:
            raise OSError(errno.EXDEV, "different volume")
        return publish(staged, folder, desired)

    def save_before_unlink(path, *args, **kwargs):
        if path.parent.name.startswith(".hifine-move-") and path.parent.parent == source.parent:
            source.write_bytes(b"new photo")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(file_clipboard, "_publish", cross_volume)
    monkeypatch.setattr(Path, "unlink", save_before_unlink)
    target = file_clipboard._transfer(source, directory, True)
    assert target.read_bytes() == b"original" and source.read_bytes() == b"new photo"
    assert set(tmp_path.iterdir()) == {source, directory}
