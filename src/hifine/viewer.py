"""HiFine's desktop window and image navigation."""

import os
from pathlib import Path

from PySide6.QtCore import QDir, QFile, QFileSystemWatcher, QSize, QStandardPaths, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColorSpace, QDesktopServices, QGuiApplication, QImage, QKeySequence, QMovie, QShortcut, QTransform
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .canvas import ImageCanvas
from .controls import ElidedLabel, InfoPanel, divider, glyph, tool_button
from .file_menu import show_file_menu
from .image_cache import image_version
from .imaging import SUPPORTED_EXTENSIONS
from .reader import ImageReader
from .settings import AppSettings
from .settings_dialog import SettingsDialog
from .thumbnails import ThumbnailList
from .updates import UpdateChecker


STYLE = """
QWidget { color: #eeeae4; font-size: 13px; }
QFrame#header, QFrame#footer, QFrame#panel, QWidget#infoContent, QScrollArea {
    background: #232426;
}
QWidget#state { background: #18191b; }
QFrame#divider { background: #38383a; border: none; }
QLabel#brand { font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 24px;
    font-weight: 700; letter-spacing: -1px; color: #faf8f4; }
QLabel#location, QLabel#position, QLabel#metaKey { color: #a19e99; }
QLabel#location, QLabel#position, QLabel#metaValue, QLabel#metaKey { font-size: 12px; }
QLabel#panelTitle, QLabel#stateTitle { font-size: 17px; font-weight: 600; }
QLabel#keyHint { padding: 1px 5px; font-size: 11px; color: #a8a59e;
    border: 1px solid #504e4c; border-radius: 4px; }
QLabel#sectionTitle { font-size: 12px; font-weight: 600; color: #f1bc86; }
QLabel#metaValue, QLabel#filename { color: #dfddd8; }
QLabel#stateDescription { color: #a8a5a0; }
QToolButton, QPushButton { background: transparent; color: #e5e1da; border: 1px solid transparent;
    border-radius: 5px; padding: 3px; }
QToolButton:hover, QPushButton:hover { background: #38383a; }
QToolButton:pressed, QPushButton:pressed { background: #454443; }
QToolButton:checked { background: #42362c; border-color: #624b37; }
QToolButton#open, QPushButton#open { background: #f0b47b; color: #251c14; font-weight: 600;
    padding: 5px 12px; border: 1px solid #f1bd8b; }
QToolButton#open:hover, QPushButton#open:hover { background: #fac58f; }
QToolButton#open:pressed, QPushButton#open:pressed { background: #dea16a; }
QPushButton#zoom { color: #e6e3dd; padding: 3px 5px; font-size: 12px; font-weight: 600; }
QPushButton#zoom:disabled { color: #77736f; }
QScrollBar:vertical { background: #232426; width: 6px; }
QScrollBar::handle:vertical { background: #515052; min-height: 26px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QToolTip { background: #343436; color: #efeee9; border: 1px solid #595756; padding: 4px; }
"""


def _open_movie(path, parent):
    if os.name != "nt":
        return QMovie(str(path), parent=parent)

    from .windows_files import open_image_fd

    movie = QMovie(parent)
    device = QFile(movie)
    try:
        fd = open_image_fd(path)
    except OSError:
        return movie
    if device.open(fd, QFile.OpenModeFlag.ReadOnly, QFile.FileHandleFlag.AutoCloseHandle):
        movie.setDevice(device)
    else:
        os.close(fd)
    return movie


