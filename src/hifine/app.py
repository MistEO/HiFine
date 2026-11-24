"""Desktop entry point, Finder file-open events and the thumbnailer command."""

import argparse
from pathlib import Path
import sys

from hifine import __version__


ASSETS = Path(__file__).resolve().parent / "assets"
SAMPLE = ASSETS / "samples" / "大棱镜泉.hif"


def write_thumbnail(source: Path, destination: Path, size: int) -> int:
    from hifine.imaging import ImageLoadError, make_thumbnail

    if not 1 <= size <= 4096:
        return 2
    try:
        with make_thumbnail(source, size) as picture:
            picture.save(destination, "PNG")
    except (ImageLoadError, OSError, ValueError) as exc:
        if sys.stderr:
            print(exc, file=sys.stderr)
        return 1
    return 0


def show_viewer(path: Path | None) -> int:
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from hifine.viewer import MainWindow

    class DesktopApplication(QApplication):
        window = None
        pending_file = None

        def event(self, event):
            if event.type() == QEvent.Type.FileOpen and event.file():
                self.pending_file = Path(event.file())
                if self.window is not None:
                    self.window.open_file(self.pending_file)
                    self.window.raise_()
                    self.window.activateWindow()
                return True
            return super().event(event)

    app = DesktopApplication([sys.argv[0]])
    app.setApplicationName("HiFine")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("HiFine")
    app.setDesktopFileName("io.github.hifine.HiFine")
    app.setWindowIcon(QIcon(str(ASSETS / "HiFine.png")))
    window = MainWindow(sample_path=SAMPLE)
    app.window = window

    # Finder can deliver the selected document during QApplication construction
    # or immediately after the event loop starts.
    if app.pending_file or path:
        window.open_file(app.pending_file or path)
    else:
        QTimer.singleShot(0, lambda: window.open_sample() if app.pending_file is None else None)
    window.show()
    QTimer.singleShot(0, window.start_update_check)
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="HiFine")
    parser.add_argument("--version", action="version", version=f"HiFine {__version__}")
    parser.add_argument("--thumbnail", nargs=3, metavar=("INPUT", "OUTPUT", "SIZE"),
                        help="write a PNG thumbnail without opening the viewer")
    parser.add_argument("file", nargs="?", type=Path)
    args = parser.parse_args(argv)
    if args.thumbnail:
        source, output, size = args.thumbnail
        if not size.isascii() or not size.isdecimal() or len(size) > 4:
            parser.error("thumbnail size must be an integer from 1 to 4096")
        return write_thumbnail(Path(source), Path(output), int(size))
    return show_viewer(args.file)
