"""Skin preview, upload and variant switching."""

import base64
import os
import subprocess
from pathlib import Path

from ..config import ELY_SKIN_SITE, SKINS_DIR
from ..logging_setup import log
from ..ms_auth import MC_SKIN_URL
from ..skin_images import (
    _default_skin_png, _ely_skin_png, _skin_dimensions, _upload_skin,
)
from ..util import open_in_system


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
