"""Windows image reads that let file managers move the file during decoding."""

import _winapi
import msvcrt
import os


def open_image_fd(path):
    """Return a read-only descriptor owned by the caller."""
    share = 0x1 | 0x2 | 0x4  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    handle = _winapi.CreateFile(str(path), _winapi.GENERIC_READ, share, 0, _winapi.OPEN_EXISTING, 0, 0)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        _winapi.CloseHandle(handle)
        raise
