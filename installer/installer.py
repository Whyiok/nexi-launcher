"""Nexi Launcher setup and uninstaller.

The file is built into a single self-contained ``NexiLauncher-Setup.exe`` that
carries ``Nexi-Portable.exe`` inside it (see ``build_installer.ps1``). It
installs the launcher per user, so no administrator rights are needed:

    %LOCALAPPDATA%\\Programs\\Nexi Launcher\\
        Nexi-Portable.exe
        Uninstall.exe        a copy of this setup exe

A Start Menu shortcut is always created, a desktop shortcut is optional, and an
entry is written to ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\
Uninstall\\NexiLauncher`` so the launcher also appears in Windows Settings →
Apps. User data in ``%APPDATA%\\NexiLauncher`` is left alone on uninstall
unless the user explicitly asks to delete it.

Command line:
    NexiLauncher-Setup.exe
    NexiLauncher-Setup.exe --uninstall
    NexiLauncher-Setup.exe --silent [--dir PATH] [--no-shortcuts] [--no-launch]
    NexiLauncher-Setup.exe --silent-uninstall [--remove-data]
    NexiLauncher-Setup.exe --cleanup PATH      (internal, used by uninstall)
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import winreg
from ctypes import wintypes
from pathlib import Path

APP_NAME = "Nexi Launcher"
VERSION = "1.8.0"
EXE_NAME = "Nexi-Portable.exe"
UNINSTALLER_NAME = "Uninstall.exe"
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\NexiLauncher")
# nexi://link?token=... is opened by the site when an account is linked.
PROTOCOL_KEY = r"Software\Classes\nexi"
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

# CSIDL values for SHGetFolderPathW; the shell resolves the real per-user
# folders, including a desktop redirected into OneDrive.
CSIDL_PROGRAMS = 0x0002
CSIDL_DESKTOPDIRECTORY = 0x0010


class InstallerError(Exception):
    """A problem the installer can show to the user."""


class AppRunning(InstallerError):
    """Nexi-Portable.exe is running and the installed copy could not be replaced."""


# --------------------------------------------------------------------- logging

def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        with open(Path(tempfile.gettempdir()) / "nexi-setup.log", "a",
                  encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


# ------------------------------------------------------------------ path utils

def _bundle_dir() -> Path:
    """Directory with the files bundled by PyInstaller (or the script dir)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _payload_path() -> Path:
    for candidate in (_bundle_dir() / EXE_NAME,
                      _project_root() / EXE_NAME,
                      _project_root() / "_dist" / EXE_NAME):
        if candidate.is_file():
            return candidate
    raise InstallerError("Nexi-Portable.exe is missing from the setup bundle.")


def _asset_path(name: str) -> Path | None:
    for candidate in (_bundle_dir() / name,
                      _project_root() / "assets" / name,
                      _project_root() / "webui" / name):
        if candidate.is_file():
            return candidate
    return None


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([str(child.resolve()),
                                   str(parent.resolve())]) == str(
            parent.resolve())
    except (OSError, ValueError):
        return False


def _known_folder(csidl: int) -> Path:
    buffer = ctypes.create_unicode_buffer(260)
    result = ctypes.windll.shell32.SHGetFolderPathW(
        None, csidl, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise InstallerError(f"Cannot resolve shell folder 0x{csidl:04x}.")
    return Path(buffer.value)


def desktop_shortcut() -> Path:
    return _known_folder(CSIDL_DESKTOPDIRECTORY) / f"{APP_NAME}.lnk"


def start_menu_shortcut() -> Path:
    return _known_folder(CSIDL_PROGRAMS) / f"{APP_NAME}.lnk"


def default_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "Programs" / APP_NAME


def app_data_dir() -> Path:
    roaming = os.environ.get("APPDATA")
    base = Path(roaming) if roaming else Path.home() / "AppData" / "Roaming"
    return base / "NexiLauncher"


def registered_dir() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            value = winreg.QueryValueEx(key, "InstallLocation")[0]
            return str(value)
    except OSError:
        return ""


def registered_version() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            value = winreg.QueryValueEx(key, "DisplayVersion")[0]
            return str(value)
    except OSError:
        return ""


def _version_tuple(value: str) -> tuple:
    match = re.match(r"^\s*[vV]?(\d+(?:\.\d+)*)", str(value or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _can_update(installed_version: str) -> bool:
    """True when this setup is newer than the registered installation."""
    current = _version_tuple(VERSION)
    installed = _version_tuple(installed_version)
    if not installed:
        return True
    width = max(len(current), len(installed))
    current += (0,) * (width - len(current))
    installed += (0,) * (width - len(installed))
    return current > installed


def _guess_install_dir() -> str:
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).parent
        if (parent / EXE_NAME).is_file():
            return str(parent)
    return ""


def _is_installed(target: Path) -> bool:
    return bool(registered_dir()) or (target / EXE_NAME).is_file()


# --------------------------------------------------------------- registry part

def write_registry(target: Path) -> None:
    size_kb = sum(item.stat().st_size for item in target.iterdir()
                  if item.is_file()) // 1024
    uninstaller = target / UNINSTALLER_NAME
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                            winreg.KEY_WRITE) as key:
        values = (
            ("DisplayName", winreg.REG_SZ, APP_NAME),
            ("DisplayVersion", winreg.REG_SZ, VERSION),
            ("Publisher", winreg.REG_SZ, APP_NAME),
            ("InstallLocation", winreg.REG_SZ, str(target)),
            ("DisplayIcon", winreg.REG_SZ, str(target / EXE_NAME)),
            ("UninstallString", winreg.REG_SZ,
             f'"{uninstaller}" --uninstall'),
            ("QuietUninstallString", winreg.REG_SZ,
             f'"{uninstaller}" --silent-uninstall'),
            ("InstallDate", winreg.REG_SZ, time.strftime("%Y%m%d")),
            ("NoModify", winreg.REG_DWORD, 1),
            ("NoRepair", winreg.REG_DWORD, 1),
            ("EstimatedSize", winreg.REG_DWORD, size_kb),
        )
        for name, kind, value in values:
            winreg.SetValueEx(key, name, 0, kind, value)

    # The site opens nexi://link?token=... to hand a link request to the app.
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PROTOCOL_KEY, 0,
                                winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ,
                              "URL:Nexi Launcher protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKeyEx(key, r"shell\open\command", 0,
                                    winreg.KEY_WRITE) as command:
                winreg.SetValueEx(command, "", 0, winreg.REG_SZ,
                                  f'"{target / EXE_NAME}" "%1"')
    except OSError as exc:
        log(f"could not register the nexi:// protocol: {exc}")


def remove_registry() -> None:
    keys = (PROTOCOL_KEY + r"\shell\open\command",
            PROTOCOL_KEY + r"\shell\open",
            PROTOCOL_KEY + r"\shell",
            PROTOCOL_KEY,
            UNINSTALL_KEY)
    for path in keys:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log(f"could not remove registry key {path}: {exc}")


