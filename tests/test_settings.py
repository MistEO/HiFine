import pytest
from PySide6.QtCore import QSettings

from hifine.settings import AppSettings, MAX_SETTING_INT


def ini(path):
    return QSettings(str(path), QSettings.Format.IniFormat)


def test_settings_round_trip(tmp_path):
    path = tmp_path / "hifine.ini"
    store = ini(path)
    assert AppSettings.load(store) == AppSettings(8, 256)

    store.setValue("appearance/theme", "dark")
    chosen = AppSettings(cache_max_entries=12, cache_max_mib=768, mirrorchyan_cdk="example-cdk",
                         keep_zoom_position=True)
    chosen.save(store)

    reopened = ini(path)
    assert AppSettings.load(reopened) == chosen
    assert reopened.value("appearance/theme") == "dark"
    assert chosen.mirrorchyan_cdk not in repr(chosen)
    AppSettings().save(reopened)
    assert AppSettings.load(ini(path)).mirrorchyan_cdk == ""
    assert not reopened.contains("updates/mirrorchyanCdk")


@pytest.mark.parametrize("bad", ["many", 0, -1, MAX_SETTING_INT + 1, True, 1.5])
def test_invalid_stored_limit_only_resets_that_field(tmp_path, bad):
    store = ini(tmp_path / "hifine.ini")
    store.setValue("cache/maxEntries", bad)
    store.setValue("cache/maxMiB", "512")
    assert AppSettings.load(store) == AppSettings(8, 512)


def test_settings_report_write_failure(tmp_path):
    parent_file = tmp_path / "file"
    parent_file.touch()
    with pytest.raises(OSError):
        AppSettings().save(ini(parent_file / "hifine.ini"))
