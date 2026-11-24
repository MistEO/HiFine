"""Exercise the Shell binding without invoking desktop applications on the test machine."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest
from PySide6.QtCore import QMimeData, QPoint, QUrl


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows Shell")
def test_reveal_selects_files_in_explorer(monkeypatch, tmp_path):
    import ctypes as c
    from ctypes import wintypes as w
    from hifine import file_menu, windows_menu as shell

    paths = (tmp_path / "照片 #01.png", tmp_path / "照片 02.png")
    for path in paths:
        path.touch()
    combine = shell._api(shell._shell, "ILCombine", shell._ptr, shell._ptr, shell._ptr)
    get_path = shell._api(shell._shell, "SHGetPathFromIDListW", w.BOOL, shell._ptr, w.LPWSTR)
    selected = []

    def inspect_selection(folder, count, children, flags):
        assert flags == 0
        for child in children[:count]:
            full_id = combine(folder, child)
            try:
                name = c.create_unicode_buffer(260)
                assert get_path(full_id, name)
                selected.append(Path(name.value))
            finally:
                shell._free(full_id)

    monkeypatch.setattr(shell, "_select", inspect_selection)
    file_menu.reveal_files(None, paths)
    assert tuple(selected) == paths


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows Shell")
@pytest.mark.parametrize("names", [("照片 01.png",), ("照片 01.png", "照片 02.jpg")])
def test_shell_menu_command_and_cancel(monkeypatch, tmp_path, names):
    import ctypes as c
    from ctypes import wintypes as w
    from hifine import file_menu, windows_menu as shell

    paths = [tmp_path / name for name in names]
    for path in paths:
        Image.new("RGB", (5, 7)).save(path)
    selection = paths[0] if len(paths) == 1 else paths
    # Qt's offscreen plugin has no HWND. A hidden Windows control provides a
    # real owner for Shell extensions and does not take focus from the desktop.
    create = shell._api(shell._user, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR,
                        w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID)
    destroy = shell._api(shell._user, "DestroyWindow", w.BOOL, w.HWND)
    count = shell._api(shell._user, "GetMenuItemCount", c.c_int, w.HMENU)
    item_id = shell._api(shell._user, "GetMenuItemID", w.UINT, w.HMENU, c.c_int)
    item_label = shell._api(shell._user, "GetMenuStringW", c.c_int, w.HMENU, w.UINT, w.LPWSTR, c.c_int, w.UINT)
    hwnd = create(0, "STATIC", "HiFine test", 0x80000000, 10, 20, 100, 100, None, None, None, None)
    assert hwnd
    window = SimpleNamespace(winId=lambda: hwnd, devicePixelRatioF=lambda: 1.0, mapFromGlobal=lambda p: p,
                             paste_files=Mock())
    mime = QMimeData()
    clipboard = SimpleNamespace(mimeData=lambda: mime)
    monkeypatch.setattr(file_menu, "QApplication", SimpleNamespace(clipboard=lambda: clipboard))
    verbs = {}
    invoked = []
    populate = shell._populate
    get_ui = shell._get_ui

    def selection_ui(folder, owner, size, children, *args):
        assert size == len(paths)
        assert len(set(children[:size])) == size
        return get_ui(folder, owner, size, children, *args)

    def read_menu(context, menu, index, first, last, flags):
        # The test replaces TrackPopupMenuEx and its message loop. Finish
        # submenu construction before destroying the test menu and COM apartment.
        result = populate(context, menu, index, first, last, flags | 0x1000)  # CMF_SYNCCASCADEMENU
        for row in range(count(menu)):
            command = item_id(menu, row)
            if first <= command <= last:
                verb = c.create_unicode_buffer(256)
                if shell._get_verb(context, command - first, 4, None, verb, len(verb)) == 0:
                    verbs[verb.value.lower()] = command
        return result

    def invoke(context, info_ptr):
        info = c.cast(info_ptr, c.POINTER(shell._InvokeInfo)).contents
        invoked.append((info.lpVerb, info.lpVerbW, info.hwnd, Path(info.lpDirectoryW)))

    def choose_paste_if_present(menu, *args):
        label = c.create_unicode_buffer(128)
        item_label(menu, shell._PASTE_COMMAND, label, len(label), 0)  # MF_BYCOMMAND
        if not mime.hasUrls():
            assert not label.value
            return 0
        assert label.value == "粘贴到当前文件夹"
        return shell._PASTE_COMMAND

    monkeypatch.setattr(shell, "_get_ui", selection_ui)
    monkeypatch.setattr(shell, "_populate", read_menu)
    monkeypatch.setattr(shell, "_track", lambda *args: verbs["properties"])
    monkeypatch.setattr(shell, "_invoke", invoke)
    try:
        assert shell.show_shell_menu(window, selection, QPoint(2, 3))
        assert {"properties", "copy"} <= verbs.keys()
        assert ("rename" in verbs) == (len(paths) == 1)
        offset = verbs["properties"] - 1
        assert invoked == [(offset, offset, hwnd, tmp_path)]
        monkeypatch.setattr(shell, "_track", choose_paste_if_present)
        assert not file_menu.show_file_menu(window, selection, QPoint(2, 3))
        window.paste_files.assert_not_called()
        mime.setUrls([QUrl.fromLocalFile(str(paths[0]))])
        assert file_menu.show_file_menu(window, selection, QPoint(2, 3))
        window.paste_files.assert_called_once_with()
        assert len(invoked) == 1
    finally:
        destroy(hwnd)