# -------------------------------------------------------------------- shortcuts

# Shortcuts are created through the shell's IShellLink COM object. The old
# implementation shelled out to PowerShell with a hidden window, which made
# the setup exe look suspicious to antivirus heuristics for no benefit.

_CLSCTX_INPROC_SERVER = 1
_CLSID_SHELLLINK = "00021401-0000-0000-C000-000000000046"
_IID_ISHELLLINKW = "000214F9-0000-0000-C000-000000000046"
_IID_IPERSISTFILE = "0000010B-0000-0000-C000-000000000046"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        value = uuid.UUID(text)
        guid = cls()
        guid.Data1 = value.time_low
        guid.Data2 = value.time_mid
        guid.Data3 = value.time_hi_version
        for index, byte in enumerate(value.bytes[8:]):
            guid.Data4[index] = byte
        return guid


def _com_call(interface, index: int, *argtypes):
    """Bind one vtable slot of a COM interface to a callable."""
    table = ctypes.cast(
        interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    address = ctypes.cast(table[index], ctypes.c_void_p).value
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   *argtypes)
    return prototype(address)


def _com_release(interface) -> None:
    try:
        _com_call(interface, 2)(interface)  # IUnknown::Release
    except (OSError, ValueError):
        pass


def _write_shortcut(link: Path, target: Path) -> None:
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long

    initialised = ole32.CoInitializeEx(None, 2) in (0, 1)
    shell_link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    try:
        clsid = _GUID.parse(_CLSID_SHELLLINK)
        iid = _GUID.parse(_IID_ISHELLLINKW)
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None,
                                    _CLSCTX_INPROC_SERVER,
                                    ctypes.byref(iid),
                                    ctypes.byref(shell_link))
        if hr < 0 or not shell_link:
            raise InstallerError(
                "Could not create the shortcut (COM error "
                f"0x{hr & 0xFFFFFFFF:08x}).")

        target_text = str(target)
        link_text = str(link)

        def set_string(index, value):
            result = _com_call(shell_link, index, wintypes.LPCWSTR)(
                shell_link, value)
            if result < 0:
                raise InstallerError(
                    f"Could not fill in the shortcut (0x{result & 0xFFFFFFFF:08x}).")

        set_string(20, target_text)                    # IShellLinkW::SetPath
        set_string(9, str(target.parent))              # SetWorkingDirectory
        set_string(7, APP_NAME)                        # SetDescription
        icon_result = _com_call(
            shell_link, 17, wintypes.LPCWSTR, ctypes.c_int)(
            shell_link, target_text, 0)                # SetIconLocation
        if icon_result < 0:
            raise InstallerError(
                f"Could not set the shortcut icon "
                f"(0x{icon_result & 0xFFFFFFFF:08x}).")

        iid_persist = _GUID.parse(_IID_IPERSISTFILE)
        hr = _com_call(shell_link, 0, ctypes.POINTER(_GUID),
                       ctypes.POINTER(ctypes.c_void_p))(
            shell_link, ctypes.byref(iid_persist), ctypes.byref(persist))
        if hr < 0 or not persist:
            raise InstallerError(
                f"Could not save the shortcut (0x{hr & 0xFFFFFFFF:08x}).")
        hr = _com_call(persist, 6, wintypes.LPCWSTR, wintypes.BOOL)(
            persist, link_text, True)                  # IPersistFile::Save
        if hr < 0:
            raise InstallerError(
                f"Could not save the shortcut (0x{hr & 0xFFFFFFFF:08x}).")
    finally:
        if persist:
            _com_release(persist)
        if shell_link:
            _com_release(shell_link)
        if initialised:
            ole32.CoUninitialize()


def create_shortcut(link: Path, target: Path) -> None:
    try:
        _write_shortcut(Path(link), Path(target))
    except OSError as exc:
        raise InstallerError(
            f"Could not create the shortcut {Path(link).name}: {exc}") from exc


# ------------------------------------------------------------------- processes

