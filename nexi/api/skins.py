"""Skin preview, upload and variant switching."""

import base64
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from ..config import ELY_SKIN_SITE, SKINS_DIR
from ..logging_setup import log
from ..ms_auth import MC_SKIN_URL
from ..skin_images import (
    _default_skin_png, _ely_skin_png, _skin_dimensions, _upload_skin,
)
from ..util import open_in_system

SKIN_HISTORY_LIMIT = 24
HISTORY_DIR = SKINS_DIR / "history"
_HISTORY_HASH = re.compile(r"^[0-9a-f]{16}$")


class SkinsApi:
    def _skin_path(self, account):
        return SKINS_DIR / f"{account['id']}.png"

    def _skin_account(self, account_id=""):
        """The account whose skin is being managed, falling back to the active
        one. The skin page can target any account, not only the active one."""
        return self._account_by_id(account_id) or self._active_account()

    def _skin_payload(self, account_id=""):
        account = self._skin_account(account_id)
        if account is None:
            return {"ok": False,
                    "error": "Add an account in Settings first."}
        path = self._skin_path(account)
        data = None
        if path.is_file():
            try:
                data = path.read_bytes()
            except OSError:
                data = None
        default = data is None
        remote = False
        variant = account.get("skin_variant", "classic")
        variant = "slim" if variant == "slim" else "classic"
        manage_url = ""
        if account["type"] == "ely":
            # The website owns the skin; show what it currently serves.
            manage_url = ELY_SKIN_SITE
            remote_data, remote_variant = _ely_skin_png(account)
            if remote_data is not None:
                data = remote_data
                default = False
                remote = True
                if remote_variant:
                    variant = remote_variant
        if data is None:
            data = _default_skin_png()
        skin = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        return {
            "ok": True,
            "id": account["id"],
            "name": account["name"],
            "type": account["type"],
            "uuid": account.get("uuid", ""),
            "online": account["type"] != "offline"
                      and bool(account.get("uuid", "")),
            "variant": variant,
            "skin": skin,
            "default": default,
            "remote": remote,
            "manage_url": manage_url,
            "path": "" if (default or remote) else str(path),
        }

    def skin_state(self, account_id=""):
        return self._skin_payload(account_id)

    # ------------------------------------------------------- skin history
    #
    # Every skin the launcher saves is also copied into
    # ``%APPDATA%\NexiLauncher\skins\history`` with a small JSON index, so a
    # previous skin can be restored with one click. The files are plain PNGs
    # of the account's own skins; nothing here ever leaves the computer.

    def _history_index_path(self):
        return HISTORY_DIR / "index.json"

    def _history_index(self):
        try:
            parsed = json.loads(
                self._history_index_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = parsed.get("items") if isinstance(parsed, dict) else None
        if not isinstance(items, list):
            return []
        clean = []
        for item in items:
            if not isinstance(item, dict):
                continue
            digest = str(item.get("hash") or "")
            if not _HISTORY_HASH.match(digest):
                continue
            clean.append({
                "hash": digest,
                "variant": "slim" if item.get("variant") == "slim"
                           else "classic",
                "source": str(item.get("source") or ""),
                "added": int(item.get("added") or 0),
            })
        return clean

    def _history_write(self, items):
        try:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            self._history_index_path().write_text(
                json.dumps({"version": 1, "items": items},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write the skin history index: %s", exc)

    def _history_add(self, data, variant, source):
        """Keep ``data`` in the history; returns its id or an empty string."""
        digest = hashlib.sha256(data).hexdigest()[:16]
        items = [item for item in self._history_index()
                 if item["hash"] != digest]
        try:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            (HISTORY_DIR / f"{digest}.png").write_bytes(data)
        except OSError as exc:
            log.warning("Could not keep the skin in history: %s", exc)
            return ""
        items.insert(0, {
            "hash": digest,
            "variant": "slim" if variant == "slim" else "classic",
            "source": str(source or ""),
            "added": int(time.time()),
        })
        for extra in items[SKIN_HISTORY_LIMIT:]:
            try:
                (HISTORY_DIR / f"{extra['hash']}.png").unlink()
            except OSError:
                pass
        del items[SKIN_HISTORY_LIMIT:]
        self._history_write(items)
        return digest

    def _history_seed(self):
        """One-time import of skins picked before the history existed."""
        if self._history_index_path().exists():
            return
        for account in getattr(self, "_accounts", None) or []:
            path = self._skin_path(account)
            try:
                data = path.read_bytes()
            except OSError:
                continue
            self._history_add(data, account.get("skin_variant", "classic"),
                              account.get("name", ""))
        # An empty index marks the seed as done even when there was nothing
        # to import.
        self._history_write(self._history_index())

    def skin_history(self, account_id=""):
        """Items for the skin history row, newest first."""
        account = self._skin_account(account_id)
        if account is None:
            return {"ok": False, "items": [],
                    "error": "Add an account in Settings first."}
        self._history_seed()
        current_hash = ""
        path = self._skin_path(account)
        try:
            if path.is_file():
                current_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            current_hash = ""
        items = []
        missing = False
        for entry in self._history_index():
            try:
                data = (HISTORY_DIR / f"{entry['hash']}.png").read_bytes()
            except OSError:
                missing = True
                continue
            items.append({
                "hash": entry["hash"],
                "variant": entry["variant"],
                "source": entry["source"],
                "added": entry["added"],
                "active": entry["hash"] == current_hash,
                "skin": "data:image/png;base64,"
                        + base64.b64encode(data).decode("ascii"),
            })
        if missing:
            self._history_write([{
                "hash": item["hash"],
                "variant": item["variant"],
                "source": item["source"],
                "added": item["added"],
            } for item in items])
        return {"ok": True, "items": items, "limit": SKIN_HISTORY_LIMIT}

    def skin_history_use(self, digest="", account_id=""):
        """Make a history entry the chosen skin of the account again."""
        account = self._skin_account(account_id)
        if account is None:
            return {"ok": False,
                    "error": "Add an account in Settings first."}
        if account["type"] != "microsoft":
            return {"ok": False,
                    "error": "Skins can only be applied to a Microsoft "
                             "account."}
        digest = str(digest or "").strip().lower()
        if not _HISTORY_HASH.match(digest):
            return {"ok": False, "error": "That skin is not in the history."}
        path = HISTORY_DIR / f"{digest}.png"
        try:
            data = path.read_bytes()
        except OSError:
            return {"ok": False,
                    "error": "That skin is no longer in the history."}
        if _skin_dimensions(data) not in ((64, 64), (64, 32)):
            return {"ok": False,
                    "error": "The saved skin file is not a Minecraft skin."}
        try:
            SKINS_DIR.mkdir(parents=True, exist_ok=True)
            self._skin_path(account).write_bytes(data)
        except OSError as exc:
            return {"ok": False, "error": f"Could not save the skin: {exc}"}
        entry = next((item for item in self._history_index()
                      if item["hash"] == digest), None)
        if entry is not None:
            with self._lock:
                account["skin_variant"] = entry["variant"]
                self._save()
        log.info("Skin restored from history for account %s", account["name"])
        return self._skin_payload(account["id"])

    def skin_history_clear(self, account_id=""):
        """Delete every history entry; the account's current skin is kept."""
        try:
            for path in HISTORY_DIR.glob("*.png"):
                path.unlink()
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not clear the skin history: {exc}"}
        self._history_write([])
        log.info("Skin history cleared")
        return {"ok": True, "items": []}

    def skin_pick(self, account_id=""):
        """Pick a PNG skin file and keep a copy for the chosen account."""
        account = self._skin_account(account_id)
        if account is None:
            return {"ok": False,
                    "error": "Add an account in Settings first."}
        if account["type"] == "offline":
            return {"ok": False,
                    "error": "Offline accounts cannot change their skin."}
        if account["type"] == "ely":
            return {"ok": False,
                    "error": "Ely.by skins are changed on ely.by/skins — "
                             "use the link on this page."}
        if os.name != "nt":
            return {"ok": False, "error": "The image picker needs Windows."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = 'Select a Minecraft skin'; "
            "$d.Filter = 'Minecraft skin (*.png)|*.png|All files (*.*)|*.*'; "
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
        picked = (result.stdout or "").strip()
        if not picked:
            return {"ok": False, "cancelled": True}
        try:
            data = Path(picked).read_bytes()
        except OSError as exc:
            return {"ok": False, "error": f"Could not read the image: {exc}"}
        if _skin_dimensions(data) not in ((64, 64), (64, 32)):
            return {"ok": False,
                    "error": "A Minecraft skin must be a 64×64 or "
                             "64×32 PNG."}
        try:
            SKINS_DIR.mkdir(parents=True, exist_ok=True)
            self._skin_path(account).write_bytes(data)
        except OSError as exc:
            return {"ok": False, "error": f"Could not save the skin: {exc}"}
        self._history_add(data, account.get("skin_variant", "classic"),
                          account.get("name", ""))
        log.info("Skin selected for account %s", account["name"])
        return self._skin_payload(account["id"])

    def skin_variant(self, variant="classic", account_id=""):
        variant = "slim" if str(variant).lower() == "slim" else "classic"
        with self._lock:
            account = self._skin_account(account_id)
            if account is None:
                return {"ok": False,
                        "error": "Add an account in Settings first."}
            account["skin_variant"] = variant
            self._save()
        return self._skin_payload(account["id"])

    def skin_apply(self, account_id=""):
        """Apply the chosen skin to the chosen (or active) account. Ely.by has
        no upload API, so its skin page is opened instead."""
        account = self._skin_account(account_id)
        if account is None:
            return {"ok": False,
                    "error": "Add an account in Settings first."}
        path = self._skin_path(account)
        try:
            data = path.read_bytes() if path.is_file() else _default_skin_png()
        except OSError as exc:
            return {"ok": False, "error": f"Could not read the skin file: {exc}"}
        variant = account.get("skin_variant", "classic")
        variant = "slim" if variant == "slim" else "classic"
        try:
            if account["type"] == "microsoft":
                token = self._ms_refresh(account)
                if not token:
                    return {"ok": False,
                            "error": "This Microsoft account needs to sign "
                                     "in again."}
                _upload_skin(MC_SKIN_URL, token,
                             [("variant", variant)], data)
            elif account["type"] == "ely":
                # Ely.by has no public API for changing skins — the website
                # owns them, and authlib-injector already makes the game load
                # them from there. Send the user to the site instead of
                # calling an endpoint that does not exist.
                open_in_system(ELY_SKIN_SITE)
                log.info("Ely.by skin page opened for account %s",
                         account["name"])
                return {"ok": True, "opened": True,
                        "message": "Ely.by changes skins on its website — "
                                   "ely.by/skins is open in your browser. "
                                   "Upload the PNG there and the game will "
                                   "load it through authlib-injector."}
            else:
                return {"ok": False,
                        "error": "Offline accounts cannot change the in-game "
                                 "skin. Add a Microsoft or Ely.by account."}
        except Exception as exc:
            log.warning("Skin upload failed: %s", exc)
            return {"ok": False, "error": f"Skin upload failed: {exc}"}
        log.info("Skin applied for account %s", account["name"])
        return {"ok": True,
                "message": f"Skin applied to {account['name']}."}
