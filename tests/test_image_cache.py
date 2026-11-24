import os
from pathlib import Path

from PySide6.QtGui import QImage

from hifine.image_cache import DecodedImage, ImageCache, image_version


def frame(width=1, height=1, version=(1, 2, 3, 4)):
    image = QImage(width, height, QImage.Format.Format_RGB888)
    return DecodedImage(image, {"width": width, "height": height}, version)


def test_foreground_access_refreshes_lru():
    cache = ImageCache(max_entries=2)
    a, b, c = map(Path, ("a.png", "b.png", "c.png"))
    first = frame()
    cache.put(a, first)
    cache.put(b, frame())
    assert cache.get(a) is first
    assert b in cache
    assert cache.put(c, frame())
    assert a in cache and c in cache
    assert cache.get(b) is None


def test_byte_limit_includes_scanline_padding_and_skips_protected_entries():
    a, b, c, d = map(Path, ("a.png", "b.png", "c.png", "d.png"))
    cache = ImageCache(max_bytes=12)
    for path in (a, b, c):
        cache.put(path, frame())
    # Each row of this 1-pixel-wide RGB image occupies four bytes.
    assert cache.put(d, frame(height=2), protected=(a,))
    assert a in cache and d in cache
    assert b not in cache and c not in cache
    assert cache.put(d, frame())
    assert cache.put(b, frame())
    assert a in cache and d in cache


def test_failed_prefetch_preserves_existing_entries_and_lru_order():
    a, b, c, d = map(Path, ("a.png", "b.png", "c.png", "d.png"))
    cache = ImageCache(max_bytes=12)
    for path in (a, b, c):
        cache.put(path, frame())
    assert not cache.put(d, frame(height=3), protected=(b,))
    assert not cache.put(a, frame(height=4))
    assert not cache.put(d, frame(version=None))
    assert a in cache and b in cache and c in cache
    assert d not in cache
    assert cache.put(d, frame())
    assert a not in cache and b in cache and c in cache
    cache.discard(b)
    assert cache.get(b) is None
    cache.clear()
    assert c not in cache and d not in cache


def test_resizing_cache_trims_in_lru_order_and_allows_growth():
    cache = ImageCache()
    a, b, c, d = map(Path, ("a", "b", "c", "d"))
    for path in (a, b, c, d):
        cache.put(path, frame())
    cache.get(a)

    cache.set_limits(max_entries=3, max_bytes=16)
    assert a in cache and c in cache and d in cache
    assert b not in cache
    cache.set_limits(max_entries=3, max_bytes=8)
    assert c not in cache
    assert a in cache and d in cache
    assert cache.available_bytes((a, d)) == 0

    cache.set_limits(max_entries=4, max_bytes=16)
    assert cache.put(b, frame()) and cache.put(c, frame())
    assert all(path in cache for path in (a, b, c, d))


def test_smaller_budget_discards_oversized_frame_before_older_frames():
    cache = ImageCache()
    small, large = map(Path, ("small", "large"))
    cache.put(small, frame())
    cache.put(large, frame(height=4))

    cache.set_limits(max_entries=8, max_bytes=8)
    assert small in cache and large not in cache
    assert not cache.put(large, frame(height=4))


def test_file_version_tracks_changes_and_removal(tmp_path):
    path = tmp_path / "picture.png"
    assert image_version(path) is None
    path.write_bytes(b"abc")
    stat = path.stat()
    initial = image_version(path)
    assert initial == (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 4_000_000_000))
    updated = image_version(path)
    assert updated != initial
    path.write_bytes(b"new data")
    assert image_version(path) != updated
    path.unlink()
    assert image_version(path) is None
