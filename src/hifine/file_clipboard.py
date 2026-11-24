"""Share image files with the system clipboard and paste them into a folder."""

import errno
import os
import shutil
import stat
from contextlib import suppress
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp

from PySide6.QtCore import QMimeData, QUrl

from .imaging import SUPPORTED_EXTENSIONS


_GNOME_FILES = "x-special/gnome-copied-files"
_KDE_CUT = "application/x-kde-cutselection"
_WINDOWS_EFFECT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'
_HIFINE_SELECTION = "application/x-hifine-image-selection"


@dataclass(frozen=True)
class FileClipboard:
    urls: tuple[QUrl, ...]
    paths: tuple[Path, ...]
    cut: bool
    viewer_selection: bool


@dataclass
class PasteResult:
    pasted: dict[Path, Path] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def destinations(self):
        return list(self.pasted.values())


def _write_urls(clipboard, urls, cut, *, viewer_selection):
    mime = QMimeData()
    mime.setUrls(urls)
    if viewer_selection:
        mime.setData(_HIFINE_SELECTION, b"1")
    lines = [b"cut" if cut else b"copy", *(bytes(url.toEncoded()) for url in urls)]
    mime.setData(_GNOME_FILES, b"\n".join(lines))
    mime.setData(_KDE_CUT, b"1" if cut else b"0")
    if os.name == "nt":
        mime.setData(_WINDOWS_EFFECT, (2 if cut else 1).to_bytes(4, "little"))
    clipboard.setMimeData(mime)


def write_file_clipboard(clipboard, paths, *, cut=False):
    urls = [QUrl.fromLocalFile(str(path.absolute())) for path in paths]
    if urls:
        _write_urls(clipboard, urls, cut, viewer_selection=True)


def read_file_clipboard(clipboard):
    mime = clipboard.mimeData()
    if mime is None:
        return None
    urls = mime.urls()
    gnome = bytes(mime.data(_GNOME_FILES)).splitlines()
    if not urls and gnome[:1] in ([b"cut"], [b"copy"]):
        urls = [QUrl.fromEncoded(line) for line in gnome[1:] if line]
    paths = (Path(url.toLocalFile()) for url in urls if url.isLocalFile())
    viewer_selection = mime.hasFormat(_HIFINE_SELECTION)
    images = tuple(dict.fromkeys(path for path in paths if path.is_absolute()
                                 and (viewer_selection or path.suffix.lower() in SUPPORTED_EXTENSIONS)))
    if not images:
        return None
    cut = (gnome[:1] == [b"cut"] or bytes(mime.data(_KDE_CUT)) == b"1"
           or bytes(mime.data(_WINDOWS_EFFECT))[:4] == b"\x02\0\0\0")
    return FileClipboard(tuple(urls), images, cut, viewer_selection)


def clipboard_files(clipboard):
    data = read_file_clipboard(clipboard)
    return list(data.paths) if data else []


def _publish(source, directory, desired):
    # Reserve the final name exclusively before the atomic rename.
    for number in count(1):
        name = desired.name if number == 1 else f"{desired.stem} ({number}){desired.suffix}"
        target = directory / name
        try:
            target.touch(exist_ok=False)
        except OSError as exc:
            # Windows can report access denied for an existing directory.
            if isinstance(exc, FileExistsError) or os.path.lexists(target):
                continue
            raise
        try:
            return source.replace(target)
        except OSError:
            target.unlink()
            raise


def _check_unchanged(path, expected):
    current = path.lstat()
    if (not os.path.samestat(expected, current) or expected.st_size != current.st_size
            or expected.st_mtime_ns != current.st_mtime_ns):
        raise OSError("剪切期间文件已更改")


def _remove_unchanged(path, expected):
    # Claim the directory entry before checking it. An editor can replace the
    # public filename at any point without its new file being unlinked.
    private = Path(mkdtemp(prefix=".hifine-move-", dir=path.parent))
    held = private / path.name
    try:
        path.rename(held)
        try:
            _check_unchanged(held, expected)
            held.unlink()
        except OSError as exc:
            try:
                restored = _publish(held, path.parent, path)
            except OSError:
                restored = held
            raise OSError(f"{exc}；文件保留在 {restored}") from exc
    finally:
        # A failed restore may have left the user's only copy inside.
        with suppress(OSError):
            private.rmdir()


def _transfer(source, directory, cut):
    if not stat.S_ISREG(source.stat().st_mode):
        raise OSError("不是普通文件")
    if cut:
        if source.parent.samefile(directory):
            return directory / source.name
        try:
            return _publish(source, directory, source)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise

    # A partially written copy should never be visible as a new thumbnail.
    with TemporaryDirectory(dir=directory) as staging:
        staged = Path(staging) / "file"
        original = source.lstat() if cut else None
        shutil.copy2(source, staged, follow_symlinks=not cut)
        if not cut:
            return _publish(staged, directory, source)
        _check_unchanged(source, original)
        copied = staged.lstat()
        target = _publish(staged, directory, source)
        try:
            _remove_unchanged(source, original)
        except OSError as exc:
            try:
                _remove_unchanged(target, copied)
            except FileNotFoundError:
                pass
            except OSError as rollback:
                raise OSError(f"{exc}；撤回目标文件时：{rollback}") from exc
            raise
        return target


def transfer_files(snapshot, directory):
    """Run on a worker thread. Each source succeeds or fails independently."""
    result = PasteResult()
    for path in snapshot.paths:
        try:
            result.pasted[path] = _transfer(path, directory, snapshot.cut)
        except (OSError, ValueError) as exc:
            result.errors.append(f"{path.name}：{exc}")
    return result


def finish_file_paste(clipboard, snapshot, result):
    """Consume only successful cuts, and only if the clipboard still matches."""
    if not snapshot.cut or not result.pasted or read_file_clipboard(clipboard) != snapshot:
        return
    remaining = [url for url in snapshot.urls
                 if not url.isLocalFile() or Path(url.toLocalFile()) not in result.pasted]
    if remaining:
        _write_urls(clipboard, remaining, True, viewer_selection=snapshot.viewer_selection)
    else:
        clipboard.clear()
