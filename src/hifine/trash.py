"""Undo a move to the system trash using the exact entry returned by Qt."""

import ctypes
import os
import sys
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from PySide6.QtCore import QFile


class TrashEntryChanged(OSError):
    """The recorded entry is gone or now belongs to a different deletion."""


@dataclass(frozen=True)
class TrashFile:
    path: Path
    version: os.stat_result

    def check(self, path):
        try:
            current = path.lstat()
        except FileNotFoundError as exc:
            raise TrashEntryChanged("回收站中的文件已移走或清空") from exc
        if (not os.path.samestat(current, self.version) or current.st_size != self.version.st_size
                or current.st_mtime_ns != self.version.st_mtime_ns):
            raise TrashEntryChanged("回收站中的文件已更改")


@dataclass(frozen=True)
class TrashedPhoto:
    original: Path
    photo: TrashFile
    info: TrashFile | None


def _info_path(path):
    if sys.platform == "win32" and path.name.startswith("$R"):
        return path.with_name("$I" + path.name[2:])
    if sys.platform.startswith("linux") and path.parent.name == "files":
        return path.parent.parent / "info" / (path.name + ".trashinfo")
    if sys.platform == "darwin":
        return None  # macOS has no per-file trashinfo sidecar.
    raise OSError("系统未提供可识别的回收站记录")


def move_to_trash(path):
    """Return an undo record, or None if the system cannot identify the trashed item."""
    if not path.is_file():
        raise OSError("文件已不存在或不是普通文件")
    original = TrashFile(path, path.lstat())
    file = QFile(str(path))
    if not file.moveToTrash():
        raise OSError(file.errorString())
    if not file.fileName():
        return None
    trashed = Path(file.fileName())
    try:
        original.check(trashed)
        info = _info_path(trashed)
        return TrashedPhoto(path, TrashFile(trashed, original.version),
                            TrashFile(info, info.lstat()) if info else None)
    except OSError:
        # A simultaneous restore/empty or an inaccessible trash must never
        # turn into an undo targeting a later item that reuses the same name.
        return None


def _rename_exclusive(source, destination):
    """Atomically restore an entry without replacing a newly arrived file."""
    if os.name == "nt":
        source.rename(destination)  # Windows os.rename always refuses replacement.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    old, new = os.fsencode(source), os.fsencode(destination)
    if sys.platform == "darwin":
        status = libc.renamex_np(old, new, 4)  # RENAME_EXCL
    else:
        status = libc.renameat2(-100, old, -100, new, 1)  # AT_FDCWD, RENAME_NOREPLACE
    if status:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


@contextmanager
def _claim(entry):
    # A second process may empty the trash and recycle the same name while we
    # undo. Validate the entry after moving it away from its public pathname.
    entry.check(entry.path)
    private = Path(mkdtemp(prefix=".hifine-undo-", dir=entry.path.parent))
    held = private / entry.path.name
    try:
        entry.path.rename(held)
        try:
            entry.check(held)
            yield held
        finally:
            if os.path.lexists(held):
                try:
                    _rename_exclusive(held, entry.path)
                except OSError as exc:
                    raise TrashEntryChanged(f"回收站已更改，文件保留在 {held}") from exc
    finally:
        with suppress(OSError):
            private.rmdir()


def restore_from_trash(record):
    if os.path.lexists(record.original):
        raise FileExistsError("原位置已有同名文件，请移开后重试")
    with _claim(record.photo) as photo:
        if record.info is None:
            _rename_exclusive(photo, record.original)
        else:
            with _claim(record.info) as info:
                _rename_exclusive(photo, record.original)
                try:
                    info.unlink()
                except OSError:
                    # Keep a complete, retryable recycle-bin entry if the
                    # system refuses to remove its sidecar after restoration.
                    with _claim(TrashFile(record.original, record.photo.version)) as restored:
                        _rename_exclusive(restored, photo)
                    raise
