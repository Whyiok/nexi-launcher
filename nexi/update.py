"""Check GitHub for a newer release and replace the running launcher.

The updater deliberately downloads only the ``nexi.exe`` asset published in the
official repository, verifies the SHA-256 digest GitHub returns for that asset,
and then lets a tiny detached batch file swap the executable once this process
has exited. User data in ``%APPDATA%\\NexiLauncher`` is never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .logging_setup import log
from .net import open_url
from .util import InstallCancelled
from .version import VERSION

RELEASE_REPO = "Whyiok/nexi-launcher"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{RELEASE_REPO}/releases/latest")
ASSET_NAME = "nexi.exe"
USER_AGENT = f"NexiLauncher/{VERSION}"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


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
    asset = None
    for item in data.get("assets") or []:
        if isinstance(item, dict) and item.get("name") == ASSET_NAME:
            asset = item
            break
    if available and asset is None:
        raise UpdateError(
            f"The latest release does not include {ASSET_NAME}.")
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
    expected = str(digest or "").strip().lower()
    if not expected:
        return
    if expected.startswith("sha256:"):
        expected = expected[7:]
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return
    actual = _sha256(path)
    if actual != expected:
        raise UpdateError("The downloaded update failed the integrity check.")


def download_update(info: dict, on_progress=None, cancel=None) -> Path:
    """Download the release executable into a private temporary folder."""
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    version = str(info.get("latest") or "").strip() or "latest"
    url = str(info.get("url") or "").strip()
    if not url:
        raise UpdateError("The update has no download address.")
    folder = Path(tempfile.gettempdir()) / "NexiLauncherUpdate"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"nexi-{version}.exe"
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


def apply_update(downloaded: Path) -> None:
    """Start a detached helper that swaps the exe after this process exits."""
    ok, reason = can_replace_running_exe()
    if not ok:
        raise UpdateError(reason)
    target = Path(sys.executable).resolve()
    downloaded = Path(downloaded).resolve()
    if not downloaded.is_file():
        raise UpdateError("The downloaded update is missing.")
    batch = Path(tempfile.gettempdir()) / f"NexiUpdate-{os.getpid()}.cmd"
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        'set "SRC=%NEXI_UPDATE_SRC%"\r\n'
        'set "DST=%NEXI_UPDATE_DST%"\r\n'
        'set "NEW=%DST%.new"\r\n'
        "set tries=0\r\n"
        ":copy\r\n"
        'copy /y "%SRC%" "%NEW%" >nul 2>&1\r\n'
        "if not errorlevel 1 goto move\r\n"
        "set /a tries+=1\r\n"
        "if %tries% geq 240 goto fail\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto copy\r\n"
        ":move\r\n"
        'move /y "%NEW%" "%DST%" >nul 2>&1\r\n'
        "if not errorlevel 1 goto done\r\n"
        "set /a tries+=1\r\n"
        "if %tries% geq 240 goto fail\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto move\r\n"
        ":done\r\n"
        'start "" "%DST%"\r\n'
        'del /f /q "%SRC%" >nul 2>&1\r\n'
        '(goto) 2>nul & del /f /q "%~f0"\r\n'
        "exit /b 0\r\n"
        ":fail\r\n"
        'del /f /q "%NEW%" >nul 2>&1\r\n'
        'start "" "%DST%"\r\n'
        'del /f /q "%SRC%" >nul 2>&1\r\n'
        '(goto) 2>nul & del /f /q "%~f0"\r\n'
        "exit /b 1\r\n"
    )
    try:
        batch.write_text(script, encoding="ascii")
    except OSError as exc:
        raise UpdateError(f"Could not write the updater script: {exc}") from exc
    env = dict(os.environ)
    env["NEXI_UPDATE_SRC"] = str(downloaded)
    env["NEXI_UPDATE_DST"] = str(target)
    try:
        subprocess.Popen(
            ["cmd.exe", "/d", "/c", str(batch)],
            env=env,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"Could not start the updater: {exc}") from exc
    log.info("update: replacement of %s scheduled", target)
