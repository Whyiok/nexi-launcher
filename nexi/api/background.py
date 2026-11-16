"""Home background: a GIF, MP4 or WebM picked in Settings.

The file is copied into ``%APPDATA%\\NexiLauncher\\backgrounds`` so the
original can be moved or deleted without breaking the launcher, and it is
published through the loopback media server (a page served over http cannot
read ``file://`` paths).
"""

import os
import shutil
import subprocess
from pathlib import Path

from .. import media
from ..config import BACKGROUNDS_DIR
from ..logging_setup import log

BACKGROUND_KINDS = {".gif": "image", ".mp4": "video", ".webm": "video"}


class BackgroundApi:
    def _background_payload(self):
        """What the Home screen needs to show the chosen background."""
        info = self._background if isinstance(self._background, dict) else {}
        name = Path(str(info.get("file") or "")).name
        path = BACKGROUNDS_DIR / name if name else None
        if path is None or not path.is_file():
            return {"active": False, "kind": "", "name": "", "url": ""}
        kind = BACKGROUND_KINDS.get(path.suffix.lower(), "image")
        return {
            "active": True,
            "kind": kind,
            "name": str(info.get("name") or path.name),
            "url": media.url_for(path),
        }

    def background_pick(self):
        """Native picker for a GIF, MP4 or WebM background."""
        if os.name != "nt":
            return {"ok": False,
                    "error": "The background picker needs Windows."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = 'Select a background'; "
            "$d.Filter = 'Backgrounds (*.gif;*.mp4;*.webm)|*.gif;*.mp4;*.webm|"
            "GIF (*.gif)|*.gif|Video (*.mp4;*.webm)|*.mp4;*.webm|"
            "All files (*.*)|*.*'; "
            "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.FileName) }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", script],
                capture_output=True, text=True, timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False,
                    "error": f"Could not open the file picker: {exc}"}
        picked = (result.stdout or "").strip().strip('"')
        if not picked:
            return {"ok": False, "cancelled": True}
        source = Path(picked)
        suffix = source.suffix.lower()
        if suffix not in BACKGROUND_KINDS:
            return {"ok": False,
                    "error": "Pick a GIF, MP4 or WebM file."}
        if not source.is_file():
            return {"ok": False,
                    "error": "The selected file was not found."}
        try:
            BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
            target = BACKGROUNDS_DIR / f"background{suffix}"
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not copy the background: {exc}"}
        # Only one background is kept, so drop any file left from before.
        for path in BACKGROUNDS_DIR.iterdir():
            if path != target and path.suffix.lower() in BACKGROUND_KINDS:
                try:
                    path.unlink()
                except OSError:
                    pass
        with self._lock:
            self._background = {"file": target.name,
                                "name": source.name,
                                "kind": BACKGROUND_KINDS[suffix]}
            self._save()
        log.info("Home background: %s", source.name)
        return {"ok": True, "state": self.state()}

    def background_clear(self):
        """Go back to the animated panorama."""
        with self._lock:
            self._background = {}
            self._save()
        try:
            for path in BACKGROUNDS_DIR.iterdir():
                if path.suffix.lower() in BACKGROUND_KINDS:
                    path.unlink()
        except OSError:
            pass
        log.info("Home background cleared")
        return {"ok": True, "state": self.state()}
