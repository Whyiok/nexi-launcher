"""Home background: a picture or a GIF/MP4/WebM clip picked in Settings.

Static images (PNG, JPG/JPEG/JFIF, WebP, BMP, AVIF) show as a still cover
behind the main menu; GIFs animate and videos loop. The file is copied into
``%APPDATA%\\NexiLauncher\\backgrounds`` so the original can be moved or
deleted without breaking the launcher, and it is published through the
loopback media server (a page served over http cannot read ``file://``
paths).
"""

import os
import shutil
from pathlib import Path

from .. import media
from ..config import BACKGROUNDS_DIR
from ..logging_setup import log
from ..util import pick_file

BACKGROUND_KINDS = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".jfif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".avif": "image",
    ".gif": "image",
    ".mp4": "video",
    ".webm": "video",
}


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
        """Native picker for a picture, GIF, MP4 or WebM background."""
        if os.name != "nt":
            return {"ok": False,
                    "error": "The background picker needs Windows."}
        try:
            picked = pick_file(
                "Select a background",
                (("Pictures and videos",
                  "*.png;*.jpg;*.jpeg;*.jfif;*.webp;*.bmp;*.avif;"
                  "*.gif;*.mp4;*.webm"),
                 ("Pictures", "*.png;*.jpg;*.jpeg;*.jfif;*.webp;*.bmp;"
                              "*.avif;*.gif"),
                 ("Video", "*.mp4;*.webm"),
                 ("All files", "*.*")))
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not open the file picker: {exc}"}
        picked = picked.strip().strip('"')
        if not picked:
            return {"ok": False, "cancelled": True}
        source = Path(picked)
        suffix = source.suffix.lower()
        if suffix not in BACKGROUND_KINDS:
            return {"ok": False,
                    "error": "Pick a PNG, JPG, WEBP, GIF, MP4 or WebM file."}
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
