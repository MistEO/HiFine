"""Host the Windows Shell's IContextMenu for a selection in one folder."""

import ctypes as c
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from pathlib import Path
from uuid import UUID


_ole = c.WinDLL("ole32")
_shell = c.WinDLL("shell32")
_user = c.WinDLL("user32", use_last_error=True)
_controls = c.WinDLL("comctl32", use_last_error=True)
_ptr = c.c_void_p
_out = c.POINTER(_ptr)
_subclass_proc = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM,
                               c.c_size_t, c.c_size_t)


class _InvokeInfo(c.Structure):
    # CMINVOKECOMMANDINFOEX. Both verb fields hold a numeric command offset.
    _fields_ = [
        ("cbSize", w.DWORD), ("fMask", w.DWORD), ("hwnd", w.HWND),
        ("lpVerb", _ptr), ("lpParameters", w.LPCSTR), ("lpDirectory", w.LPCSTR),
        ("nShow", c.c_int), ("dwHotKey", w.DWORD), ("hIcon", w.HICON),
        ("lpTitle", w.LPCSTR), ("lpVerbW", _ptr), ("lpParametersW", w.LPCWSTR),
        ("lpDirectoryW", w.LPCWSTR), ("lpTitleW", w.LPCWSTR), ("ptInvoke", w.POINT),
    ]


def _api(library, name, result, *args):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = args
    return function


