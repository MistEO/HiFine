"""Trash undo must only restore and clean up the originally recorded entries."""

from pathlib import Path

import pytest

from hifine.trash import TrashEntryChanged, TrashedPhoto, TrashFile, restore_from_trash


@pytest.fixture
def record(tmp_path):
    photo = tmp_path / "trash-data"
    photo.write_bytes(b"original")
    info = tmp_path / "trash-info"
    info.write_bytes(b"trash metadata")
    return TrashedPhoto(tmp_path / "photo.png", TrashFile(photo, photo.lstat()), TrashFile(info, info.lstat()))


def test_name_conflict_preserves_both_and_allows_retry(record):
    record.original.write_bytes(b"new photo")
    with pytest.raises(FileExistsError):
        restore_from_trash(record)
    assert record.original.read_bytes() == b"new photo"
    assert record.photo.path.read_bytes() == b"original" and record.info.path.is_file()
    record.original.unlink()
    restore_from_trash(record)
    assert record.original.read_bytes() == b"original"
    assert list(record.original.parent.iterdir()) == [record.original]


@pytest.mark.parametrize("changed", ["photo", "info"])
def test_external_change_preserves_both_trash_entries(record, changed):
    item = getattr(record, changed)
    item.path.write_bytes(b"belongs to someone else's deletion")
    with pytest.raises(TrashEntryChanged):
        restore_from_trash(record)
    assert not record.original.exists()
    assert item.path.read_bytes() == b"belongs to someone else's deletion"
    assert set(record.original.parent.iterdir()) == {record.photo.path, record.info.path}


def test_metadata_cleanup_failure_keeps_photo_recoverable(record, monkeypatch):
    unlink = Path.unlink

    def refuse_info(path):
        if path.name == record.info.path.name:
            raise PermissionError("metadata in use")
        return unlink(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", refuse_info)
        with pytest.raises(PermissionError):
            restore_from_trash(record)
    assert set(record.original.parent.iterdir()) == {record.photo.path, record.info.path}
    restore_from_trash(record)
    assert record.original.read_bytes() == b"original"
