"""Delete files and folders by moving them to the Recycle Bin (Windows), so a mistaken delete can be undone.

Other systems have no standard-library recycle bin; there the items are removed for good.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def to_trash(paths: list[Path]) -> bool:
    """Remove ``paths`` (files or folders). True when they went to the Recycle Bin, False when deleted outright."""
    paths = [p for p in paths if p.exists()]
    if not paths:
        return sys.platform == "win32"
    if sys.platform == "win32" and _windows_recycle(paths):
        return True
    for p in paths:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    return False


def _windows_recycle(paths: list[Path]) -> bool:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    # A list of absolute paths, each ending in a NUL, the whole list ending in a second NUL.
    names = "\0".join(str(p.resolve()) for p in paths) + "\0\0"
    op = SHFILEOPSTRUCTW(None, FO_DELETE, names, None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return result == 0 and not op.fAnyOperationsAborted and not any(p.exists() for p in paths)
