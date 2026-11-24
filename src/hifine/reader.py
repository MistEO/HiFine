"""Background image reads and bounded lookahead for the current folder."""

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage

from .image_cache import DecodedImage, ImageCache, image_version
from .imaging import SUPPORTED_EXTENSIONS, list_images, load_image


def _decode(path: Path, cached: DecodedImage | None, max_pixel_bytes: int | None) -> DecodedImage:
    version = image_version(path)
    if cached is not None and version is not None and version == cached.version:
        return cached

    loaded = load_image(path, max_pixel_bytes=max_pixel_bytes)
    pixels = loaded.image
    fmt = (QImage.Format.Format_RGBA8888 if pixels.mode == "RGBA"
           else QImage.Format.Format_RGB888)
    stride = pixels.width * len(pixels.getbands())
    image = QImage(pixels.tobytes(), pixels.width, pixels.height, stride, fmt).copy()
    if image.isNull():
        raise ValueError("图片尺寸过大，无法分配显示内存。")
    # A concurrent edit must not associate old pixels with the new file version.
    if image_version(path) != version:
        version = None
    return DecodedImage(image, loaded.metadata, version)


class _ReadSignals(QObject):
    finished = Signal(object, object, object, str)


class _ReadImage(QRunnable):
    def __init__(self, path, generation, scan, cached, max_pixel_bytes):
        super().__init__()
        self.path = path
        self.generation = generation
        self.scan = scan
        self.cached = cached
        self.max_pixel_bytes = max_pixel_bytes
        self.joined = False
        self.signals = _ReadSignals()

    def run(self):
        siblings = None
        if self.scan:
            try:
                siblings = list_images(self.path.parent)
            except OSError:
                siblings = []
            if self.path not in siblings:
                siblings = [self.path]
        try:
            frame = _decode(self.path, self.cached, self.max_pixel_bytes)
        except Exception as exc:
            error = str(exc) or "请检查图片是否完整，再重新打开。"
            self.signals.finished.emit(self, siblings, None, error)
        else:
            self.signals.finished.emit(self, siblings, frame, "")


class ImageReader(QObject):
    """Keep only the latest selection pending and reuse an in-flight neighbor."""

    ready = Signal(object, object, object, str)
    folder_rescanned = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._cache = ImageCache()
        self._generation = 0
        self._active = {}
        self._wanted = None
        self._scan = False
        self._neighbors = []
        self._queue = []

    @property
    def loading(self):
        return self._wanted is not None

    def reset(self):
        self._generation += 1
        self._wanted = None
        self._neighbors.clear()
        self._queue.clear()
        self._cache.clear()

    def set_cache_limits(self, *, max_entries: int, max_bytes: int):
        if (self._cache.max_entries, self._cache.max_bytes) == (max_entries, max_bytes):
            return
        self._cache.set_limits(max_entries=max_entries, max_bytes=max_bytes)
        self.set_neighbors(self._neighbors)

    def rescan_folder(self, path, version, known_files):
        request = (path, version)
        known = set(known_files)

        def scan():
            try:
                files = list_images(path.parent)
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS and path.is_file():
                    files = [path]  # A file opened through the "all files" filter.
            except FileNotFoundError:
                files = []
            except OSError:
                return
            # A rename preserves the file ID. Only newly listed names could
            # be the missing file, even in a folder containing hard links.
            renamed = None
            if path not in files and version is not None and version[1]:
                for candidate in files:
                    if candidate not in known:
                        candidate_version = image_version(candidate)
                        if candidate_version and candidate_version[:2] == version[:2]:
                            renamed = candidate
                            break
            self.folder_rescanned.emit(request, files, renamed)

        self._pool.start(scan)
        return request

    def request(self, path: Path, neighbors, scan=False):
        if scan:
            self.reset()
        self._wanted = path
        self._scan = scan
        active = self._active.get((self._generation, path))
        if active is not None:
            active.joined = True
        self.set_neighbors(neighbors)

    def set_neighbors(self, neighbors):
        self._neighbors = neighbors
        # Plan once per selection. A neighbor evicted by this round of prefetch
        # should not immediately be decoded again in the same round.
        self._queue = [path for path in neighbors if path not in self._cache
                       and (self._generation, path) not in self._active]
        self._dispatch()

    def _dispatch(self):
        if self.loading:
            path = self._wanted
            if len(self._active) < 2 and (self._generation, path) not in self._active:
                self._start(path, self._scan, self._cache.get(path))
        elif self._queue and not self._active:
            # Only one speculative read at a time, leaving a slot for navigation.
            path = self._queue.pop(0)
            budget = self._cache.available_bytes(self._higher_priority_neighbors(path))
            if budget > 0:
                self._start(path, False, None, max_pixel_bytes=budget)
            else:
                self._queue.clear()  # Lower-priority neighbors have no more budget.

    def _higher_priority_neighbors(self, path):
        return self._neighbors[:self._neighbors.index(path)]

    def _start(self, path, scan, cached, max_pixel_bytes=None):
        job = _ReadImage(path, self._generation, scan, cached, max_pixel_bytes)
        self._active[self._generation, path] = job
        job.signals.finished.connect(self._finished)
        self._pool.start(job)

    @Slot(object, object, object, str)
    def _finished(self, job, siblings, frame, error):
        path = job.path
        del self._active[job.generation, path]
        if job.generation == self._generation:
            if path == self._wanted:
                if job.joined:
                    # The file may have changed between this earlier read and
                    # the keypress, even if its result is still queued in Qt.
                    self._start(path, self._scan, frame)
                    return
                self._wanted = None
                self._cache.discard(path)
                if frame is not None:
                    self._cache.put(path, frame)
                self.ready.emit(path, siblings, frame, error)
            elif path in self._neighbors:
                protected = self._higher_priority_neighbors(path)
                if frame is not None:
                    # A lower-priority neighbor must not evict the predicted next image.
                    self._cache.put(path, frame, protected=protected)
                elif (job.max_pixel_bytes is not None
                      and self._cache.available_bytes(protected) > job.max_pixel_bytes):
                    # Replan in priority order if the old budget limited this prefetch.
                    self.set_neighbors(self._neighbors)
                    return
        self._dispatch()

    @Slot()
    def shutdown(self):
        self.reset()
        self._pool.waitForDone()
