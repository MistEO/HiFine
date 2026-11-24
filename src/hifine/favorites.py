"""Per-user photo stars, kept separately from the image files."""

from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3

from PySide6.QtCore import QStandardPaths


def _absolute(path):
    return Path(os.path.abspath(os.path.expanduser(path)))


def _file_key(path):
    return os.path.normcase(str(path.parent)), os.path.normcase(path.name)


class FavoriteStore:
    def __init__(self, database=None):
        if database is None:
            folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
            database = Path(folder) / "favorites.sqlite3"
        self.database = _absolute(database)

    @contextmanager
    def _connect(self, *, write):
        try:
            if write:
                self.database.parent.mkdir(parents=True, exist_ok=True)
                uri = self.database.as_uri()
            else:
                uri = self.database.as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db, db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("CREATE TABLE IF NOT EXISTS favorites ("
                               "folder TEXT, file_key TEXT, filename TEXT NOT NULL, "
                               "PRIMARY KEY (folder, file_key)) WITHOUT ROWID")
                yield db
        except sqlite3.Error as exc:
            raise OSError(str(exc)) from exc

    def in_folder(self, folder):
        """Return absolute paths. Browsing a new installation never creates a database."""
        if not self.database.exists():
            return set()
        folder = _absolute(folder)
        with self._connect(write=False) as db:
            # Another process can be just about to commit the first star.
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='favorites'").fetchone():
                return set()
            rows = db.execute("SELECT filename FROM favorites WHERE folder = ?", (os.path.normcase(str(folder)),))
            return {folder / name for (name,) in rows}

    @staticmethod
    def _add(db, path):
        db.execute("INSERT OR REPLACE INTO favorites (folder, file_key, filename) VALUES (?, ?, ?)",
                   (*_file_key(path), path.name))

    @staticmethod
    def _remove(db, path):
        result = db.execute("DELETE FROM favorites WHERE folder = ? AND file_key = ?", _file_key(path))
        return result.rowcount > 0

    def set_favorite(self, path, enabled):
        if not enabled and not self.database.exists():
            return
        path = _absolute(path)
        with self._connect(write=True) as db:
            if enabled:
                self._add(db, path)
            else:
                self._remove(db, path)

    def move_stars(self, paths):
        """Transfer the stars that belonged to the moved files before this operation."""
        if not paths or not self.database.exists():
            return
        with self._connect(write=True) as db:
            destinations = []
            for old, new in paths.items():
                if self._remove(db, _absolute(old)):
                    destinations.append(new)
            for new in destinations:
                self._add(db, _absolute(new))
