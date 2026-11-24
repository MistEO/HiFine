"""Small native controls used in HiFine's desktop viewer."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)


def glyph(name, color="#cfccc6"):
    """Render the toolbar's 24-unit line icons at a high-DPI resolution."""
    icon = QIcon()
    for mode, ink in ((QIcon.Mode.Normal, color), (QIcon.Mode.Disabled, "#635f5a")):
        pix = QPixmap(72, 72)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(3, 3)
        pen = QPen(QColor(ink), 1.65, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        def line(*coords):
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in coords]))

        if name == "reveal":
            line((11, 6), (9, 4), (3, 4), (3, 20), (20, 20), (20, 14))
            line((11, 13), (20, 4))
            line((14, 4), (20, 4), (20, 10))
        elif name == "keyboard":
            painter.drawRoundedRect(QRectF(2, 5, 20, 14), 2, 2)
            for y in (9, 12):
                for x in (6, 10, 14, 18):
                    painter.drawPoint(QPointF(x, y))
            line((8, 15), (16, 15))
        elif name == "panel":
            painter.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
            line((15, 5), (15, 19))
        elif name in ("star", "star-filled"):
            if name == "star-filled":
                painter.setBrush(QColor(ink))
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in (
                (12, 2.5), (15, 8.7), (22, 9.7), (17, 14.6), (18.2, 21.5),
                (12, 18.2), (5.8, 21.5), (7, 14.6), (2, 9.7), (9, 8.7),
            )]))
        elif name == "filter":
            for y, left, right in ((6, 3, 21), (12, 6.5, 17.5), (18, 10, 14)):
                line((left, y), (right, y))
        elif name == "fullscreen":
            line((9, 4), (4, 4), (4, 9))
            line((15, 4), (20, 4), (20, 9))
            line((4, 15), (4, 20), (9, 20))
            line((20, 15), (20, 20), (15, 20))
        elif name == "settings":
            for y, knob in ((6, 9), (12, 16), (18, 9)):
                line((3, y), (knob - 2, y))
                painter.drawEllipse(QPointF(knob, y), 2, 2)
                line((knob + 2, y), (21, y))
        elif name == "left":
            line((14, 6), (8, 12), (14, 18))
        elif name == "right":
            line((10, 6), (16, 12), (10, 18))
        elif name == "play":
            line((7, 4), (19, 12), (7, 20), (7, 4))
        elif name == "pause":
            line((8, 5), (8, 19))
            line((16, 5), (16, 19))
        elif name in ("minus", "plus"):
            line((5, 12), (19, 12))
            if name == "plus":
                line((12, 5), (12, 19))
        elif name == "fit":
            line((7, 4), (3, 4), (3, 8))
            line((17, 4), (21, 4), (21, 8))
            line((3, 16), (3, 20), (7, 20))
            line((21, 16), (21, 20), (17, 20))
            painter.drawRoundedRect(QRectF(7, 8, 10, 8), 0.8, 0.8)
        elif name == "image":
            painter.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
            painter.drawEllipse(QPointF(8, 9), 1.3, 1.3)
            line((4, 17), (9, 13), (12, 15), (16, 10), (20, 15))
        painter.end()
        pix.setDevicePixelRatio(3)
        icon.addPixmap(pix, mode)
    return icon


class ToolButton(QToolButton):
    def __init__(self, name, title, callback, *, text="", checkable=False):
        super().__init__()
        self._key_hint = ""
        self.mouse_focus_target = None
        self.describe(title)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(checkable)
        self.setFixedHeight(34)
        self.setMinimumWidth(34)
        if name:
            self.setIcon(glyph(name))
            self.setIconSize(QSize(18, 18))
        if text:
            self.setText(text)
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if name
                                    else Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.clicked.connect(callback)

    def describe(self, title, keys=None):
        if keys is not None:
            self._key_hint = keys
        self.setAccessibleName(title)
        self.setToolTip(f"{title}（{self._key_hint}）" if self._key_hint else title)

    def mousePressEvent(self, event):
        if self.mouse_focus_target is not None and event.button() == Qt.MouseButton.LeftButton:
            self.mouse_focus_target.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class ElidedLabel(QLabel):
    def __init__(self, object_name):
        super().__init__()
        self.setObjectName(object_name)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full_text = ""

    def set_full_text(self, text):
        self._full_text = text
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, max(0, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


def divider(vertical=False):
    rule = QFrame()
    rule.setObjectName("divider")
    if vertical:
        rule.setFixedSize(1, 18)
    else:
        rule.setFixedHeight(1)
    return rule


def format_bytes(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


class InfoPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(20, 20, 20, 17)
        title = QLabel("照片信息")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch()
        hint = QLabel("Tab")
        hint.setObjectName("keyHint")
        hint.setToolTip("显示或隐藏照片信息")
        header.addWidget(hint)
        outer.addLayout(header)
        outer.addWidget(divider())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)
        self.set_details(None, {})

    def set_details(self, path, data):
        content = QWidget()
        content.setObjectName("infoContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)

        def section(title, rows):
            rows = [(key, value) for key, value in rows if value is not None and value != ""]
            if not rows:
                return
            if layout.count():
                layout.addSpacing(20)
                layout.addWidget(divider())
                layout.addSpacing(20)
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            layout.addWidget(label)
            layout.addSpacing(14)
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(12)
            grid.setColumnStretch(1, 1)
            for i, (name, value) in enumerate(rows):
                key = QLabel(name)
                key.setObjectName("metaKey")
                key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                val = QLabel(str(value))
                val.setObjectName("metaValue")
                val.setTextFormat(Qt.TextFormat.PlainText)
                val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                val.setWordWrap(True)
                val.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                val.setToolTip(str(value))
                grid.addWidget(key, i, 0)
                grid.addWidget(val, i, 1)
            layout.addLayout(grid)

        if path is None:
            message = QLabel("打开图片后可查看详细信息")
            message.setObjectName("metaKey")
            layout.addWidget(message)
        else:
            width, height = data.get("width"), data.get("height")
            size = data.get("file_size")
            section("图像", [
                ("格式", data.get("format")),
                ("尺寸", f"{width:,} × {height:,}" if width and height else None),
                ("像素", f"{width * height / 1_000_000:.1f} MP" if width and height else None),
                ("像素模式", data.get("color_mode")),
                ("位深", f"{data['bit_depth']} 位" if data.get("bit_depth") else None),
            ])
            section("文件", [
                ("名称", path.name),
                ("大小", format_bytes(size) if size is not None else None),
                ("修改时间", data.get("modified")),
            ])
            section("拍摄信息", [
                ("摄影者", data.get("artist")),
                ("拍摄时间", data.get("taken_at")),
                ("相机", data.get("camera_model")),
                ("镜头", data.get("lens")),
                ("焦距", data.get("focal_length")),
                ("光圈", data.get("aperture")),
                ("快门", data.get("exposure")),
                ("ISO", data.get("iso")),
            ])
        layout.addStretch()
        self.scroll.setWidget(content)
