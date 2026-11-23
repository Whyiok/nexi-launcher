"""Check GitHub for a newer release and replace the running launcher.

The updater deliberately downloads only the release executable published in
the official repository and verifies the SHA-256 digest GitHub returns for
that asset. The swap itself is done by the *downloaded* build: it is started
with ``--nexi-finish-update`` (or ``--nexi-apply-dir`` for the installed
folder build), waits for this process to exit and only then replaces the
files, so no batch file or shell is involved. User data in
``%APPDATA%\\NexiLauncher`` is never touched.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .logging_setup import log
from .net import open_url
from .util import InstallCancelled
from .version import VERSION

RELEASE_REPO = "Whyiok/nexi-launcher"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{RELEASE_REPO}/releases/latest")
ASSET_NAME = "Nexi-Portable.exe"
ASSET_NAMES = (ASSET_NAME,)
# Installed builds run from a folder (exe plus ``_internal``) and update from
# the zipped folder asset instead of the single-file executable.
DIR_ASSET_NAME = "NexiLauncher.zip"
DIR_ASSET_NAMES = (DIR_ASSET_NAME,)
USER_AGENT = f"NexiLauncher/{VERSION}"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

# Internal command line used when the downloaded build performs the swap.
HELPER_FLAG = "--nexi-finish-update"
DIR_HELPER_FLAG = "--nexi-apply-dir"
HELPER_FLAGS = (HELPER_FLAG, DIR_HELPER_FLAG)


def is_onedir() -> bool:
    """True when this process runs from an installed folder build."""
    try:
        return (Path(sys.executable).resolve().parent / "_internal").is_dir()
    except OSError:
        return False


def expected_asset_names() -> tuple:
    return DIR_ASSET_NAMES if is_onedir() else ASSET_NAMES


# PyInstaller one-file builds tell child processes where their extraction
# folder is. A launcher started from a frozen parent would therefore inherit
# the *old* ``%TEMP%\\_MEI...`` path, which is deleted when that parent exits,
# and fail with "Failed to load Python DLL ...\\_MEI...\\python314.dll". These
# variables are removed before starting another build so it unpacks itself.
_PYI_ENV_VARS = ("_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL",
                 "_PYI_SPLASH_IPC", "_PYI_ARCHIVE_FILE", "_MEIPASS2")


def child_environment() -> dict:
    env = dict(os.environ)
    for name in _PYI_ENV_VARS:
        env.pop(name, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


class UpdateError(Exception):
    """A problem the update card can show to the user."""


def version_tuple(value: str) -> tuple:
    """``v1.5.0`` -> ``(1, 5, 0)``; non-numeric parts are ignored."""
    match = re.match(r"^\s*[vV]?(\d+(?:\.\d+)*)", str(value or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str = VERSION) -> bool:
    newer = version_tuple(candidate)
    if not newer:
        return False
    older = version_tuple(current)
    width = max(len(newer), len(older))
    newer += (0,) * (width - len(newer))
    older += (0,) * (width - len(older))
    return newer > older


def _request_json(url: str, timeout: float = 25) -> dict:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    })
    try:
        with open_url(request, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                "No published release was found in the repository.") from exc
        raise UpdateError(f"GitHub answered with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"GitHub could not be reached: {exc}") from exc
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("GitHub returned an unreadable release list.") from exc
    if not isinstance(data, dict):
        raise UpdateError("GitHub returned an unexpected release list.")
    return data


def check_latest(current: str = VERSION) -> dict:
    """Describe the latest release and whether it is newer than *current*."""
    data = _request_json(LATEST_RELEASE_API)
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    version = tag.lstrip("vV").strip()
    if not version:
        raise UpdateError("The latest release has no version tag.")
    available = is_newer(version, current)
    names = expected_asset_names()
    asset = None
    for name in names:
        for item in data.get("assets") or []:
            if isinstance(item, dict) and item.get("name") == name:
                asset = item
                break
        if asset is not None:
            break
    if available and asset is None:
        raise UpdateError(
            f"The latest release does not include {names[0]}.")
    url = ""
    size = 0
    digest = ""
    if asset is not None:
        url = str(asset.get("browser_download_url") or "")
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        digest = str(asset.get("digest") or "")
        if not url:
            raise UpdateError("The update asset has no download address.")
    notes = str(data.get("body") or "").strip()
    if len(notes) > 4000:
        notes = notes[:3997] + "…"
    return {
        "current": current,
        "latest": version,
        "available": available,
        "url": url,
        "size": size,
        "digest": digest,
        "notes": notes,
        "published": str(data.get("published_at") or ""),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset(path: Path, digest: str) -> None:
    """Refuse an update that has no usable SHA-256 from the release.

    GitHub publishes a ``sha256:`` digest for every release asset. Failing
    closed means a truncated, swapped or MITM'd download is never run, even if
    the release metadata was incomplete.
    """
    expected = str(digest or "").strip().lower()
    if expected.startswith("sha256:"):
        expected = expected[7:]
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        path.unlink(missing_ok=True)
        raise UpdateError(
            "The release does not publish a SHA-256 checksum for the "
            "download, so it was not installed.")
    actual = _sha256(path)
    if actual != expected:
        path.unlink(missing_ok=True)
        raise UpdateError("The downloaded update failed the integrity check.")


def download_update(info: dict, on_progress=None, cancel=None) -> Path:
    """Download the release asset into a private temporary folder."""
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    version = str(info.get("latest") or "").strip() or "latest"
    url = str(info.get("url") or "").strip()
    if not url:
        raise UpdateError("The update has no download address.")
    suffix = ".zip" if is_onedir() else ".exe"
    folder = Path(tempfile.gettempdir()) / "NexiLauncherUpdate"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"nexi-{version}{suffix}"
    try:
        size = int(info.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if not (target.is_file() and size and target.stat().st_size == size):
        from .net import download_file

        download_file(url, target, size=size or None, cancel=cancel,
                      timeout=180, on_progress=on_progress)
    verify_asset(target, str(info.get("digest") or ""))
    if target.stat().st_size < 1024 * 1024:
        target.unlink(missing_ok=True)
        raise UpdateError("The downloaded update is too small.")
    log.info("update: downloaded %s (%d bytes)", target.name,
             target.stat().st_size)
    return target


def _writable(folder: Path) -> bool:
    probe = folder / f".nexi-update-probe-{os.getpid()}"
    try:
        probe.write_bytes(b"probe")
        probe.unlink()
        return True
    except OSError:
        return False


def can_replace_running_exe() -> tuple:
    if not getattr(sys, "frozen", False):
        return False, "Updates are only available in the built launcher."
    target = Path(sys.executable).resolve()
    if not target.is_file():
        return False, f"The launcher executable was not found at {target}."
    if not _writable(target.parent):
        return False, (f"The launcher folder is not writable: {target.parent}. "
                       "Run the installer to update instead.")
    return True, ""


def _extract_update(archive: Path) -> Path:
    """Unpack the folder build into a fresh temp directory."""
    folder = archive.parent / f"app-{archive.stem}"
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = info.filename.replace("\\", "/")
                if not name or name.endswith("/"):
                    continue
                parts = Path(name).parts
                if name.startswith("/") or ".." in parts:
                    raise UpdateError(
                        "The downloaded update contains unsafe paths.")
                destination = (root / name).resolve()
                if os.path.commonpath([str(destination), str(root)]) != str(root):
                    raise UpdateError(
                        "The downloaded update contains unsafe paths.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(destination, "wb") as out:
                    shutil.copyfileobj(source, out)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(f"The downloaded update is not a valid archive: "
                          f"{exc}") from exc
    exe = root / "NexiLauncher.exe"
    if not exe.is_file() or not (root / "_internal").is_dir():
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError("The downloaded archive does not contain the "
                          "launcher.")
    return root


def apply_update(downloaded: Path) -> None:
    """Start the downloaded build, which swaps the files once we exit."""
    ok, reason = can_replace_running_exe()
    if not ok:
        raise UpdateError(reason)
    target = Path(sys.executable).resolve()
    downloaded = Path(downloaded).resolve()
    if not downloaded.is_file():
        raise UpdateError("The downloaded update is missing.")
    if downloaded.suffix.lower() == ".zip":
        # The new folder build lives in a temp directory of its own; it copies
        # itself over the installation after the old process is gone.
        exe = _extract_update(downloaded) / "NexiLauncher.exe"
        argv = [str(exe), DIR_HELPER_FLAG, str(target.parent),
                str(os.getpid())]
    else:
        argv = [str(downloaded), HELPER_FLAG, str(target), str(os.getpid())]
    try:
        subprocess.Popen(argv, creationflags=CREATE_NO_WINDOW
                         | DETACHED_PROCESS, close_fds=True,
                         env=child_environment())
    except OSError as exc:
        raise UpdateError(f"Could not start the updater: {exc}") from exc
    log.info("update: replacement of %s scheduled", target)


# ------------------------------------------------------------ update helper
#
# These functions run inside the newly downloaded build. They wait for the old
# launcher to exit, replace the files and start the result. Keeping the work in
# the new executable avoids the self-replacing batch file that antivirus
# sandboxes read as dropper behaviour.

def parse_helper_args(argv) -> tuple | None:
    """``[flag, target, pid]`` -> ``(flag, target, pid)`` or None."""
    if len(argv) != 3 or argv[0] not in HELPER_FLAGS:
        return None
    try:
        pid = int(argv[2])
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    target = str(argv[1] or "").strip()
    if not target or not os.path.isabs(target):
        return None
    return argv[0], target, pid


_KERNEL32 = None


def _kernel32():
    """kernel32 with 64-bit-safe prototypes for the process helpers."""
    global _KERNEL32
    if _KERNEL32 is not None:
        return _KERNEL32
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32 = kernel32
    return kernel32


def _pid_alive(pid: int) -> bool:
    kernel32 = _kernel32()
    synchronize = 0x00100000
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_exit(pid: int, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while _pid_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def _replace_exe(target: Path) -> None:
    source = Path(sys.executable).resolve()
    if target.suffix.lower() != ".exe":
        raise UpdateError("The update target is not an executable.")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(target.name + ".new")
    deadline = time.monotonic() + 120
    while True:
        try:
            shutil.copyfile(source, staged)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
            continue
        break
    while True:
        try:
            os.replace(staged, target)
            return
        except OSError as exc:
            if time.monotonic() >= deadline:
                staged.unlink(missing_ok=True)
                raise UpdateError(f"Could not replace {target}: {exc}") from exc
            time.sleep(0.5)


def _replace_dir(target: Path) -> None:
    source = Path(sys.executable).resolve().parent
    if not (source / "_internal").is_dir() or not (
            source / "NexiLauncher.exe").is_file():
        raise UpdateError("The downloaded update is incomplete.")
    if source == target.resolve():
        raise UpdateError("The update source and target are the same folder.")
    target.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 180
    while True:
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
            return
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise UpdateError(
                    f"Could not replace {target}: {exc}") from exc
            time.sleep(0.5)


def _start_installed(mode: str, target: Path) -> None:
    exe = target if mode == HELPER_FLAG else target / "NexiLauncher.exe"
    for attempt in range(3):
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent),
                             creationflags=DETACHED_PROCESS,
                             close_fds=True, env=child_environment())
            return
        except OSError:
            if attempt == 2:
                log.exception("update helper: could not restart %s", exe)
                return
            time.sleep(1.0)


def finish_update(argv) -> bool:
    """Handle a helper invocation; returns True when nothing else should run."""
    parsed = parse_helper_args(argv)
    if parsed is None:
        return False
    try:
        from .logging_setup import setup_logging
        setup_logging()
    except Exception:
        pass
    mode, target, pid = parsed
    log.info("update helper: waiting for the old launcher to exit")
    if not _wait_for_exit(pid):
        log.warning("update helper: the old launcher is still running")
        return True
    destination = Path(target)
    try:
        if mode == HELPER_FLAG:
            _replace_exe(destination)
        else:
            _replace_dir(destination)
        log.info("update helper: installed %s", destination)
    except Exception:
        log.exception("update helper: could not install the update")
    _start_installed(mode, destination)
    return True
