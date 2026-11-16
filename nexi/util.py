"""Small helpers used across the launcher."""

import json
import os
import platform
import re
import subprocess
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
