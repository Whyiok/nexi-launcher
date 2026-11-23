"""Small helpers used across the launcher."""

import ctypes
import json
import os
import platform
import re
import subprocess
import threading
from ctypes import wintypes
from pathlib import Path


class InstallCancelled(Exception):
    pass


def safe_filename(name: str) -> str:
    base = Path(str(name)).name
    return base if base else "mod.jar"


def format_count(value) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return str(value)
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def _version_key(version_id):
    parts = re.split(r"[.\-+]", version_id)
    return [(0, int(part)) if part.isdigit() else (1, part) for part in parts]


def open_in_system(path) -> None:
    """Open a file or folder with the system's default handler."""
    try:
        if os.name == "nt":
            os.startfile(str(path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


# ---------------------------------------------------------------- file picker
#
# The launcher used to open its "Browse" dialogs through a hidden PowerShell
# process running System.Windows.Forms. That works, but spawning PowerShell to
# show a file dialog is a classic malware pattern, so setup and antivirus
# heuristics flag the built exe for nothing. The Windows common dialog is a
# plain Win32 call and can be driven directly with ctypes.

_PICK_LOCK = threading.Lock()

_OFN_READONLY = 0x00000001
_OFN_HIDEREADONLY = 0x00000004
_OFN_NOCHANGEDIR = 0x00000008
_OFN_PATHMUSTEXIST = 0x00000800
_OFN_FILEMUSTEXIST = 0x00001000
_OFN_EXPLORER = 0x00080000
_OFN_DONTADDTORECENT = 0x02000000

_OPEN_FILENAME_W = None


class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


def _dialog_filters(filters) -> str:
    """Build the double-NUL separated ``lpstrFilter`` string."""
    parts = []
    for label, pattern in filters:
        parts.append(f"{label} ({pattern})")
        parts.append(pattern)
    return "\0".join(parts) + "\0\0"


def _run_open_dialog(title: str, filters, default_ext: str) -> str:
    """Show the modal dialog on the calling thread; "" when cancelled."""
    global _OPEN_FILENAME_W
    if _OPEN_FILENAME_W is None:
        comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
        comdlg32.GetOpenFileNameW.argtypes = [
            ctypes.POINTER(_OPENFILENAMEW)]
        comdlg32.GetOpenFileNameW.restype = wintypes.BOOL
        comdlg32.CommDlgExtendedError.restype = wintypes.DWORD
        _OPEN_FILENAME_W = comdlg32

    buffer = ctypes.create_unicode_buffer(32768)
    filter_text = ctypes.create_unicode_buffer(_dialog_filters(filters))
    owner = ctypes.windll.user32.GetForegroundWindow()
    info = _OPENFILENAMEW()
    info.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    info.hwndOwner = owner
    info.lpstrFilter = ctypes.cast(filter_text, ctypes.c_wchar_p)
    info.nFilterIndex = 1
    info.lpstrFile = ctypes.cast(buffer, ctypes.c_wchar_p)
    info.nMaxFile = len(buffer)
    info.lpstrTitle = title
    info.lpstrDefExt = default_ext or None
    info.Flags = (_OFN_EXPLORER | _OFN_FILEMUSTEXIST | _OFN_PATHMUSTEXIST
                  | _OFN_NOCHANGEDIR | _OFN_HIDEREADONLY
                  | _OFN_DONTADDTORECENT)

    if _OPEN_FILENAME_W.GetOpenFileNameW(ctypes.byref(info)):
        return buffer.value
    error = _OPEN_FILENAME_W.CommDlgExtendedError()
    if error:
        raise OSError(f"the file dialog failed (code {error})")
    return ""


def pick_file(title="Select a file", filters=None, default_ext="") -> str:
    """Show the Windows "Open file" dialog and return the chosen path.

    Returns an empty string when the user cancels, raises ``OSError`` when the
    dialog itself could not be shown, and returns "" on other platforms (the
    callers keep their text-input fallback there).
    """
    if os.name != "nt":
        return ""
    filters = tuple(filters or (("All files", "*.*"),))
    result = {"path": "", "error": None}

    def run():
        # The common dialog is a shell window and expects an STA thread.
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 2)
            initialised = True
        except OSError:
            initialised = False
        try:
            result["path"] = _run_open_dialog(title, filters, default_ext)
        except Exception as exc:  # noqa: BLE001 - re-raised in the caller
            result["error"] = exc
        finally:
            if initialised:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except OSError:
                    pass

    # One dialog at a time: two stacked pickers confuse the shell.
    with _PICK_LOCK:
        worker = threading.Thread(target=run, name="nexi-file-picker",
                                  daemon=True)
        worker.start()
        worker.join()
    if result["error"] is not None:
        raise result["error"]
    return result["path"]


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wintypes.LPWSTR),
        ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    ]


