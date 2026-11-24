"""Folder thumbnails for the viewer's navigation sidebar."""

from collections import OrderedDict

from PySide6.QtCore import (
    QAbstractListModel, QItemSelection, QItemSelectionModel, QModelIndex, QObject, QPoint, QRect,
    QRunnable, QSignalBlocker, QSize, Qt, QThreadPool, Signal, Slot,
)
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QPainter, QPen
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from .controls import glyph
from .image_cache import image_version
from .imaging import make_thumbnail


_PREVIEW_SIZE = 320


class _ThumbnailModel(QAbstractListModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.files = []
        self.images = OrderedDict()

    def set_files(self, files):
        self.beginResetModel()
        self.files = list(files)
        self.images.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.files)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.files[row].name
        if role == Qt.ItemDataRole.DecorationRole and row in self.images:
            self.images.move_to_end(row)
            return self.images[row][0]
        return None

    def set_preview(self, row, image, version=None):
        self.images.pop(row, None)
        if image is not None:
            self.images[row] = image, version
            if len(self.images) > 64:
                self.images.popitem(last=False)
        index = self.index(row)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])


class _ThumbnailDelegate(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self._placeholder = glyph("image", "#726f6b")

    def sizeHint(self, option, index):
        return QSize(1, 110)

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = option.rect.adjusted(5, 3, -5, -3)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or hovered:
            painter.setBrush(QColor("#43372d" if selected else "#2e2e30"))
            painter.drawRoundedRect(card, 5, 5)

        frame = card.adjusted(5, 5, -5, -23)
        painter.setBrush(QColor("#191a1c"))
        painter.setPen(QPen(QColor("#f0b47b" if selected else "#434346"), 2 if selected else 1))
        painter.drawRoundedRect(frame, 3, 3)

        image = index.data(Qt.ItemDataRole.DecorationRole)
        if image is not None and not image.isNull():
            size = image.size().scaled(frame.size() - QSize(4, 4), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(), size)
            target.moveCenter(frame.center())
            painter.drawImage(target, image)
        else:
            icon = QRect(0, 0, 23, 23)
            icon.moveCenter(frame.center())
            self._placeholder.paint(painter, icon)

        label = QRect(frame.left(), frame.bottom() + 2, frame.width(), 20)
        text = option.fontMetrics.elidedText(index.data(), Qt.TextElideMode.ElideMiddle, label.width())
        painter.setPen(QColor("#ffdbb6" if selected else "#c5c2bd"))
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class _ThumbnailSignals(QObject):
    finished = Signal(object, QImage)


class _ReadThumbnail(QRunnable):
    def __init__(self, files, row, frame):
        super().__init__()
        self.files = files
        self.row = row
        self.frame = frame
        self.version = None
        self.superseded = False
        self.signals = _ThumbnailSignals()

    def run(self):
        try:
            if self.frame is not None:
                image = self.frame.image
                if max(image.width(), image.height()) > _PREVIEW_SIZE:
                    image = image.scaled(_PREVIEW_SIZE, _PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
                self.version = self.frame.version
            else:
                path = self.files[self.row]
                version = image_version(path)
                with make_thumbnail(path, _PREVIEW_SIZE) as pixels:
                    image = QImage(pixels.tobytes(), pixels.width, pixels.height,
                                   pixels.width * 4, QImage.Format.Format_RGBA8888).copy()
                if version == image_version(path):
                    self.version = version
        except Exception:
            # Keep an unreadable file selectable so the viewer can show its error.
            image = QImage()
        self.signals.finished.emit(self, image)


class ThumbnailList(QListView):
    row_requested = Signal(int)
    file_menu_requested = Signal(object, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("thumbnailList")
        self.setAccessibleName("图片缩略图")
        self.setStyleSheet("QListView#thumbnailList { background: #232426; border: none;"
                           " border-right: 1px solid #38383a; }")
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._model = _ThumbnailModel(self)
        self.setModel(self._model)
        self.setItemDelegate(_ThumbnailDelegate(self))
        self.selectionModel().currentChanged.connect(self._current_changed)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job = None
        self._source_row = -1
        self._source_frame = None

    def set_files(self, files):
        self._source_row = -1
        self._source_frame = None
        self._model.set_files(files)

    def sync_current(self, row, frame):
        """Refresh a changed file's preview from the frame the viewer actually read."""
        if not 0 <= row < self._model.rowCount():
            return
        self._source_row = row
        self._source_frame = frame
        cached = self._model.images.get(row)
        if frame is not None and frame.version is not None and cached and cached[1] == frame.version:
            return
        self._refresh_preview(row, QImage() if frame is None else None)

    def invalidate_preview(self, row):
        if row == self._source_row:
            self._source_frame = None
        self._refresh_preview(row, None)

    def _refresh_preview(self, row, placeholder):
        if self._job is not None and self._job.row == row:
            self._job.superseded = True
        self._model.set_preview(row, placeholder)
        self._load_visible()

    def select_row(self, row):
        index = self._model.index(row)
        if index != self.currentIndex():
            with QSignalBlocker(self):
                self.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                if index.isValid():
                    self.scrollTo(index)

    def selected_paths(self):
        rows = sorted(index.row() for index in self.selectedIndexes())
        return [self._model.files[row] for row in rows]

    def set_selected_paths(self, paths):
        paths = set(paths)
        selection = QItemSelection()
        for row, path in enumerate(self._model.files):
            if path in paths:
                index = self._model.index(row)
                selection.select(index, index)
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _current_changed(self, current, previous):
        if current.isValid():
            self.row_requested.emit(current.row())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._select_context_index(self.indexAt(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)

    def _select_context_index(self, index):
        selection = self.selectionModel()
        if index.isValid() and not selection.isSelected(index):
            selection.select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def contextMenuEvent(self, event):
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            index = self.currentIndex()
            if not self.selectionModel().isSelected(index):
                index = next(iter(self.selectedIndexes()), QModelIndex())
            position = self.viewport().mapToGlobal(self.visualRect(index).center())
        else:
            index = self.indexAt(event.pos())
            self._select_context_index(index)
            position = event.globalPos()
        if not index.isValid():
            return super().contextMenuEvent(event)
        event.accept()
        self.file_menu_requested.emit(self.selected_paths(), position)

    def paintEvent(self, event):
        super().paintEvent(event)
        self._load_visible()

    def _load_visible(self):
        if self._job is not None or not self.isVisible():
            return
        viewport = self.viewport().rect()
        first = self.indexAt(viewport.topLeft())
        if not first.isValid():
            return
        last = self.indexAt(viewport.bottomLeft())
        stop = last.row() + 1 if last.isValid() else self._model.rowCount()
        row = self._source_row
        if not first.row() <= row < stop or row in self._model.images:
            row = next((i for i in range(first.row(), stop) if i not in self._model.images), None)
        if row is not None:
            frame = self._source_frame if row == self._source_row else None
            job = _ReadThumbnail(self._model.files, row, frame)
            self._job = job
            job.signals.finished.connect(self._finished)
            self._pool.start(job)

    @Slot(object, QImage)
    def _finished(self, job, image):
        if job is not self._job:
            return
        self._job = None
        if self._model.files is job.files and not job.superseded:
            self._model.set_preview(job.row, image, job.version)
        self._load_visible()

    @Slot()
    def shutdown(self):
        self._job = None
        self._source_frame = None
        self._pool.waitForDone()
