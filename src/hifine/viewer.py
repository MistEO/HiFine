"""HiFine's desktop window and image navigation."""

import os
from pathlib import Path

from PySide6.QtCore import (
    QDir, QFile, QFileSystemWatcher, QSize, QStandardPaths, Qt, QThreadPool, QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import QColorSpace, QDesktopServices, QGuiApplication, QImage, QKeySequence, QMovie, QShortcut, QTransform
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .canvas import ImageCanvas
from .controls import ElidedLabel, InfoPanel, divider, glyph, thumbnail_shortcut_button, tool_button
from .favorites import FavoriteStore
from .file_clipboard import finish_file_paste, read_file_clipboard, transfer_files, write_file_clipboard
from .file_menu import reveal_files, show_file_menu
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
QWidget#thumbnailSidebar { background: #232426; }
QToolButton#favoriteFilter { border-right: 1px solid #38383a; border-bottom: 1px solid #38383a;
    border-radius: 0; }
QToolButton#thumbnailHint { background: #232426; color: #e1c9b1; font-size: 12px;
    border: none; border-top: 1px solid #38383a; border-right: 1px solid #38383a;
    border-radius: 0; padding: 3px 10px 3px 1px; }
QToolButton#thumbnailHint::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center;
    right: 3px; width: 6px; height: 6px; }
QToolButton#thumbnailHint:hover, QToolButton#thumbnailHint:pressed { background: #39332e; }
QMenu#thumbnailShortcutMenu { background: #292a2c; border: 1px solid #504e4c; }
QToolButton#reveal, QPushButton#open { background: #f0b47b; color: #251c14; font-weight: 600;
    padding: 5px 12px; border: 1px solid #f1bd8b; }