_BIF_RETURNONLYFSDIRS = 0x0001
_BIF_EDITBOX = 0x0010
_BIF_NEWDIALOGSTYLE = 0x0040


def _run_folder_dialog(title: str, initial: str) -> str:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHBrowseForFolderW.argtypes = [
        ctypes.POINTER(_BROWSEINFOW)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p,
                                             wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    shell32.SHParseDisplayName.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    shell32.SHParseDisplayName.restype = ctypes.c_long

    root = ctypes.c_void_p()
    if initial:
        attrs = wintypes.DWORD()
        if shell32.SHParseDisplayName(str(initial), None, ctypes.byref(root),
                                      0, ctypes.byref(attrs)) != 0:
            root = ctypes.c_void_p()

    display = ctypes.create_unicode_buffer(260)
    info = _BROWSEINFOW()
    info.hwndOwner = ctypes.windll.user32.GetForegroundWindow()
    info.pidlRoot = root
    info.pszDisplayName = ctypes.cast(display, ctypes.c_wchar_p)
    info.lpszTitle = title
    info.ulFlags = (_BIF_RETURNONLYFSDIRS | _BIF_EDITBOX
                    | _BIF_NEWDIALOGSTYLE)
    try:
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return ""
        buffer = ctypes.create_unicode_buffer(32768)
        try:
            if not shell32.SHGetPathFromIDListW(pidl, buffer):
                return ""
            return buffer.value
        finally:
            ole32.CoTaskMemFree(pidl)
    finally:
        if root:
            ole32.CoTaskMemFree(root)


def pick_folder(title="Select a folder", initial="") -> str:
    """Show the Windows folder picker; "" when cancelled or not on Windows."""
    if os.name != "nt":
        return ""
    result = {"path": "", "error": None}

    def run():
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 2)
            initialised = True
        except OSError:
            initialised = False
        try:
            result["path"] = _run_folder_dialog(title, str(initial or ""))
        except Exception as exc:  # noqa: BLE001 - re-raised in the caller
            result["error"] = exc
        finally:
            if initialised:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except OSError:
                    pass

    with _PICK_LOCK:
        worker = threading.Thread(target=run, name="nexi-folder-picker",
                                  daemon=True)
        worker.start()
        worker.join()
    if result["error"] is not None:
        raise result["error"]
    return result["path"]


def copy_image_to_clipboard(path) -> bool:
    """Put an image file on the clipboard (Windows only).

    ``Clipboard::Flush`` renders every format before the helper process
    exits — without it Windows drops the data with the process.
    """
    if os.name != "nt":
        return False
    escaped = str(path).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        f"$img=[System.Drawing.Image]::FromFile('{escaped}');"
        "$bmp=New-Object System.Drawing.Bitmap $img;"
        "[System.Windows.Forms.Clipboard]::SetImage($bmp);"
        "[System.Windows.Forms.Clipboard]::Flush();"
        "$bmp.Dispose();$img.Dispose()"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _read_json(path):
    """Parse JSON tolerating a UTF-8 BOM (editors and PowerShell add one)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
