"""In-memory cache of display pixels and metadata for folder navigation."""

from collections import OrderedDict
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImage

from .settings import DEFAULT_CACHE_ENTRIES, DEFAULT_CACHE_MIB


ImageVersion = tuple[int, int, int, int]


def image_version(path: Path) -> ImageVersion | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@dataclass(frozen=True)
class DecodedImage:
    image: QImage
    metadata: dict[str, str | int]
    version: ImageVersion | None


class ImageCache:
    """GUI-thread LRU of read-only decoded images."""

    def __init__(self, max_bytes: int = DEFAULT_CACHE_MIB * 1024**2,
                 max_entries: int = DEFAULT_CACHE_ENTRIES):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._frames: OrderedDict[Path, DecodedImage] = OrderedDict()

    def __contains__(self, path: Path) -> bool:
        """Check residency without touching the file or changing eviction order."""
        return path in self._frames

    def get(self, path: Path) -> DecodedImage | None:
        frame = self._frames.get(path)
        if frame is not None:
            self._frames.move_to_end(path)
        return frame

    def discard(self, path: Path) -> None:
        self._frames.pop(path, None)

    def clear(self) -> None:
        self._frames.clear()

    def set_limits(self, *, max_bytes: int, max_entries: int) -> None:
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        # An oversized recent frame cannot be kept, even if every older frame is evicted.
        self._frames = OrderedDict((path, frame) for path, frame in self._frames.items()
                                   if frame.image.sizeInBytes() <= max_bytes)
        total = sum(frame.image.sizeInBytes() for frame in self._frames.values())
        while self._frames and (len(self._frames) > max_entries or total > max_bytes):
            _, oldest = self._frames.popitem(last=False)
            total -= oldest.image.sizeInBytes()

    def available_bytes(self, protected: Collection[Path]) -> int:
        pinned = [self._frames[path] for path in protected if path in self._frames]
        if len(pinned) >= self.max_entries:
            return 0
        return self.max_bytes - sum(frame.image.sizeInBytes() for frame in pinned)

    def put(self, path: Path, frame: DecodedImage, protected: Collection[Path] = ()) -> bool:
        size = frame.image.sizeInBytes()
        if frame.version is None or size == 0 or size > self.max_bytes:
            return False

        # Plan eviction on a shallow copy so a rejected prefetch leaves the LRU intact.
        frames = self._frames.copy()
        frames.pop(path, None)
        frames[path] = frame
        total = sum(item.image.sizeInBytes() for item in frames.values())
        evictable = (key for key in self._frames if key != path and key not in protected)
        while len(frames) > self.max_entries or total > self.max_bytes:
            oldest = next(evictable, None)
            if oldest is None:
                return False
            total -= frames.pop(oldest).image.sizeInBytes()
        self._frames = frames
        return True