class MainWindow(QMainWindow):
    def __init__(self, sample_path=None, *, settings_store=None):
        super().__init__()
        self.setWindowTitle("HiFine")
        self.setAcceptDrops(True)
        self.setMinimumSize(600, 380)
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().size() if screen else QSize(1280, 800)
        self.resize(min(1200, int(available.width() * 0.90)),
                    min(800, int(available.height() * 0.90)))
        self.sample_path = Path(sample_path).absolute() if sample_path else None
        self.current_path = None
        self.files = []
        self._index = -1
        self._direction = 1
        self._reads = ImageReader(self)
        self._settings_store = settings_store
        self._updates = None
        self._apply_settings(AppSettings.load(settings_store))
        self._reads.ready.connect(self._read_finished)
        self._reads.folder_rescanned.connect(self._menu_folder_rescanned)
        self._menu_watch = QFileSystemWatcher(self)
        self._menu_watch.fileChanged.connect(self._menu_file_changed)
        self._menu_refresh = QTimer(self, singleShot=True, interval=80)
        self._menu_refresh.timeout.connect(self._rescan_menu_folder)
        self._menu_watch.directoryChanged.connect(lambda _: self._menu_refresh.start())
        self._menu_versions = {}
        self._menu_scan = None
        QApplication.instance().aboutToQuit.connect(self._reads.shutdown)
        self._movie = None
        self._movie_orientation = 1
        self._loading_hint = QTimer(self)
        self._loading_hint.setSingleShot(True)
        self._loading_hint.setInterval(150)
        self._loading_hint.timeout.connect(self._show_loading)
        self._had_maximized = False
        self._displayed_path = None
        self._setup_view()
        self._setup_shortcuts()
        self._show_state("打开一张图片", "也可以将图片拖到这里。", open_button=True)
        self._update_navigation()

    def _setup_view(self):
        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(STYLE)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(62)
        top = QHBoxLayout(header)
        top.setContentsMargins(20, 0, 18, 0)
        top.setSpacing(8)
        logo = QLabel()
        app_icon = QApplication.windowIcon()
        if app_icon.isNull():
            app_icon = glyph("image", "#f0b47b")
        logo.setPixmap(app_icon.pixmap(QSize(30, 30), self.devicePixelRatioF()))
        top.addWidget(logo)
        brand = QLabel("HiFine")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addSpacing(11)
        top.addWidget(divider(True))
        top.addSpacing(9)
        self.location = ElidedLabel("location")
        top.addWidget(self.location, 1)
        self.open_button = tool_button("folder", "打开图片", self.choose_file,
                                       text="打开图片", color="#342519")
        self.open_button.setObjectName("open")
        self.open_button.setToolTip(f"打开图片（{QKeySequence(QKeySequence.StandardKey.Open).toString(QKeySequence.SequenceFormat.NativeText)}）")
        top.addWidget(self.open_button)
        top.addSpacing(5)
        self.info_button = tool_button("panel", "查看或隐藏照片信息（Tab）",
                                       self._set_info, checkable=True)
        self.info_button.setChecked(True)
        top.addWidget(self.info_button)
        self.full_button = tool_button("fullscreen", "进入或退出全屏（F11）",
                                       self._toggle_fullscreen, checkable=True)
        top.addWidget(self.full_button)
        self.settings_button = tool_button("settings", "设置", self.show_settings, text="设置")
        settings_key = QKeySequence("Ctrl+,")
        self.settings_button.setShortcut(settings_key)
        self.settings_button.setToolTip(f"设置（{settings_key.toString(QKeySequence.SequenceFormat.NativeText)}）")
        top.addWidget(self.settings_button)
        layout.addWidget(header)
        layout.addWidget(divider())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.thumbnail_list = ThumbnailList()
        self.thumbnail_list.row_requested.connect(self._go_to)
        self.thumbnail_list.file_menu_requested.connect(self._show_file_menu)
        QApplication.instance().aboutToQuit.connect(self.thumbnail_list.shutdown)
        body.addWidget(self.thumbnail_list)
        self.stage = QStackedWidget()
        self.canvas = ImageCanvas()
        self.canvas.file_menu_requested.connect(lambda pos: self._show_file_menu(self._displayed_path, pos))
        self.stage.addWidget(self.canvas)
        self.state = QWidget()
        self.state.setObjectName("state")
        state_layout = QVBoxLayout(self.state)
        state_layout.setContentsMargins(20, 15, 20, 15)
        state_layout.setSpacing(10)
        state_layout.addStretch()
        state_icon = QLabel()
        state_icon.setPixmap(glyph("image", "#cb9463").pixmap(QSize(36, 36), self.devicePixelRatioF()))
        state_layout.addWidget(state_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.state_title = QLabel()
        self.state_title.setObjectName("stateTitle")
        self.state_description = QLabel()
        self.state_description.setObjectName("stateDescription")
        self.state_description.setTextFormat(Qt.TextFormat.PlainText)
        self.state_description.setWordWrap(True)
        self.state_description.setMaximumWidth(420)
        self.state_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        state_layout.addWidget(self.state_title, 0, Qt.AlignmentFlag.AlignHCenter)
        state_layout.addWidget(self.state_description, 0, Qt.AlignmentFlag.AlignHCenter)
        self.state_button = QPushButton("打开图片")
        self.state_button.setObjectName("open")
        self.state_button.clicked.connect(self.choose_file)
        state_layout.addWidget(self.state_button, 0, Qt.AlignmentFlag.AlignHCenter)
        state_layout.addStretch()
        self.stage.addWidget(self.state)
        body.addWidget(self.stage, 1)
        self.panel_divider = QFrame()
        self.panel_divider.setObjectName("divider")
        self.panel_divider.setFixedWidth(1)
        body.addWidget(self.panel_divider)
        self.info_panel = InfoPanel()
        self.info_panel.setFixedWidth(264)
        body.addWidget(self.info_panel)
        layout.addLayout(body, 1)

        layout.addWidget(divider())
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(53)
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(13, 0, 17, 0)
        bottom.setSpacing(5)
        self.prev_button = tool_button("left", "上一张（←）", lambda: self.navigate(-1))
        self.next_button = tool_button("right", "下一张（→）", lambda: self.navigate(1))
        bottom.addWidget(self.prev_button)
        self.position = QLabel()
        self.position.setObjectName("position")
        self.position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position.setMinimumWidth(40)
        bottom.addWidget(self.position)
        bottom.addWidget(self.next_button)
        bottom.addSpacing(7)
        bottom.addWidget(divider(True))
        bottom.addSpacing(9)
        self.filename = ElidedLabel("filename")
        bottom.addWidget(self.filename, 1)
        self.play_button = tool_button("pause", "暂停动图（空格）", self._toggle_play)
        self.play_button.hide()
        bottom.addWidget(self.play_button)
        self.minus_button = tool_button("minus", "缩小（−）", lambda: self.canvas.zoom_by(1 / 1.2))
        bottom.addWidget(self.minus_button)
        self.zoom_button = QPushButton("100%")
        self.zoom_button.setObjectName("zoom")
        self.zoom_button.setFixedWidth(56)
        self.zoom_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_button.setToolTip("原始大小（1）")
        self.zoom_button.setAccessibleName("以原始大小查看")
        self.zoom_button.clicked.connect(lambda: self.canvas.set_zoom(1.0))
        bottom.addWidget(self.zoom_button)
        self.plus_button = tool_button("plus", "放大（+）", lambda: self.canvas.zoom_by(1.2))
        bottom.addWidget(self.plus_button)
        bottom.addSpacing(5)
        bottom.addWidget(divider(True))
        bottom.addSpacing(6)
        self.fit_button = tool_button("fit", "适应窗口（0）", self.canvas.fit, checkable=True)
        bottom.addWidget(self.fit_button)
        layout.addWidget(footer)
        self.canvas.zoom_changed.connect(self._set_zoom_label)
        self._set_zoom_label(self.canvas.zoom(), True)

    def _setup_shortcuts(self):
        self._shortcuts = []

        def add(sequence, callback):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        add(QKeySequence.StandardKey.Open, self.choose_file)
        add("Left", lambda: self.navigate(-1))
        add("Right", lambda: self.navigate(1))
        add("Tab", lambda: self.info_button.click())
        add("F11", self._toggle_fullscreen)
        add("Escape", self._leave_fullscreen)
        add("Space", self._toggle_play)
        add("+", lambda: self.canvas.zoom_by(1.2))
        add("=", lambda: self.canvas.zoom_by(1.2))
        add("-", lambda: self.canvas.zoom_by(1 / 1.2))
        add("0", self.canvas.fit)
        add("1", lambda: self.canvas.set_zoom(1.0))

    def show_settings(self):
        dialog = SettingsDialog(self._settings, self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            settings = dialog.settings()
            try:
                settings.save(self._settings_store)
            except OSError as exc:
                QMessageBox.warning(self, "无法保存设置", str(exc))
            else:
                self._apply_settings(settings)
                break
        dialog.deleteLater()

    def _apply_settings(self, settings):
        if self._updates is not None and self._settings.mirrorchyan_cdk != settings.mirrorchyan_cdk:
            self._updates.stop()
        self._settings = settings
        self._reads.set_cache_limits(max_entries=settings.cache_max_entries,
                                     max_bytes=settings.cache_max_mib * 1024**2)

    def start_update_check(self):
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setStyleSheet("QStatusBar { background: #232426; color: #f1bc86; padding-left: 12px; }")
        bar.hide()
        bar.messageChanged.connect(lambda text: bar.setVisible(bool(text)))

        self._updates = UpdateChecker(self)
        self._updates.notice.connect(self._show_update_notice)
        self._updates.installer_ready.connect(self._open_installer)
        QApplication.instance().aboutToQuit.connect(self._updates.stop)
        self._updates.start(self._settings.mirrorchyan_cdk)

    def _show_update_notice(self, message):
        bar = self.statusBar()
        bar.setToolTip(message)
        bar.showMessage(message, 15_000)

    def _open_installer(self, version, path):
        if QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self._show_update_notice(f"HiFine v{version} 安装包已打开，请关闭 HiFine 后按提示安装。")
        else:
            self._show_update_notice(f"请手动打开已下载的安装包：{QDir.toNativeSeparators(path)}")

    def _set_info(self, visible):
        self.info_panel.setVisible(visible)
        self.panel_divider.setVisible(visible)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self._had_maximized = self.isMaximized()
            self.showFullScreen()
            self.full_button.setChecked(True)

    def _leave_fullscreen(self):
        if self.isFullScreen():
            if self._had_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.full_button.setChecked(False)

    def _set_zoom_label(self, value, fitting):
        percentage = value * 100
        self.zoom_button.setText(f"{percentage:.1f}%" if percentage < 10 else f"{percentage:.0f}%")
        self.fit_button.setChecked(fitting)

    def _show_state(self, title, description="", open_button=False):
        self.state_title.setText(title)
        self.state_description.setText(description)
        self.state_description.setVisible(bool(description))
        self.state_button.setVisible(open_button)
        self.stage.setCurrentWidget(self.state)
        self._displayed_path = None
        self._set_zoom_enabled(False)

    def _set_zoom_enabled(self, enabled):
        for button in (self.zoom_button, self.fit_button, self.minus_button, self.plus_button):
            button.setEnabled(enabled)

    def _show_file_menu(self, path, position):
        if path is None:
            return
        version = image_version(path)
        if not show_file_menu(self, path, position):
            return
        if self.current_path and path.parent == self.current_path.parent:
            # Shell commands can finish after the menu closes, e.g. Explorer's rename editor.
            if str(path.parent) not in self._menu_watch.directories():
                self._menu_watch.addPath(str(path.parent))
            self._menu_versions[path] = version
            self._menu_file_changed(str(path))
            self._menu_refresh.start()

    def _menu_file_changed(self, filename):
        path = Path(filename)
        if path not in self._menu_versions:
            return
        previous = self._menu_versions[path]
        version = image_version(path)
        if version is None:
            self._menu_refresh.start()
            return
        if filename not in self._menu_watch.files():
            self._menu_watch.addPath(filename)
        self._menu_versions[path] = version
        if version != previous:
            if path == self.current_path:
                self._schedule_read(path, scan=False)
            elif path in self.files:
                self.thumbnail_list.invalidate_preview(self.files.index(path))

    def _rescan_menu_folder(self):
        path = self.current_path or next(iter(self._menu_versions), None)
        if path is not None:
            self._menu_scan = self._reads.rescan_folder(
                path, self._menu_versions.get(path), self.files)

    def _menu_folder_rescanned(self, request, files, renamed):
        if request is not self._menu_scan or self._menu_refresh.isActive():
            return
        self._menu_scan = None
        known = set(files)
        missing = [name for name in self._menu_watch.files() if Path(name) not in known]
        if missing:
            self._menu_watch.removePaths(missing)
        # A replacement can arrive as a single directory change. Recheck the
        # menu targets even if Qt still lists their file watches.
        for path in self._menu_versions:
            if path in known:
                self._menu_file_changed(str(path))
        if len(files) == len(self.files) and all(old.name == new.name for old, new in zip(self.files, files)):
            return
        original_path, version = request
        self.files = files
        self.thumbnail_list.set_files(files)
        if not files:
            # An editor can leave the folder empty between removing the only
            # image and saving its replacement. Keep watching the directory.
            self._menu_versions = {original_path: version}
            self._reads.reset()
            self._loading_hint.stop()
            self._stop_animation()
            self._index = -1
            self.current_path = None
            self.canvas.set_image(QImage())
            self.info_panel.set_details(None, {})
            self.filename.set_full_text("")
            self.filename.setToolTip("")
            self.setWindowTitle("HiFine")
            self._show_state("文件夹中没有图片", open_button=True)
            self._update_navigation()
            return

        selected = self.current_path or original_path
        if renamed:
            self._menu_versions[renamed] = version
            self._menu_watch.addPath(str(renamed))
            if selected == original_path:
                selected = renamed
        self._menu_versions = {path: version for path, version in self._menu_versions.items() if path in known}
        self._index = files.index(selected) if selected in known else min(max(self._index, 0), len(files) - 1)
        path = files[self._index]
        loading = self._reads.loading
        if loading:
            self._reads.reset()  # An earlier folder scan can no longer replace this list.
        if loading or self._displayed_path is None or path.parts != self._displayed_path.parts:
            self._schedule_read(path, scan=False)
        else:
            self.current_path = path
            self._update_navigation()
            self._reads.set_neighbors(self._neighbors())

    def _clear_menu_watch(self):
        self._menu_scan = None
        self._menu_refresh.stop()
        self._menu_versions.clear()
        if paths := self._menu_watch.files() + self._menu_watch.directories():
            self._menu_watch.removePaths(paths)

    def choose_file(self):
        start = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        if self.current_path and not self._is_sample(self.current_path):
            start = str(self.current_path.parent)
        patterns = " ".join(f"*{ext} *{ext.upper()}" for ext in sorted(SUPPORTED_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(self, "打开图片", start,
                                               f"图片文件 ({patterns});;所有文件 (*)")
        if path:
            self.open_file(path)

    def open_sample(self):
        if self.sample_path and self.sample_path.is_file():
            self.open_file(self.sample_path)

    def _is_sample(self, path):
        return self.sample_path is not None and self.sample_path.parent == path.parent

    def open_file(self, path):
        path = Path(path).expanduser().absolute()
        self._menu_scan = None
        if self.current_path is None or self.current_path.parent != path.parent:
            self._clear_menu_watch()
        self.thumbnail_list.set_files([])
        self.files = [path]
        self._index = 0
        self._direction = 1
        self._schedule_read(path, scan=True)

    def navigate(self, step):
        self._go_to(self._index + step)

    def _go_to(self, index):
        if not 0 <= index < len(self.files) or index == self._index:
            return
        self._direction = 1 if index > self._index else -1
        self._index = index
        self._schedule_read(self.files[index], scan=False)

    def _schedule_read(self, path, scan):
        self._stop_animation()
        self.current_path = path
        self._update_navigation()
        if self._displayed_path is not None:
            self._loading_hint.start()
        else:
            self._show_loading()
        self._reads.request(path, self._neighbors(), scan=scan)

    def _neighbors(self):
        indices = (self._index + self._direction, self._index - self._direction)
        return [self.files[i] for i in indices if 0 <= i < len(self.files)]

    def _show_path(self, path):
        self.setWindowTitle(f"{path.name} — HiFine")
        self.filename.set_full_text(path.name)
        self.filename.setToolTip(QDir.toNativeSeparators(str(path)))
        location = "示例照片" if self._is_sample(path) else (path.parent.name or str(path.parent))
        self.location.set_full_text(location)
        self.location.setToolTip(QDir.toNativeSeparators(str(path.parent)))

    def _show_loading(self):
        self._show_path(self.current_path)
        self.info_panel.set_details(self.current_path, {})
        self.canvas.set_image(QImage())
        self._show_state("正在读取图片…")

    @Slot(object, object, object, str)
    def _read_finished(self, path, siblings, frame, error):
        self._loading_hint.stop()
        self._show_path(path)
        if siblings is not None:
            self.files = siblings
            self._index = self.files.index(path)
            self.thumbnail_list.set_files(siblings)
            self._reads.set_neighbors(self._neighbors())
        self._update_navigation()
        self.thumbnail_list.sync_current(self._index, frame)
        details = frame.metadata if frame is not None else {}
        self.info_panel.set_details(path, details)
        if error:
            self.canvas.set_image(QImage())
            self._show_state("无法打开这张图片", error, open_button=True)
        else:
            self.stage.setCurrentWidget(self.canvas)
            self._displayed_path = path
            self.canvas.set_image(frame.image)
            self._set_zoom_enabled(True)
            if details.get("animated"):
                self._start_animation(path, details.get("animation_orientation", 1))

    def closeEvent(self, event):
        if self._updates is not None:
            self._updates.stop()
        self._clear_menu_watch()
        self._loading_hint.stop()
        self._reads.reset()
        self.thumbnail_list.shutdown()
        super().closeEvent(event)

    def _start_animation(self, path, orientation):
        movie = _open_movie(path, self)
        if not movie.isValid():
            movie.deleteLater()
            return
        self._movie = movie
        self._movie_orientation = orientation
        movie.frameChanged.connect(self._show_frame)
        movie.stateChanged.connect(self._movie_state_changed)
        movie.error.connect(self._stop_animation)
        self.play_button.show()
        movie.start()

    def _stop_animation(self):
        movie, self._movie = self._movie, None
        if movie is not None:
            movie.stop()
            movie.deleteLater()
        self.play_button.hide()

    def _show_frame(self):
        if self._movie is None:
            return
        frame = self._movie.currentImage()
        if frame.isNull():
            return
        orientation = self._movie_orientation
        degrees = {3: 180, 5: 90, 6: 90, 7: 90, 8: -90}.get(orientation)
        if degrees is not None:
            frame = frame.transformed(QTransform().rotate(degrees))
        if orientation in (2, 5):
            frame = frame.flipped(Qt.Orientation.Horizontal)
        elif orientation in (4, 7):
            frame = frame.flipped(Qt.Orientation.Vertical)
        if frame.colorSpace().isValid():
            frame = frame.convertedToColorSpace(QColorSpace.NamedColorSpace.SRgb)
        self.canvas.set_frame(frame)

    def _movie_state_changed(self, state):
        playing = state == QMovie.MovieState.Running
        action = "暂停动图（空格）" if playing else "播放动图（空格）"
        self.play_button.setIcon(glyph("pause" if playing else "play"))
        self.play_button.setToolTip(action)
        self.play_button.setAccessibleName(action)

    def _toggle_play(self):
        if self._movie is None:
            return
        state = self._movie.state()
        if state == QMovie.MovieState.NotRunning:
            self._movie.start()
        else:
            self._movie.setPaused(state == QMovie.MovieState.Running)

    def _update_navigation(self):
        self.thumbnail_list.select_row(self._index)
        self.prev_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(0 <= self._index < len(self.files) - 1)
        self.position.setText(f"{self._index + 1} / {len(self.files)}" if self.files else "—")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "info_panel"):
            self.thumbnail_list.setFixedWidth(max(105, min(176, round(self.width() * 0.15))))
            self.info_panel.setFixedWidth(max(205, min(278, round(self.width() * 0.235))))

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() and Path(url.toLocalFile()).is_file()
               for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).is_file():
                self.open_file(url.toLocalFile())
                event.acceptProposedAction()
                return