_ole_initialize = _api(_ole, "OleInitialize", c.HRESULT, _ptr)
_ole_uninitialize = _api(_ole, "OleUninitialize", None)
_free = _api(_ole, "CoTaskMemFree", None, _ptr)
_parse = _api(_shell, "SHParseDisplayName", c.HRESULT, w.LPCWSTR, _ptr, _out, w.DWORD, _ptr)
_last_child = _api(_shell, "ILFindLastID", _ptr, _ptr)
_bind_parent = _api(_shell, "SHBindToParent", c.HRESULT, _ptr, _ptr, _out, _out)
_select = _api(_shell, "SHOpenFolderAndSelectItems", c.HRESULT, _ptr, w.UINT, _out, w.DWORD)
_create_menu = _api(_user, "CreatePopupMenu", w.HMENU)
_append_menu = _api(_user, "AppendMenuW", w.BOOL, w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR)
_destroy_menu = _api(_user, "DestroyMenu", w.BOOL, w.HMENU)
_track = _api(_user, "TrackPopupMenuEx", w.UINT, w.HMENU, w.UINT, c.c_int, c.c_int, w.HWND, _ptr)
_to_screen = _api(_user, "ClientToScreen", w.BOOL, w.HWND, c.POINTER(w.POINT))
_key_state = _api(_user, "GetKeyState", c.c_short, c.c_int)
_subclass = _api(_controls, "SetWindowSubclass", w.BOOL, w.HWND, _subclass_proc, c.c_size_t, c.c_size_t)
_unsubclass = _api(_controls, "RemoveWindowSubclass", w.BOOL, w.HWND, _subclass_proc, c.c_size_t)
_default_proc = _api(_controls, "DefSubclassProc", c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

# COM vtable slots from IUnknown, IShellFolder and IContextMenu{,2,3}.
_query = c.WINFUNCTYPE(w.LONG, _ptr, _out)(0, "QueryInterface")
_release = c.WINFUNCTYPE(w.ULONG)(2, "Release")
_get_ui = c.WINFUNCTYPE(c.HRESULT, w.HWND, w.UINT, _out, _ptr, _ptr, _out)(10, "GetUIObjectOf")
_populate = c.WINFUNCTYPE(c.HRESULT, w.HMENU, w.UINT, w.UINT, w.UINT, w.UINT)(3, "QueryContextMenu")
_invoke = c.WINFUNCTYPE(c.HRESULT, c.POINTER(_InvokeInfo))(4, "InvokeCommand")
_get_verb = c.WINFUNCTYPE(w.LONG, c.c_size_t, w.UINT, _ptr, w.LPWSTR, w.UINT)(5, "GetCommandString")
_handle_msg = c.WINFUNCTYPE(w.LONG, w.UINT, w.WPARAM, w.LPARAM)(6, "HandleMenuMsg")
_handle_msg2 = c.WINFUNCTYPE(w.LONG, w.UINT, w.WPARAM, w.LPARAM,
                             c.POINTER(c.c_ssize_t))(7, "HandleMenuMsg2")

_SHELL_FOLDER = UUID("000214e6-0000-0000-c000-000000000046").bytes_le
_CONTEXT_MENU = UUID("000214e4-0000-0000-c000-000000000046").bytes_le
_CONTEXT_MENU2 = UUID("000214f4-0000-0000-c000-000000000046").bytes_le
_CONTEXT_MENU3 = UUID("bcfce0a0-ec17-11d0-8d10-00a0c90f2719").bytes_le
_WM_DRAWITEM, _WM_MEASUREITEM, _WM_INITMENUPOPUP, _WM_MENUCHAR = 0x2B, 0x2C, 0x117, 0x120
_PASTE_COMMAND = 0x8000  # Host command above the range reserved for Shell verbs.


@contextmanager
def _menu_messages(hwnd, context):
    """Let Shell extensions populate submenus, draw items and handle mnemonic keys."""
    handler = _ptr()
    has_menu3 = _query(context, _CONTEXT_MENU3, c.byref(handler)) == 0
    if not has_menu3 and _query(context, _CONTEXT_MENU2, c.byref(handler)) != 0:
        yield
        return

    @_subclass_proc
    def dispatch(window, message, wparam, lparam, subclass_id, data):
        drawing = message in (_WM_DRAWITEM, _WM_MEASUREITEM) and wparam == 0
        if drawing or message == _WM_INITMENUPOPUP or (has_menu3 and message == _WM_MENUCHAR):
            result = c.c_ssize_t()
            if has_menu3:
                status = _handle_msg2(handler, message, wparam, lparam, c.byref(result))
            else:
                status = _handle_msg(handler, message, wparam, lparam)
            if status == 0:
                return 1 if drawing else result.value
        return _default_proc(window, message, wparam, lparam)

    with ExitStack() as cleanup:
        cleanup.callback(_release, handler)
        if not _subclass(hwnd, dispatch, 1, 0):
            raise c.WinError(c.get_last_error())
        cleanup.callback(_unsubclass, hwnd, dispatch, 1)
        yield


@contextmanager
def _shell_item_ids(paths):
    with ExitStack() as cleanup:
        _ole_initialize(None)
        cleanup.callback(_ole_uninitialize)
        pidls = []
        for path in paths:
            pidl = _ptr()
            _parse(str(path), None, c.byref(pidl), 0, None)
            cleanup.callback(_free, pidl)
            pidls.append(pidl)
        yield pidls


def select_files(paths):
    """Open the containing Explorer folder and select its files."""
    with _shell_item_ids((paths[0].parent, *paths)) as (folder, *items):
        children = (_ptr * len(items))(*(_last_child(item) for item in items))
        _select(folder, len(children), children, 0)


def show_shell_menu(window, paths, global_pos, *, paste=None):
    paths = (paths,) if isinstance(paths, Path) else tuple(paths)
    if not paths or any(path.parent != paths[0].parent for path in paths):
        return False
    hwnd = int(window.winId())
    # Qt positions are logical. ClientToScreen supplies the native origin even
    # on secondary monitors with a different scale or negative coordinates.
    local = window.mapFromGlobal(global_pos)
    scale = window.devicePixelRatioF()
    point = w.POINT(round(local.x() * scale), round(local.y() * scale))
    if not _to_screen(hwnd, c.byref(point)):
        raise c.WinError(c.get_last_error())

    with _shell_item_ids(paths) as pidls, ExitStack() as cleanup:
        folder, context = _ptr(), _ptr()
        _bind_parent(pidls[0], _SHELL_FOLDER, c.byref(folder), None)
        cleanup.callback(_release, folder)
        children = (_ptr * len(pidls))(*(_last_child(pidl) for pidl in pidls))
        _get_ui(folder, hwnd, len(children), children, _CONTEXT_MENU, None, c.byref(context))
        cleanup.callback(_release, context)
        menu = _create_menu()
        if not menu:
            raise c.WinError(c.get_last_error())
        cleanup.callback(_destroy_menu, menu)

        flags = 0x10 if len(paths) == 1 else 0  # CMF_CANRENAME
        if _key_state(0x10) < 0:  # VK_SHIFT
            flags |= 0x100  # CMF_EXTENDEDVERBS
        _populate(context, menu, 0, 1, _PASTE_COMMAND - 1, flags)
        if paste is not None:
            if not _append_menu(menu, 0x800, 0, None):  # MF_SEPARATOR
                raise c.WinError(c.get_last_error())
            if not _append_menu(menu, 0, _PASTE_COMMAND, "粘贴到当前文件夹"):
                raise c.WinError(c.get_last_error())
        with _menu_messages(hwnd, context):
            command = _track(menu, 0x102, point.x, point.y, hwnd, None)  # TPM_RETURNCMD | TPM_RIGHTBUTTON
        if not command:
            return False
        if command == _PASTE_COMMAND and paste is not None:
            paste()
            return True

        offset = command - 1
        verb = c.create_unicode_buffer(128)
        if (len(paths) == 1 and _get_verb(context, offset, 4, None, verb, len(verb)) == 0
                and verb.value.lower() == "rename"):
            # Rename needs an editable Shell view. Explorer selects this file
            # and opens its native filename editor (OFASI_EDIT).
            _select(pidls[0], 0, None, 1)
            return True
        mask = 0x20004000  # CMIC_MASK_PTINVOKE | CMIC_MASK_UNICODE
        if _key_state(0x10) < 0:
            mask |= 0x10000000  # CMIC_MASK_SHIFT_DOWN
        if _key_state(0x11) < 0:
            mask |= 0x40000000  # CMIC_MASK_CONTROL_DOWN
        directory = str(paths[0].parent)
        info = _InvokeInfo(cbSize=c.sizeof(_InvokeInfo), fMask=mask, hwnd=hwnd, nShow=1,
                           lpVerb=offset, lpVerbW=offset, lpDirectory=directory.encode("mbcs", "replace"),
                           lpDirectoryW=directory, ptInvoke=point)
        _invoke(context, c.byref(info))
        return True