def launcher_running(target: Path) -> bool:
    exe = Path(target) / EXE_NAME
    if not exe.is_file():
        return False
    try:
        with open(exe, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def kill_launcher() -> None:
    subprocess.run(["taskkill", "/IM", EXE_NAME, "/F"],
                   creationflags=CREATE_NO_WINDOW, capture_output=True)


def _spawn_launcher(target: Path) -> None:
    subprocess.Popen([str(Path(target) / EXE_NAME)], cwd=str(target),
                     creationflags=DETACHED_PROCESS, close_fds=True)


def _rmtree_retry(path: Path, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while path.exists():
        try:
            shutil.rmtree(path)
        except OSError:
            if time.time() >= deadline:
                return False
            time.sleep(0.4)
    return True


# -------------------------------------------------------------------- install

def _uninstaller_source() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    candidate = _project_root() / "NexiLauncher-Setup.exe"
    if candidate.is_file():
        return candidate
    raise InstallerError(
        "Building the uninstaller needs NexiLauncher-Setup.exe; run "
        "build_installer.ps1.")


def install(target: Path, desktop: bool, launch: bool,
            progress=None, force_kill: bool = False):
    """Copy the launcher into *target*, then create shortcuts and registry.

    Returns a list of non-fatal warnings. Raises AppRunning if the installed
    launcher is running and ``force_kill`` is false.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    payload = _payload_path()

    _progress(progress, 8)
    destination = target / EXE_NAME
    try:
        shutil.copy2(payload, destination)
    except PermissionError:
        if not force_kill:
            raise AppRunning(str(target)) from None
        log("launcher is running; closing it before the copy")
        kill_launcher()
        time.sleep(0.8)
        shutil.copy2(payload, destination)

    _progress(progress, 45)
    shutil.copy2(_uninstaller_source(), target / UNINSTALLER_NAME)

    warnings: list[str] = []
    _progress(progress, 70)
    if desktop:
        try:
            create_shortcut(desktop_shortcut(), destination)
        except InstallerError as exc:
            warnings.append(str(exc))
            log(str(exc))
    try:
        create_shortcut(start_menu_shortcut(), destination)
    except InstallerError as exc:
        warnings.append(str(exc))
        log(str(exc))

    _progress(progress, 88)
    write_registry(target)

    _progress(progress, 100)
    log(f"installed {destination}")
    if launch:
        _spawn_launcher(target)
    return warnings


def _progress(progress, percent: int) -> None:
    if progress is not None:
        progress(percent)


# ------------------------------------------------------------------ uninstall

def remove_installation(target: Path, remove_data: bool, progress=None,
                        kill_first: bool = False) -> bool:
    """Remove shortcuts, the registry entry and the installed files.

    Returns True when the installation directory is removed by a detached
    cleanup copy (because this executable lives inside it); the caller must
    exit immediately in that case.
    """
    target = Path(target)
    if kill_first:
        kill_launcher()
        time.sleep(0.6)

    _progress(progress, 10)
    for link in (desktop_shortcut(), start_menu_shortcut()):
        try:
            link.unlink(missing_ok=True)
        except OSError as exc:
            log(f"could not remove shortcut {link}: {exc}")

    remove_registry()
    _progress(progress, 35)

    if remove_data:
        data = app_data_dir()
        log(f"removing user data at {data}")
        if data.exists() and not _rmtree_retry(data, timeout=20):
            raise InstallerError(f"Could not delete {data}.")

    _progress(progress, 65)
    relaunched = _finalize_removal(target)
    _progress(progress, 100)
    log(f"uninstalled from {target}")
    return relaunched


def _finalize_removal(target: Path) -> bool:
    if not target.exists():
        return False
    if getattr(sys, "frozen", False) and _is_within(Path(sys.executable),
                                                    target):
        # Uninstall.exe cannot delete itself: hand the folder to a copy in
        # %TEMP% and let it clean up once this process has exited.
        temporary = Path(tempfile.gettempdir()) / (
            f"NexiUninstall-{os.getpid()}.exe")
        shutil.copy2(sys.executable, temporary)
        subprocess.Popen([str(temporary), "--cleanup", str(target)],
                         creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                         close_fds=True)
        return True
    if not _rmtree_retry(target, timeout=25):
        raise InstallerError(f"Could not delete {target}.")
    return False


def _schedule_self_delete() -> None:
    """Delete this (running) executable once Windows releases its image.

    A one-file PyInstaller exe is locked by its bootloader parent for a moment
    after the child exits, so a single ``del`` can arrive too early. A tiny
    retrying batch file is used instead.
    """
    executable = Path(sys.executable)
    batch = Path(tempfile.gettempdir()) / f"NexiCleanup-{os.getpid()}.cmd"
    script = (
        "@echo off\r\n"
        "set tries=0\r\n"
        ":loop\r\n"
        f'del /f /q "{executable}" >nul 2>&1\r\n'
        f'if not exist "{executable}" goto done\r\n'
        "set /a tries+=1\r\n"
        "if %tries% geq 120 goto done\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto loop\r\n"
        ":done\r\n"
        "(goto) 2>nul & del /f /q \"%~f0\"\r\n"
    )
    try:
        batch.write_text(script, encoding="utf-8")
        subprocess.Popen(["cmd.exe", "/c", str(batch)],
                         creationflags=CREATE_NO_WINDOW, close_fds=True)
    except OSError:
        pass


def cleanup_main(target: str) -> int:
    """Internal: wait for the uninstaller to exit, then delete the folder."""
    try:
        folder = _validate_dir(target)
    except InstallerError as exc:
        # --cleanup is invoked with a path; never let a wrong one wipe an
        # arbitrary directory.
        log(f"cleanup: refusing {target!r}: {exc}")
        _schedule_self_delete()
        return 1
    if folder.exists() and not ((folder / UNINSTALLER_NAME).is_file()
                                or (folder / EXE_NAME).is_file()):
        log(f"cleanup: {folder} does not look like a Nexi installation")
        _schedule_self_delete()
        return 1
    deadline = time.time() + 40
    while folder.exists() and time.time() < deadline:
        try:
            shutil.rmtree(folder)
        except OSError:
            time.sleep(0.5)
    _schedule_self_delete()
    return 0


# ------------------------------------------------------------------ CLI helpers

def _arg_value(args: list[str], flag: str) -> str:
    for index, item in enumerate(args):
        if item == flag and index + 1 < len(args):
            return args[index + 1]
        if item.startswith(flag + "="):
            return item[len(flag) + 1:]
    return ""


def _validate_dir(raw: str) -> Path:
    text = str(raw or "").strip().strip('"')
    if not text:
        raise InstallerError("empty")
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    if path.parent == path:
        raise InstallerError("drive root")
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    if _is_within(path, windows):
        raise InstallerError("windows folder")
    if path.exists() and not path.is_dir():
        raise InstallerError("not a folder")
    return path


# ------------------------------------------------------------------ WebView2

def webview2_installed() -> bool:
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    for root in roots:
        for view in views:
            try:
                with winreg.OpenKey(
                        root,
                        r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
                        "\\" + WEBVIEW2_GUID,
                        0, winreg.KEY_READ | view) as key:
                    version = winreg.QueryValueEx(key, "pv")[0]
                    if version and version != "0.0.0.0":
                        return True
            except OSError:
                continue
    return False


WEBVIEW2_SETUP_NAME = "NexiWebView2Setup.exe"


def download_webview2(progress=None) -> Path:
    """Download Microsoft's tiny Evergreen bootstrapper into %TEMP%."""
    import urllib.request

    target = Path(tempfile.gettempdir()) / WEBVIEW2_SETUP_NAME
    request = urllib.request.Request(
        WEBVIEW2_URL, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
    with urllib.request.urlopen(request, timeout=90) as response:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        with open(target, "wb") as handle:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, total)
    with open(target, "rb") as handle:
        signature = handle.read(2)
    if signature != b"MZ":
        target.unlink(missing_ok=True)
        raise InstallerError("The WebView2 download is not an executable.")
    log(f"downloaded the WebView2 bootstrapper "
        f"({target.stat().st_size} bytes)")
    return target


def run_webview2_installer(bootstrapper: Path) -> int:
    """Run the bootstrapper silently; without elevation it installs per user."""
    result = subprocess.run([str(bootstrapper), "/silent", "/install"],
                            timeout=900)
    log(f"WebView2 bootstrapper exited with {result.returncode}")
    return result.returncode


def wait_for_webview2(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if webview2_installed():
            return True
        time.sleep(0.6)
    return False


# ----------------------------------------------------------------------- texts

TEXTS = {
    "ru": {
        "setup_title": "Установка Nexi Launcher",
        "uninstall_title": "Удаление Nexi Launcher",
        "subtitle_setup": "Установка лаунчера Minecraft",
        "subtitle_uninstall": "Удаление с этого компьютера",
        "folder": "ПАПКА УСТАНОВКИ",
        "browse": "Обзор…",
        "desktop": "Создать ярлык на рабочем столе",
        "launch": "Запустить Nexi Launcher после установки",
        "install": "Установить",
        "cancel": "Отмена",
        "installing": "Установка…",
        "step_copy": "Копирование файлов…",
        "step_shortcuts": "Создание ярлыков…",
        "step_registry": "Регистрация в Windows…",
        "done_title": "Установка завершена",
        "done_text": "Nexi Launcher установлен в\n{path}",
        "done_warn": "Замечания:\n{warnings}",
        "run": "Запустить",
        "close": "Закрыть",
        "warn_webview": "Не найден Microsoft Edge WebView2 Runtime. "
                        "Без него интерфейс лаунчера не запустится.",
        "webview_link": "Скачать WebView2",
        "running_title": "Nexi Launcher запущен",
        "running_text": "Чтобы продолжить, лаунчер нужно закрыть. "
                        "Закрыть его сейчас?",
        "error_title": "Ошибка",
        "bad_dir": "Выберите другую папку установки.",
        "uninstall_where": "Лаунчер установлен в\n{path}",
        "remove_data": "Также удалить аккаунты, настройки и сборки",
        "remove_data_hint": "Будут безвозвратно удалены аккаунты и токены, "
                            "настройки, журналы и все сборки в "
                            "%APPDATA%\\NexiLauncher.",
        "uninstall_button": "Удалить",
        "uninstalling": "Удаление…",
        "uninstall_done": "Nexi Launcher удалён.",
        "not_installed": "Nexi Launcher не установлен на этом компьютере.",
        "cleanup_failed": "Не удалось полностью удалить файлы. "
                          "Удалите папку вручную:\n{path}",
        "keep_data_note": "Аккаунты, настройки и сборки сохранены.",
        "webview_title": "Nexi Launcher — WebView2",
        "webview_heading": "Нужен Microsoft Edge WebView2",
        "webview_text": "Установщик Nexi Launcher рисует интерфейс через "
                        "WebView2 — компонент Microsoft. Сейчас он скачается "
                        "и установится автоматически.",
        "webview_downloading": "Скачивание установщика WebView2…",
        "webview_installing": "Установка WebView2… Это может занять "
                              "несколько минут.",
        "webview_ready": "Готово. Запускаем установщик Nexi Launcher…",
        "webview_failed": "Не удалось установить WebView2.",
        "webview_manual": "Скачать вручную",
        "webview_retry": "Повторить",
        "webview_close": "Закрыть",
        "webview_note": "Если автоматическая установка не удалась, скачайте "
                        "WebView2 со страницы Microsoft и запустите установщик "
                        "снова.",
        "webview_download_hint": "Небольшой загрузчик, около 2 МБ.",
    },
    "en": {
        "setup_title": "Nexi Launcher Setup",
        "uninstall_title": "Uninstall Nexi Launcher",
        "subtitle_setup": "Minecraft launcher setup",
        "subtitle_uninstall": "Remove it from this computer",
        "folder": "INSTALL FOLDER",
        "browse": "Browse…",
        "desktop": "Create a desktop shortcut",
        "launch": "Start Nexi Launcher after installing",
        "install": "Install",
        "cancel": "Cancel",
        "installing": "Installing…",
        "step_copy": "Copying files…",
        "step_shortcuts": "Creating shortcuts…",
        "step_registry": "Registering with Windows…",
        "done_title": "Installation complete",
        "done_text": "Nexi Launcher is installed in\n{path}",
        "done_warn": "Notes:\n{warnings}",
        "run": "Start",
        "close": "Close",
        "warn_webview": "Microsoft Edge WebView2 Runtime was not found. "
                        "The launcher interface needs it.",
        "webview_link": "Download WebView2",
        "running_title": "Nexi Launcher is running",
        "running_text": "It has to be closed to continue. Close it now?",
        "error_title": "Error",
        "bad_dir": "Choose another install folder.",
        "uninstall_where": "The launcher is installed in\n{path}",
        "remove_data": "Also delete accounts, settings and builds",
        "remove_data_hint": "Accounts and tokens, settings, logs and every "
                            "build in %APPDATA%\\NexiLauncher will be deleted "
                            "permanently.",
        "uninstall_button": "Uninstall",
        "uninstalling": "Uninstalling…",
        "uninstall_done": "Nexi Launcher has been removed.",
        "not_installed": "Nexi Launcher is not installed on this computer.",
        "cleanup_failed": "Some files could not be removed. Delete the "
                          "folder manually:\n{path}",
        "keep_data_note": "Accounts, settings and builds were kept.",
        "webview_title": "Nexi Launcher — WebView2",
        "webview_heading": "Microsoft Edge WebView2 is required",
        "webview_text": "The Nexi Launcher setup draws its interface with "
                        "WebView2, a Microsoft component. It will be "
                        "downloaded and installed automatically.",
        "webview_downloading": "Downloading the WebView2 installer…",
        "webview_installing": "Installing WebView2… This can take a few "
                              "minutes.",
        "webview_ready": "Done. Starting the Nexi Launcher setup…",
        "webview_failed": "WebView2 could not be installed.",
        "webview_manual": "Download manually",
        "webview_retry": "Try again",
        "webview_close": "Close",
        "webview_note": "If the automatic installation failed, download "
                        "WebView2 from Microsoft and run the setup again.",
        "webview_download_hint": "A small bootstrapper, about 2 MB.",
    },
}


def ui_language() -> str:
    try:
        language = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (language & 0x3FF) == 0x19:  # LANG_RUSSIAN
            return "ru"
    except Exception:
        pass
    return "en"


# -------------------------------------------------------------- web GUI bridge

class SetupApi:
    """Methods exposed to the installer page as window.pywebview.api."""

    def __init__(self, mode: str, language: str):
        self.mode = mode
        self.language = language
        # Private on purpose: pywebview walks every public attribute of the
        # js_api object to build the JS bridge and recurses into anything that
        # has a __module__. A Window here would drag it through the whole
        # WinForms/WebView2 object graph, which takes minutes in a frozen
        # build and leaves the page without its API ("Нет связи с установщиком").
        self._window = None
        self.busy = False
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._target = ""

    # ----------------------------------------------------------- plumbing

    def _push(self, event: dict) -> None:
        with self._lock:
            self._events.append(event)

    def poll(self) -> dict:
        with self._lock:
            events = self._events
            self._events = []
        return {"events": events, "busy": self.busy}

    def state(self) -> dict:
        if self.mode == "install":
            target = registered_dir() or str(default_dir())
        else:
            target = (registered_dir() or _guess_install_dir()
                      or str(default_dir()))
        self._target = target
        installed = _is_installed(Path(target))
        installed_version = registered_version()
        return {
            "mode": self.mode,
            "language": self.language,
            "version": VERSION,
            "path": target,
            "installed": installed,
            "installed_version": installed_version,
            "can_update": bool(installed
                               and _can_update(installed_version)),
            "webview2": webview2_installed(),
            "data_path": str(app_data_dir()),
        }

    # ------------------------------------------------------------ window

    def minimize(self) -> dict:
        if self._window is not None:
            try:
                self._window.minimize()
            except Exception:
                log(traceback.format_exc())
        return {"ok": True}

    def close_window(self) -> dict:
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                log(traceback.format_exc())
        return {"ok": True}

    def set_title(self, title: str = "") -> dict:
        """Keep the native window title in sync with the page language."""
        try:
            if self._window is not None and title:
                self._window.set_title(str(title)[:120])
        except Exception:
            log(traceback.format_exc())
        return {"ok": True}

    def open_webview2(self) -> dict:
        try:
            os.startfile(WEBVIEW2_URL)
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def pick_folder(self, current: str = "") -> dict:
        if self._window is None:
            return {"path": ""}
        import webview

        directory = str(current or "").strip() or str(default_dir())
        try:
            folder = Path(directory)
            if not folder.is_dir():
                directory = str(folder.parent)
        except OSError:
            directory = str(default_dir())
        try:
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG, directory=directory)
        except Exception:
            log(traceback.format_exc())
            return {"path": ""}
        if not result:
            return {"path": ""}
        selected = result[0] if isinstance(result, (list, tuple)) else result
        return {"path": str(selected)}

    def launch(self, path: str = "") -> dict:
        target = Path(path or self._target or default_dir())
        try:
            _spawn_launcher(target)
            return {"ok": True}
        except OSError as exc:
            log(traceback.format_exc())
            return {"ok": False, "error": str(exc)}

    # ----------------------------------------------------------- install

    def start_install(self, path: str, desktop: bool, launch: bool,
                      force: bool = False) -> dict:
        if self.busy:
            return {"ok": False, "error": "busy"}
        try:
            target = _validate_dir(str(path or ""))
        except InstallerError:
            return {"ok": False, "error": "invalid_dir"}
        self.busy = True
        threading.Thread(
            target=self._install_worker,
            args=(target, bool(desktop), bool(launch), bool(force)),
            daemon=True).start()
        return {"ok": True}

    def _install_worker(self, target: Path, desktop: bool, launch_after: bool,
                        force: bool) -> None:
        try:
            try:
                warnings = install(target, desktop, False,
                                   progress=self._progress,
                                   force_kill=force)
            except AppRunning:
                self.busy = False
                self._push({"t": "running"})
                return
            launched = False
            if launch_after:
                try:
                    _spawn_launcher(target)
                    launched = True
                except OSError as exc:
                    warnings.append(str(exc))
            self._target = str(target)
            self.busy = False
            self._push({"t": "done", "ok": True, "path": str(target),
                        "warnings": warnings, "launched": launched})
        except Exception as exc:
            log(traceback.format_exc())
            self.busy = False
            self._push({"t": "error", "error": str(exc)})

    # --------------------------------------------------------- uninstall

    def start_uninstall(self, remove_data: bool = False,
                        force: bool = False) -> dict:
        if self.busy:
            return {"ok": False, "error": "busy"}
        target = Path(self._target or registered_dir() or _guess_install_dir()
                      or default_dir())
        if not _is_installed(target):
            return {"ok": False, "error": "not_installed"}
        self.busy = True
        threading.Thread(
            target=self._uninstall_worker,
            args=(target, bool(remove_data), bool(force)),
            daemon=True).start()
        return {"ok": True}

    def _uninstall_worker(self, target: Path, remove_data: bool,
                          force: bool) -> None:
        try:
            if not force and launcher_running(target):
                self.busy = False
                self._push({"t": "running"})
                return
            relaunched = remove_installation(
                target, remove_data, progress=self._progress,
                kill_first=force)
            self.busy = False
            self._push({"t": "done", "ok": True, "path": str(target),
                        "kept_data": not remove_data,
                        "relaunched": relaunched})
        except Exception as exc:
            log(traceback.format_exc())
            self.busy = False
            self._push({"t": "error", "error": str(exc)})

    def _progress(self, percent: int) -> None:
        self._push({"t": "progress", "value": int(percent)})


def _web_page() -> Path:
    for candidate in (_bundle_dir() / "web" / "index.html",
                      Path(__file__).resolve().parent / "web" / "index.html"):
        if candidate.is_file():
            return candidate
    raise InstallerError("The installer page is missing from the bundle.")


WEB_WIDTH = 720
WEB_HEIGHT = 600


class WebSetup:
    """Frameless pywebview window that renders ``installer/web/index.html``."""

    def __init__(self, mode: str, language: str):
        self.mode = mode
        self.language = language
        self.window = None
        self.api = SetupApi(mode, language)

    def _on_closing(self) -> bool:
        # Never let the window disappear while files are being written.
        return not self.api.busy

    def show(self, driver=None) -> None:
        import webview

        # In a windowed build stderr is gone, so pywebview's bridge errors
        # would disappear into the void; keep them next to the setup log.
        try:
            handler = logging.FileHandler(
                Path(tempfile.gettempdir()) / "nexi-setup-pywebview.log",
                encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "[pywebview] %(levelname)s %(message)s"))
            logging.getLogger("pywebview").addHandler(handler)
        except Exception:
            pass

        page = _web_page()
        title = (TEXTS[self.language]["setup_title"]
                 if self.mode == "install"
                 else TEXTS[self.language]["uninstall_title"])
        url = page.as_uri() + f"#lang={self.language}&mode={self.mode}"
        self.window = webview.create_window(
            title,
            url,
            js_api=self.api,
            width=WEB_WIDTH,
            height=WEB_HEIGHT,
            resizable=False,
            background_color="#0a0a0a",
            frameless=True,
            easy_drag=False,
        )
        self.api._window = self.window
        self.window.events.closing += self._on_closing

        webview.start(driver, gui="edgechromium",
                      debug=bool(os.environ.get("NEXI_SETUP_DEBUG")))


# --------------------------------------------------------------------------- GUI

BG = "#0a0a0a"
PANEL = "#111318"
FIELD = "#0e1015"
BORDER = "#24282f"
TEXT = "#f2f3f5"
DIM = "#9a9a9a"
FAINT = "#666666"
ACCENT = "#6ee7b7"
ACCENT_HOVER = "#93eecb"
ACCENT_FG = "#0a0a0a"
GHOST_BG = "#171a20"
GHOST_HOVER = "#1f232b"
WARN = "#f0b35b"
DANGER_STRONG = "#c9434a"
DANGER_STRONG_HOVER = "#dc5259"

FONT = "Segoe UI"


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class SetupWindow:
    def __init__(self, mode: str, language: str):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.mode = mode
        self.text = TEXTS[language]
        self.phase = "form"

        self.root = tk.Tk()
        self.root.title(self.text["setup_title"] if mode == "install"
                        else self.text["uninstall_title"])
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        try:
            scale = float(self.root.tk.call("tk", "scaling"))
        except Exception:
            scale = 1.3333
        self.ui = max(1.0, scale / 1.3333)
        self.wrap = int(560 * self.ui)

        icon = _asset_path("nexi.ico")
        if icon is not None:
            try:
                self.root.iconbitmap(default=str(icon))
            except Exception:
                pass

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Nexi.Horizontal.TProgressbar",
                        troughcolor="#1a1d23", background=ACCENT,
                        bordercolor="#1a1d23", lightcolor=ACCENT,
                        darkcolor=ACCENT, thickness=int(8 * self.ui))

        self._build_shell()

    # ---------------------------------------------------------- widget helpers

    def _button(self, parent, text, command, kind="ghost", width=None):
        colors = {
            "primary": (ACCENT, ACCENT_HOVER, ACCENT_FG),
            "danger": (DANGER_STRONG, DANGER_STRONG_HOVER, "#ffffff"),
            "ghost": (GHOST_BG, GHOST_HOVER, TEXT),
        }
        background, hover, foreground = colors[kind]
        button = self.tk.Button(
            parent, text=text, command=command, bg=background, fg=foreground,
            activebackground=hover, activeforeground=foreground,
            disabledforeground=DIM, relief="flat", bd=0,
            padx=int(18 * self.ui), pady=int(8 * self.ui),
            font=(FONT, 10), cursor="hand2")
        if width:
            button.configure(width=width)
        button.bind("<Enter>", lambda _e: button.configure(bg=hover)
                    if str(button["state"]) != "disabled" else None)
        button.bind("<Leave>", lambda _e: button.configure(bg=background)
                    if str(button["state"]) != "disabled" else None)
        return button

    def _checkbutton(self, parent, text, variable):
        """A themed checkbox: Tk's native indicator ignores dark colours."""
        tk = self.tk
        row = tk.Frame(parent, bg=BG, cursor="hand2")
        box = tk.Label(row, text="", width=2, bg=FIELD, fg=ACCENT_FG,
                       font=(FONT, 9, "bold"), padx=1, pady=1,
                       highlightthickness=1, highlightbackground=BORDER,
                       bd=0)
        box.pack(side="left")
        label = tk.Label(row, text=text, bg=BG, fg=TEXT, font=(FONT, 10))
        label.pack(side="left", padx=(9, 0))

        def refresh(*_args):
            on = bool(variable.get())
            box.configure(text="✓" if on else "",
                          bg=ACCENT if on else FIELD,
                          fg=ACCENT_FG if on else DIM,
                          highlightbackground=ACCENT if on else BORDER)

        variable.trace_add("write", refresh)

        def toggle(_event=None):
            variable.set(not variable.get())

        for widget in (row, box, label):
            widget.bind("<Button-1>", toggle)
        refresh()
        return row

    def _label(self, parent, text, size=10, color=TEXT, weight="normal",
               wrap=True, anchor="w"):
        return self.tk.Label(
            parent, text=text, bg=BG, fg=color, font=(FONT, size, weight),
            anchor=anchor, justify="left",
            wraplength=self.wrap if wrap else 0)

    # ----------------------------------------------------------------- layout

    def _build_shell(self):
        tk = self.tk
        outer = tk.Frame(self.root, bg=BG, padx=28, pady=24)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        icon_file = _asset_path("star_icon_rounded.png")
        if icon_file is not None:
            try:
                self.icon_image = tk.PhotoImage(file=str(icon_file))
                factor = max(1, self.icon_image.width() // 48)
                if factor > 1:
                    self.icon_image = self.icon_image.subsample(factor, factor)
                tk.Label(header, image=self.icon_image, bg=BG).pack(
                    side="left", padx=(0, 14))
            except Exception:
                self.icon_image = None
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", anchor="w")
        tk.Label(titles, text="NEXI LAUNCHER", bg=BG, fg=TEXT,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(titles,
                 text=self.text["subtitle_setup"] if self.mode == "install"
                 else self.text["subtitle_uninstall"],
                 bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", pady=(2, 0))

        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(18, 16))

        self.content = tk.Frame(outer, bg=BG)
        self.content.pack(fill="both", expand=True)

        if self.mode == "install":
            self._build_install_form()
        else:
            self._build_uninstall_form()

        self.root.update_idletasks()
        width = max(self.root.winfo_reqwidth(), int(600 * self.ui))
        height = self.root.winfo_reqheight()
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2 - 30)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _clear_content(self):
        for child in self.content.winfo_children():
            child.destroy()

    # -------------------------------------------------------- install screen

    def _build_install_form(self):
        tk = self.tk
        start = registered_dir() or str(default_dir())
        self.target_var = tk.StringVar(value=start)
        self.desktop_var = tk.BooleanVar(value=True)
        self.launch_var = tk.BooleanVar(value=True)

        self._label(self.content, self.text["folder"], size=8,
                    color=DIM).pack(anchor="w")
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(6, 14))
        entry_wrap = tk.Frame(row, bg=BORDER, padx=1, pady=1)
        entry_wrap.pack(side="left", fill="x", expand=True)
        self.entry = tk.Entry(
            entry_wrap, textvariable=self.target_var, bg=FIELD, fg=TEXT,
            insertbackground=TEXT, relief="flat", bd=0,
            highlightthickness=0, font=(FONT, 10))
        self.entry.pack(fill="x", padx=10, ipady=int(7 * self.ui))
        self.browse_button = self._button(row, self.text["browse"],
                                          self._browse)
        self.browse_button.pack(side="left", padx=(10, 0))

        if not webview2_installed():
            warning = tk.Frame(self.content, bg="#1d1709", padx=12, pady=9)
            warning.pack(fill="x", pady=(0, 12))
            tk.Label(warning, text=self.text["warn_webview"], bg="#1d1709",
                     fg=WARN, font=(FONT, 9), anchor="w", justify="left",
                     wraplength=self.wrap).pack(side="left", fill="x",
                                                expand=True)
            link = tk.Label(warning, text=self.text["webview_link"],
                            bg="#1d1709", fg=ACCENT, font=(FONT, 9, "underline"),
                            cursor="hand2")
            link.pack(side="right", padx=(10, 0))
            link.bind("<Button-1>", lambda _e: self._open_webview())

        self._checkbutton(self.content, self.text["desktop"],
                          self.desktop_var).pack(anchor="w")
        self._checkbutton(self.content, self.text["launch"],
                          self.launch_var).pack(anchor="w", pady=(2, 14))

        self.progress = self.ttk.Progressbar(
            self.content, style="Nexi.Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self.status = self._label(self.content, "", size=9, color=DIM,
                                  wrap=True)
        self.status.pack(anchor="w", pady=(0, 4))
        self.progress.pack(fill="x", pady=(0, 14))

        buttons = tk.Frame(self.content, bg=BG)
        buttons.pack(fill="x", pady=(4, 0))
        self.install_button = self._button(
            buttons, self.text["install"], self._start_install,
            kind="primary")
        self.install_button.pack(side="right")
        self.cancel_button = self._button(
            buttons, self.text["cancel"], self.root.destroy)
        self.cancel_button.pack(side="right", padx=(0, 10))

    def _browse(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(
            parent=self.root, initialdir=self.target_var.get() or str(
                default_dir()), title=self.text["folder"].title())
        if folder:
            self.target_var.set(folder)

    def _open_webview(self):
        try:
            os.startfile(WEBVIEW2_URL)
        except OSError:
            pass

    def _start_install(self):
        from tkinter import messagebox
        try:
            target = _validate_dir(self.target_var.get())
        except InstallerError:
            messagebox.showerror(self.text["error_title"],
                                 self.text["bad_dir"], parent=self.root)
            return

        self._set_busy(True)
        try:
            try:
                warnings = install(target, self.desktop_var.get(), False,
                                   progress=self._progress)
            except AppRunning:
                self._set_busy(False)
                if not messagebox.askyesno(
                        self.text["running_title"],
                        self.text["running_text"], parent=self.root):
                    return
                self._set_busy(True)
                warnings = install(target, self.desktop_var.get(), False,
                                   progress=self._progress, force_kill=True)
        except Exception as exc:
            log(traceback.format_exc())
            self._set_busy(False)
            messagebox.showerror(self.text["error_title"], str(exc),
                                 parent=self.root)
            return

        launched = False
        if self.launch_var.get():
            try:
                _spawn_launcher(target)
                launched = True
            except OSError as exc:
                warnings.append(str(exc))
        self._show_done(target, warnings, launched)

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.install_button.configure(
            state=state, text=self.text["installing"] if busy
            else self.text["install"])
        self.cancel_button.configure(state=state)
        self.browse_button.configure(state=state)
        self.entry.configure(state=state)

    def _progress(self, percent: int):
        if percent <= 45:
            caption = self.text["step_copy"]
        elif percent <= 75:
            caption = self.text["step_shortcuts"]
        elif percent < 100:
            caption = self.text["step_registry"]
        else:
            caption = self.text["installing"]
        self.status.configure(text=caption)
        self.progress.configure(value=percent)
        self.root.update_idletasks()

    # ------------------------------------------------------------- done view

    def _show_done(self, target: Path, warnings, launched: bool):
        tk = self.tk
        self._clear_content()
        tk.Label(self.content, text="✓", bg=BG, fg=ACCENT,
                 font=(FONT, 30, "bold")).pack(anchor="w", pady=(4, 6))
        tk.Label(self.content, text=self.text["done_title"], bg=BG, fg=TEXT,
                 font=(FONT, 15, "bold"), anchor="w").pack(anchor="w")
        self._label(self.content, self.text["done_text"].format(
            path=target), size=10, color=DIM).pack(anchor="w", pady=(8, 0))
        if warnings:
            self._label(self.content, self.text["done_warn"].format(
                warnings="\n".join(warnings)), size=9,
                color=WARN).pack(anchor="w", pady=(10, 0))
        buttons = tk.Frame(self.content, bg=BG)
        buttons.pack(fill="x", pady=(18, 0))
        self._button(buttons, self.text["close"], self.root.destroy,
                     kind="primary").pack(side="right")
        if not launched:
            self._button(
                buttons, self.text["run"],
                lambda: (self._run(target), self.root.destroy()),
                kind="ghost").pack(side="right", padx=(0, 10))

    def _run(self, target: Path):
        try:
            _spawn_launcher(target)
        except OSError:
            pass

    # ------------------------------------------------------ uninstall screen

    def _build_uninstall_form(self):
        tk = self.tk
        start = registered_dir() or _guess_install_dir() or str(default_dir())
        self.target = Path(start)
        self.remove_data_var = tk.BooleanVar(value=False)

        self._label(self.content, self.text["uninstall_where"].format(
            path=start), size=10).pack(anchor="w")
        self._checkbutton(self.content, self.text["remove_data"],
                          self.remove_data_var).pack(anchor="w",
                                                     pady=(18, 2))
        self._label(self.content, self.text["remove_data_hint"], size=9,
                    color=DIM).pack(anchor="w")

        self.progress = self.ttk.Progressbar(
            self.content, style="Nexi.Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self.status = self._label(self.content, "", size=9, color=DIM)
        self.status.pack(anchor="w", pady=(16, 4))
        self.progress.pack(fill="x", pady=(0, 12))

        buttons = tk.Frame(self.content, bg=BG)
        buttons.pack(fill="x", pady=(8, 0))
        self.remove_button = self._button(
            buttons, self.text["uninstall_button"], self._start_uninstall,
            kind="danger")
        self.remove_button.pack(side="right")
        self.cancel_button = self._button(
            buttons, self.text["cancel"], self.root.destroy)
        self.cancel_button.pack(side="right", padx=(0, 10))

    def _start_uninstall(self):
        from tkinter import messagebox
        kill_first = False
        if launcher_running(self.target):
            if not messagebox.askyesno(self.text["running_title"],
                                       self.text["running_text"],
                                       parent=self.root):
                return
            kill_first = True
        self.remove_button.configure(state="disabled", text=self.text[
            "uninstalling"])
        self.cancel_button.configure(state="disabled")
        self.status.configure(text=self.text["uninstalling"])
        self.root.update_idletasks()
        try:
            relaunched = remove_installation(
                self.target, self.remove_data_var.get(),
                progress=self._uninstall_progress, kill_first=kill_first)
        except Exception as exc:
            log(traceback.format_exc())
            messagebox.showerror(self.text["error_title"], str(exc),
                                 parent=self.root)
            self.remove_button.configure(state="normal",
                                         text=self.text["uninstall_button"])
            self.cancel_button.configure(state="normal")
            return
        if relaunched:
            self.root.destroy()
            return
        self._show_uninstalled()

    def _uninstall_progress(self, percent: int):
        self.progress.configure(value=percent)
        self.root.update_idletasks()

    def _show_uninstalled(self):
        tk = self.tk
        self._clear_content()
        tk.Label(self.content, text="✓", bg=BG, fg=ACCENT,
                 font=(FONT, 30, "bold")).pack(anchor="w", pady=(4, 6))
        tk.Label(self.content, text=self.text["uninstall_done"], bg=BG,
                 fg=TEXT, font=(FONT, 15, "bold"), anchor="w").pack(anchor="w")
        if not self.remove_data_var.get():
            self._label(self.content, self.text["keep_data_note"], size=10,
                        color=DIM).pack(anchor="w", pady=(10, 0))
        buttons = tk.Frame(self.content, bg=BG)
        buttons.pack(fill="x", pady=(22, 0))
        self._button(buttons, self.text["close"], self.root.destroy,
                     kind="primary").pack(side="right")

    def show(self):
        self.root.mainloop()


# ------------------------------------------------------------------------ main

class WebView2Window:
    """Native bootstrap window used when WebView2 is not installed.

    The pretty installer needs WebView2 itself, so this small window first
    downloads Microsoft's Evergreen bootstrapper, runs it silently and starts
    the web setup as soon as the runtime is registered.
    """

    def __init__(self, language: str):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.text = TEXTS[language]
        self.success = False
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title(self.text["webview_title"])
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        try:
            scale = float(self.root.tk.call("tk", "scaling"))
        except Exception:
            scale = 1.3333
        self.ui = max(1.0, scale / 1.3333)
        self.wrap = int(430 * self.ui)

        icon = _asset_path("nexi.ico")
        if icon is not None:
            try:
                self.root.iconbitmap(default=str(icon))
            except Exception:
                pass

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Bootstrap.Horizontal.TProgressbar",
                        troughcolor=FIELD, background=ACCENT,
                        bordercolor=FIELD, lightcolor=ACCENT,
                        darkcolor=ACCENT, thickness=int(8 * self.ui))

        outer = tk.Frame(self.root, bg=BG, padx=26, pady=22)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        icon_file = _asset_path("star_icon_rounded.png")
        if icon_file is not None:
            try:
                self._icon = tk.PhotoImage(file=str(icon_file))
                factor = max(1, self._icon.width() // 40)
                if factor > 1:
                    self._icon = self._icon.subsample(factor, factor)
                tk.Label(header, image=self._icon, bg=BG).pack(
                    side="left", padx=(0, 12))
            except Exception:
                self._icon = None
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", anchor="w")
        tk.Label(titles, text=self.text["webview_heading"], bg=BG, fg=TEXT,
                 font=(FONT, 13, "bold")).pack(anchor="w")
        tk.Label(titles, text="NEXI LAUNCHER", bg=BG, fg=FAINT,
                 font=(FONT, 8)).pack(anchor="w", pady=(2, 0))

        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(16, 14))

        tk.Label(outer, text=self.text["webview_text"], bg=BG, fg=DIM,
                 font=(FONT, 9), anchor="w", justify="left",
                 wraplength=self.wrap).pack(fill="x")

        self.progress = ttk.Progressbar(
            outer, style="Bootstrap.Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(16, 8))

        self.status = tk.Label(outer, text=self.text["webview_downloading"],
                               bg=BG, fg=DIM, font=(FONT, 9), anchor="w",
                               justify="left", wraplength=self.wrap)
        self.status.pack(fill="x")

        tk.Label(outer, text=self.text["webview_download_hint"], bg=BG,
                 fg=FAINT, font=(FONT, 8), anchor="w").pack(fill="x",
                                                            pady=(6, 0))
        tk.Label(outer, text=self.text["webview_note"], bg=BG, fg=FAINT,
                 font=(FONT, 8), anchor="w", justify="left",
                 wraplength=self.wrap).pack(fill="x", pady=(10, 0))

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(16, 0))
        self.close_button = self._button(buttons, self.text["webview_close"],
                                         self._close)
        self.close_button.pack(side="right")
        self.manual_button = self._button(
            buttons, self.text["webview_manual"], self._open_manual)
        self.manual_button.pack(side="right", padx=(0, 10))
        self.retry_button = self._button(
            buttons, self.text["webview_retry"], self._start, kind="primary")
        # Packed only after a failure; kept here so `before=` can find it.

        self.root.update_idletasks()
        width = max(self.root.winfo_reqwidth(), int(490 * self.ui))
        height = self.root.winfo_reqheight()
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2 - 40)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self.root.after(250, self._start)
        self.root.after(120, self._drain)

    def _button(self, parent, text, command, kind="ghost"):
        colors = {
            "primary": (ACCENT, ACCENT_HOVER, ACCENT_FG),
            "ghost": (GHOST_BG, GHOST_HOVER, TEXT),
        }
        background, hover, foreground = colors[kind]
        button = self.tk.Button(
            parent, text=text, command=command, bg=background, fg=foreground,
            activebackground=hover, activeforeground=foreground,
            relief="flat", bd=0, padx=int(16 * self.ui),
            pady=int(7 * self.ui), font=(FONT, 9), cursor="hand2")
        button.bind("<Enter>", lambda _e: button.configure(bg=hover))
        button.bind("<Leave>", lambda _e: button.configure(bg=background))
        return button

    def _start(self):
        if self._worker is not None and self._worker.is_alive():
            return
        self.retry_button.pack_forget()
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.status.configure(text=self.text["webview_downloading"], fg=DIM)
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

    def _work(self):
        try:
            def report(done: int, total: int) -> None:
                percent = int(done * 100 / total) if total else 0
                self._queue.put(("progress", percent))

            bootstrapper = download_webview2(progress=report)
            self._queue.put(("installing", None))
            code = run_webview2_installer(bootstrapper)
            if wait_for_webview2():
                self._queue.put(("ok", None))
            else:
                self._queue.put(("fail", f"exit code {code}"))
        except Exception as exc:
            log(traceback.format_exc())
            self._queue.put(("fail", str(exc)))

    def _drain(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self.progress.configure(value=payload)
                elif kind == "installing":
                    self.progress.stop()
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(12)
                    self.status.configure(text=self.text["webview_installing"])
                elif kind == "ok":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=100)
                    self.status.configure(text=self.text["webview_ready"],
                                          fg=ACCENT)
                    self.success = True
                    self.root.after(700, self._close)
                elif kind == "fail":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    detail = str(payload or "").strip()
                    message = self.text["webview_failed"]
                    if detail:
                        message = f"{message} ({detail})"
                    self.status.configure(text=message, fg="#ff8a8a")
                    self.retry_button.pack(side="right", padx=(0, 10),
                                           before=self.manual_button)
        except queue.Empty:
            pass
        try:
            alive = bool(self.root.winfo_exists())
        except Exception:
            alive = False
        if alive:
            self.root.after(120, self._drain)

    def _open_manual(self):
        try:
            os.startfile(WEBVIEW2_URL)
        except OSError:
            pass

    def _close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def show(self) -> bool:
        self.root.mainloop()
        return self.success


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args[:1] == ["--cleanup"] and len(args) >= 2:
        return cleanup_main(args[1])

    _enable_dpi_awareness()
    language = ui_language()

    if "--silent-uninstall" in args:
        target = (_arg_value(args, "--dir") or registered_dir()
                  or _guess_install_dir())
        if not target:
            log("silent uninstall: no installation found")
            return 1
        try:
            remove_installation(Path(target), "--remove-data" in args,
                                kill_first=True)
            return 0
        except Exception:
            log(traceback.format_exc())
            return 1

    if "--silent" in args:
        target = Path(_arg_value(args, "--dir") or registered_dir()
                      or default_dir())
        try:
            target = _validate_dir(str(target))
            install(target,
                    desktop="--no-shortcuts" not in args,
                    launch="--no-launch" not in args,
                    force_kill=True)
            return 0
        except Exception:
            log(traceback.format_exc())
            return 1

    mode = "uninstall" if "--uninstall" in args else "install"

    # The web UI itself is rendered by WebView2. On machines without it,
    # a small native window installs the runtime first and then opens the
    # real setup, so the launcher is never installed without its UI.
    if not webview2_installed():
        bootstrap = WebView2Window(language)
        if not bootstrap.show():
            return 0

    try:
        WebSetup(mode, language).show()
        return 0
    except Exception:
        # Rare (for example a source checkout without pywebview): keep a
        # native fallback instead of failing silently.
        log(traceback.format_exc())

    window = SetupWindow(mode, language)
    window.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