QToolButton#reveal { padding-right: 3.5em; }
QToolButton#reveal QLabel#keyHint { color: #58381f; border-color: #b98151; }
QToolButton#reveal QLabel#keyHint:disabled { color: #85827e; border-color: #555250; }
QToolButton#reveal:hover, QPushButton#open:hover { background: #fac58f; }
QToolButton#reveal:pressed, QPushButton#open:pressed { background: #dea16a; }
QToolButton#reveal:disabled { background: #333436; border-color: #38383a; color: #85827e; }
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
    _file_operation_finished = Signal(object, object, object, str)

    def __init__(self, sample_path=None, *, settings_store=None, favorite_store=None):
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
        self._folder = None
        self._folder_files = []
        self._favorite_store = favorite_store if favorite_store is not None else FavoriteStore()
        self._favorites = set()
        self._filter_origin = None
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
        self._file_busy = False
        self._close_after_operation = False
        self._file_operation_finished.connect(self._finish_file_operation)
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
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setStyleSheet("QStatusBar { background: #232426; color: #f1bc86; padding-left: 12px; }")
        bar.hide()
        bar.messageChanged.connect(lambda text: bar.setVisible(bool(text)))
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
        self.reveal_button = tool_button("folder", "在文件管理器中显示当前图片（回车键）",
                                         self._reveal_current_file, text="打开文件位置", color="#342519")
        self.reveal_button.setObjectName("reveal")
        enter_hint = QLabel("Enter")
        enter_hint.setObjectName("keyHint")
        enter_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hint_layout = QHBoxLayout(self.reveal_button)
        hint_layout.setContentsMargins(0, 0, 9, 0)
        hint_layout.addWidget(enter_hint, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.reveal_button)
        top.addSpacing(5)
        self.info_button = tool_button("panel", "查看或隐藏照片信息（Tab）",
                                       self._set_info, checkable=True)
        self.info_button.setChecked(True)
        top.addWidget(self.info_button)
        self.full_button = tool_button("fullscreen", "进入或退出全屏（F11）",
                                       self._toggle_fullscreen, checkable=True)
        top.addWidget(self.full_button)
        self.settings_button = tool_button("settings", "设置", self.show_settings)
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
        self.thumbnail_sidebar = QWidget()
        self.thumbnail_sidebar.setObjectName("thumbnailSidebar")
        sidebar = QVBoxLayout(self.thumbnail_sidebar)
        sidebar.setContentsMargins(0, 0, 0, 0)
        sidebar.setSpacing(0)
        self.favorite_filter = tool_button("filter", "只显示当前文件夹中加过星标的照片",
                                           self._filter_favorites, text="只看星标", checkable=True)
        self.favorite_filter.setObjectName("favoriteFilter")
        self.favorite_filter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sidebar.addWidget(self.favorite_filter)
        sidebar.addWidget(self.thumbnail_list, 1)
        body.addWidget(self.thumbnail_sidebar)
        self.stage = QStackedWidget()
        self.canvas = ImageCanvas()
        self.canvas.file_menu_requested.connect(self._show_canvas_file_menu)
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
        self.prev_button = tool_button("left", "上一张（← / ↑）", lambda: self.navigate(-1))
        self.next_button = tool_button("right", "下一张（→ / ↓）", lambda: self.navigate(1))
        bottom.addWidget(self.prev_button)
        self.position = QLabel()
        self.position.setObjectName("position")
        self.position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position.setMinimumWidth(40)
        self.thumbnail_list.selectionModel().selectionChanged.connect(self._update_position)
        bottom.addWidget(self.position)
        bottom.addWidget(self.next_button)
        bottom.addSpacing(7)
        bottom.addWidget(divider(True))
        bottom.addSpacing(9)
        self.filename = ElidedLabel("filename")
        bottom.addWidget(self.filename, 1)
        self.favorite_button = tool_button("star", "加星标（F）", self._toggle_favorite, checkable=True)
        self.favorite_button.setFocusProxy(self.canvas)
        self._favorite_icons = (self.favorite_button.icon(), glyph("star-filled", "#f0b47b"))
        bottom.addWidget(self.favorite_button)
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

        def add(sequence, callback, widget=None):
            shortcut = QShortcut(QKeySequence(sequence), widget or self)
            if widget is not None:
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
            return shortcut

        view = self.thumbnail_list
        keys = QKeySequence.StandardKey
        hints = []
        for key, label, callback in (
            (keys.SelectAll, "全选", view.selectAll),
            (keys.Copy, "复制", lambda: self.copy_files(view.selected_paths())),
            (keys.Cut, "剪切", lambda: self.copy_files(view.selected_paths(), cut=True)),
            (keys.Paste, "粘贴到当前文件夹", self.paste_files),
            (keys.Delete, "移到回收站", lambda: self.trash_files(view.selected_paths())),
        ):
            shortcut = add(key, callback, view)
            hints.append((label, shortcut.key().toString(QKeySequence.SequenceFormat.NativeText)))
        add("F", self.favorite_button.click).setAutoRepeat(False)
        hints.append(("切换当前照片星标", "F"))
        self.thumbnail_hint = thumbnail_shortcut_button(view, hints)
        self.thumbnail_sidebar.layout().addWidget(self.thumbnail_hint)

        add(QKeySequence.StandardKey.Open, self.choose_file)
        reveal_shortcut = QShortcut(self.reveal_button)
        reveal_shortcut.setKeys([QKeySequence("Return"), QKeySequence("Enter")])
        reveal_shortcut.setAutoRepeat(False)
        reveal_shortcut.activated.connect(self.reveal_button.click)
        for key in ("Left", "Up"):
            add(key, lambda: self.navigate(-1))
        for key in ("Right", "Down"):
            add(key, lambda: self.navigate(1))
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
        self._update_favorite_button()
        self._set_zoom_enabled(False)

    def _load_favorites(self):
        try:
            self._favorites = self._favorite_store.in_folder(self._folder)
        except OSError as exc:
            self.statusBar().showMessage(f"无法读取星标：{exc}", 5000)
        self.thumbnail_list.set_favorites(self._favorites)

    def _update_favorite_button(self):
        path = self._displayed_path
        marked = path in self._favorites
        button = self.favorite_button
        button.setEnabled(path is not None and path == self.current_path)
        button.setChecked(marked)
        button.setIcon(self._favorite_icons[marked])
        label = "取消星标（F）" if marked else "加星标（F）"
        button.setToolTip(label)
        button.setAccessibleName(label)

    def _toggle_favorite(self, marked):
        path = self._displayed_path
        if path is None or path != self.current_path:
            return
        try:
            self._favorite_store.set_favorite(path, marked)
        except OSError as exc:
            self.statusBar().showMessage(f"无法保存星标：{exc}", 5000)
        else:
            if marked:
                self._favorites.add(path)
            else:
                self._favorites.discard(path)
            self.thumbnail_list.set_favorites(self._favorites)
            if self.favorite_filter.isChecked():
                self._apply_visible_files(path)
        self._update_favorite_button()

    def _filter_favorites(self, enabled):
        if enabled:
            self._filter_origin = self.current_path
            self._load_favorites()
        self._apply_visible_files(self.current_path or self._filter_origin)
        self.thumbnail_list.setFocus()

    def _set_zoom_enabled(self, enabled):
        for button in (self.zoom_button, self.fit_button, self.minus_button, self.plus_button):
            button.setEnabled(enabled)

    def copy_files(self, paths, *, cut=False):
        if not paths:
            return
        write_file_clipboard(QApplication.clipboard(), paths, cut=cut)
        if cut:
            # A paste in the system file manager can remove these files later.
            self._watch_folder()
        verb = "剪切" if cut else "复制"
        self.statusBar().showMessage(f"已{verb} {len(paths)} 张图片", 3000)

    def paste_files(self):
        if self._file_busy or self._folder is None:
            return
        snapshot = read_file_clipboard(QApplication.clipboard())
        if snapshot is None:
            return
        folder = self._folder
        if self.sample_path is not None and folder == self.sample_path.parent:
            self.statusBar().showMessage("请先打开目标文件夹中的一张照片，再粘贴。", 5000)
            return

        def paste():
            result = transfer_files(snapshot, folder)
            if snapshot.cut and result.pasted:
                try:
                    self._favorite_store.move_stars(result.pasted)
                except OSError as exc:
                    result.errors.append(f"图片已移动，无法更新星标：{exc}")
            return result

        def finish(result):
            finish_file_paste(QApplication.clipboard(), snapshot, result)
            if snapshot.cut and result.pasted and folder == self._folder:
                self._load_favorites()
                if self.favorite_filter.isChecked():
                    self._apply_visible_files(self.current_path or self._filter_origin)
                self._update_favorite_button()
            return f"已粘贴 {len(result.destinations)} 张图片", result.errors

        self._run_file_operation(folder, "正在粘贴图片…", paste, finish)

    def trash_files(self, paths):
        if self._file_busy or not paths:
            return
        target = paths[0].name if len(paths) == 1 else f"选中的 {len(paths)} 张图片"
        answer = QMessageBox.question(self, "移到回收站", f"将{target}移到回收站？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return

        def trash():
            errors = []
            for path in paths:
                file = QFile(str(path))
                if not path.is_file():
                    errors.append(f"{path.name}：文件已不存在或不是普通文件")
                elif not file.moveToTrash():
                    errors.append(f"{path.name}：{file.errorString()}")
            return errors

        self._run_file_operation(paths[0].parent, "正在将图片移到回收站…", trash,
                                 lambda errors: (f"已将 {len(paths) - len(errors)} 张图片移到回收站", errors))

    def _run_file_operation(self, folder, message, work, finish):
        self._file_busy = True
        self.statusBar().showMessage(message)

        def run():
            try:
                result = work()
            except Exception as exc:
                self._file_operation_finished.emit(folder, finish, None, str(exc))
            else:
                self._file_operation_finished.emit(folder, finish, result, "")

        QThreadPool.globalInstance().start(run)

    @Slot(object, object, object, str)
    def _finish_file_operation(self, folder, finish, result, error):
        self._file_busy = False
        if folder == self._folder:
            self._watch_folder()
            self._menu_refresh.start()
        message, errors = ("文件操作失败", [error]) if error else finish(result)
        self.statusBar().showMessage(message, 5000)
        if errors:
            dialog = QMessageBox(QMessageBox.Icon.Warning, "文件操作", f"{len(errors)} 项操作失败\n{errors[0]}",
                                 parent=self)
            if len(errors) > 1:
                dialog.setDetailedText("\n".join(errors))
            dialog.exec()
        if self._close_after_operation:
            self.close()

    def _watch_folder(self):
        if self._folder is not None and str(self._folder) not in self._menu_watch.directories():
            self._menu_watch.addPath(str(self._folder))

    def _reveal_current_file(self):
        if self.current_path is not None:
            reveal_files(self, (self.current_path,))

    def _show_canvas_file_menu(self, position):
        if self._displayed_path is not None:
            self._show_file_menu([self._displayed_path], position)

    def _show_file_menu(self, paths, position):
        versions = {path: image_version(path) for path in paths}
        if show_file_menu(self, paths, position) and paths[0].parent == self._folder:
            # Explorer may finish a rename, edit or move after its menu closes.
            self._watch_folder()
            self._menu_versions.update(versions)
            self._check_menu_files(versions)
            self._menu_refresh.start()

    def _menu_file_changed(self, filename):
        path = Path(filename)
        if path in self._menu_versions:
            self._check_menu_files([path])

    def _check_menu_files(self, paths):
        watched = set(self._menu_watch.files())
        new_watches = []
        for path in paths:
            previous = self._menu_versions[path]
            version = image_version(path)
            if version is None:
                self._menu_refresh.start()
                continue
            if str(path) not in watched:
                new_watches.append(str(path))
            self._menu_versions[path] = version
            if version != previous:
                if path == self.current_path:
                    self._schedule_read(path, scan=False)
                elif path in self.files:
                    self.thumbnail_list.invalidate_preview(self.files.index(path))
        if new_watches:
            self._menu_watch.addPaths(new_watches)

    def _rescan_menu_folder(self):
        path = self.current_path or next(iter(self._menu_versions), None) or next(iter(self._folder_files), None)
        if path is not None:
            self._menu_scan = self._reads.rescan_folder(
                path, self._menu_versions, self._folder_files)

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
        self._check_menu_files(self._menu_versions.keys() & known)
        if len(files) == len(self._folder_files) and all(
                old.name == new.name for old, new in zip(self._folder_files, files)):
            return
        original_path, versions = request
        selection = {renamed.get(path, path) for path in self.thumbnail_list.selected_paths()}
        selected = self.current_path or original_path
        selected = renamed.get(selected, selected)
        if renamed:
            for old, new in renamed.items():
                self._menu_versions.pop(old, None)
                self._menu_versions[new] = versions[old]
            try:
                self._favorite_store.move_stars(renamed)
            except OSError as exc:
                self.statusBar().showMessage(f"无法更新星标文件名：{exc}", 5000)
            self._check_menu_files(renamed.values())
            self._load_favorites()
        self._menu_versions = {path: version for path, version in self._menu_versions.items() if path in known}
        if not files:
            # Keep watching even when an editor temporarily removes the only image.
            self._menu_versions = versions or {original_path: None}
        self._folder_files = files
        self._apply_visible_files(selected, selection)

    def _apply_visible_files(self, selected, selection=None):
        previous_files = self.files
        files = self._folder_files
        if self.favorite_filter.isChecked():
            files = [path for path in files if path in self._favorites]
        self.files = files
        self.thumbnail_list.set_files(files)
        if not files:
            self._reads.reset()
            self._loading_hint.stop()
            self._stop_animation()
            self._index = -1
            self.current_path = None
            self.canvas.set_image(QImage(), keep_view=bool(self._folder_files) and self._settings.keep_zoom_position)
            self.info_panel.set_details(None, {})
            self.filename.set_full_text("")
            self.filename.setToolTip("")
            self.setWindowTitle("HiFine")
            if self.favorite_filter.isChecked() and self._folder_files:
                self._show_state("还没有星标照片", "点「只看星标」返回全部照片，按 F 给喜欢的照片加星标。")
            else:
                self._show_state("文件夹中没有图片", open_button=True)
            self._update_navigation()
            return

        if selected in files:
            self._index = files.index(selected)
        elif selected in self._folder_files:
            # When filtering or removing a star, prefer the next marked shot.
            next_path = next((p for p in self._folder_files[self._folder_files.index(selected) + 1:]
                              if p in self._favorites), files[-1])
            self._index = files.index(next_path)
        else:
            self._index = min(max(self._index, 0), len(files) - 1)
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
        if selection is not None and (selection.intersection(files) or (previous_files and not selection)):
            self.thumbnail_list.set_selected_paths(selection)

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
        path = Path(os.path.abspath(Path(path).expanduser()))
        self._menu_scan = None
        if self._folder != path.parent:
            self._clear_menu_watch()
        self._folder = path.parent
        self._folder_files = []
        self._filter_origin = None
        self.favorite_filter.setChecked(False)
        self._favorites = set()
        self._load_favorites()
        self.thumbnail_list.set_files([])
        self.thumbnail_list.setFocus()
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
        self.canvas.set_image(QImage(), keep_view=self._settings.keep_zoom_position)
        self._show_state("正在读取图片…")

    @Slot(object, object, object, str)
    def _read_finished(self, path, siblings, frame, error):
        self._loading_hint.stop()
        # An explicit open scans a folder and starts with the whole image in view.
        keep_view = self._settings.keep_zoom_position and siblings is None
        self._show_path(path)
        if siblings is not None:
            self._folder_files = siblings
            self.files = siblings
            self._index = self.files.index(path)
            self.thumbnail_list.set_files(siblings)
            self._reads.set_neighbors(self._neighbors())
        self._update_navigation()
        self.thumbnail_list.sync_current(self._index, frame)
        details = frame.metadata if frame is not None else {}
        self.info_panel.set_details(path, details)
        if error:
            self.canvas.set_image(QImage(), keep_view=keep_view)
            self._show_state("无法打开这张图片", error, open_button=True)
        else:
            self.stage.setCurrentWidget(self.canvas)
            self._displayed_path = path
            self._update_favorite_button()
            self.canvas.set_image(frame.image, keep_view=keep_view)
            self._set_zoom_enabled(True)
            if details.get("animated"):
                self._start_animation(path, details.get("animation_orientation", 1))

    def closeEvent(self, event):
        if self._file_busy:
            self._close_after_operation = True
            event.ignore()
            return
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
        self.favorite_filter.setEnabled(bool(self._folder_files) or self.favorite_filter.isChecked())
        self._update_favorite_button()
        self.reveal_button.setEnabled(self.current_path is not None)
        self.prev_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(0 <= self._index < len(self.files) - 1)
        self._update_position()

    def _update_position(self):
        text = f"{self._index + 1} / {len(self.files)}" if self.files else "—"
        count = sum(span.height() for span in self.thumbnail_list.selectionModel().selection())
        if count > 1:
            text += f" · 已选 {count} 张 · 右键批量操作"
        self.position.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "thumbnail_hint"):
            width = max(105, min(176, round(self.width() * 0.15)))
            self.thumbnail_sidebar.setFixedWidth(max(width, self.thumbnail_hint.sizeHint().width()))
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
