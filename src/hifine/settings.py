"""Persistent preferences shared by the desktop viewer and its settings dialog."""

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings


DEFAULT_CACHE_ENTRIES = 8
DEFAULT_CACHE_MIB = 256
MAX_SETTING_INT = 2**31 - 1  # QSpinBox stores signed 32-bit integers.


def _valid_limit(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_SETTING_INT


def _read_limit(store: QSettings, key: str, default: int) -> int:
    value = store.value(key, default)
    if isinstance(value, str):
        # Qt's INI backend can return numbers as strings.
        try:
            value = int(value)
        except ValueError:
            return default
    return value if _valid_limit(value) else default


@dataclass(frozen=True)
class AppSettings:
    cache_max_entries: int = DEFAULT_CACHE_ENTRIES
    cache_max_mib: int = DEFAULT_CACHE_MIB
    mirrorchyan_cdk: str = field(default="", repr=False)

    def __post_init__(self):
        if not _valid_limit(self.cache_max_entries) or not _valid_limit(self.cache_max_mib):
            raise ValueError(f"Cache limits must be integers between 1 and {MAX_SETTING_INT}")

    @classmethod
    def load(cls, store: QSettings | None = None) -> "AppSettings":
        if store is None:
            store = QSettings("HiFine", "HiFine")
        cdk = store.value("updates/mirrorchyanCdk", "")
        return cls(
            cache_max_entries=_read_limit(store, "cache/maxEntries", DEFAULT_CACHE_ENTRIES),
            cache_max_mib=_read_limit(store, "cache/maxMiB", DEFAULT_CACHE_MIB),
            mirrorchyan_cdk=cdk.strip() if isinstance(cdk, str) else "",
        )

    def save(self, store: QSettings | None = None) -> None:
        if store is None:
            store = QSettings("HiFine", "HiFine")
        store.setValue("cache/maxEntries", self.cache_max_entries)
        store.setValue("cache/maxMiB", self.cache_max_mib)
        if self.mirrorchyan_cdk:
            store.setValue("updates/mirrorchyanCdk", self.mirrorchyan_cdk)
        else:
            store.remove("updates/mirrorchyanCdk")
        store.sync()
        if store.status() != QSettings.Status.NoError:
            raise OSError(f"无法写入设置（{store.fileName()}）")
