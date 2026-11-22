"""Bridge plumbing, settings storage and account storage."""

import inspect
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .. import config, curseforge
from ..config import (DATA_DIR, ELY_OAUTH_REDIRECT_DEFAULT, MC,
                      NEXI_BASE_URL_DEFAULT, app_dir)
from ..game_options import normalize_defaults
from ..logging_setup import log
from ..net import (MIRROR_MODES, normalize_proxy, set_dns, set_mirror_mode,
                   set_mirror_notifier, set_proxy)
from ..util import _read_json, open_in_system


class BaseApi:
    RAM_MIN = 1
    RAM_MAX = 16
    THEMES = ("mint", "orange", "indigo")
    PETS = ("axi", "clawd")

    def __init__(self):
        self.instances = []
        self.selected_slug = str(self._saved("instance", "") or "")
        order = self._saved("instance_order", [])
        self.instance_order = ([str(slug) for slug in order if str(slug or "")]
                               if isinstance(order, list) else [])
        self.player = str(self._saved("player", "Player") or "Player")
        try:
            ram = int(self._saved("ram", 2) or 2)
        except (TypeError, ValueError):
            ram = 2
        self.ram = max(self.RAM_MIN, min(self.RAM_MAX, ram))
        try:
            default_ram = int(self._saved("default_ram", 2) or 2)
        except (TypeError, ValueError):
            default_ram = 2
        self.default_ram = max(self.RAM_MIN, min(self.RAM_MAX, default_ram))
        # Chosen on the first-run screen, inherited by every new profile.
        defaults = self._saved("default_game_options", None)
        self.default_game_options = (normalize_defaults(defaults)
                                     if isinstance(defaults, dict) else None)
        theme = str(self._saved("theme", "mint") or "mint").strip().lower()
        self.theme = theme if theme in self.THEMES else "mint"
        mode = str(self._saved("color_mode", "dark") or "dark").strip().lower()
        self.color_mode = mode if mode in ("dark", "light") else "dark"
        language = str(self._saved("language", "en") or "en").strip().lower()
        self.language = language if language in ("en", "ru") else "en"
        # Nexi site used by the "Nexi" account method. Only the address is a
        # preference; the account token lives in accounts.json.
        nexi = self._saved("nexi", {})
        if not isinstance(nexi, dict):
            nexi = {}
        self.nexi_base_url = str(nexi.get("base_url")
                                 or NEXI_BASE_URL_DEFAULT).strip().rstrip("/")
        self._nexi_pending = None
        # Companion shown in the top bar; purely cosmetic.
        pet = str(self._saved("pet", "axi") or "axi").strip().lower()
        self.pet = pet if pet in self.PETS else "axi"
        # First-run setup is shown until the user finishes or skips it.
        self._onboarded = bool(self._saved("onboarded", False))
        self.java_path = str(self._saved("java", "") or "")
        config.JAVA_OVERRIDE = self.java_path
        # Home background: {"file", "name", "kind"} or {} for the panorama.
        background = self._saved("background", {})
        self._background = background if isinstance(background, dict) else {}
        # DPI bypass: only the folder and preset name, never any credentials.
        zapret = self._saved("zapret", {})
        if not isinstance(zapret, dict):
            zapret = {}
        self._zapret = zapret
        self._zapret_path = str(zapret.get("path", "") or "")
        self._zapret_preset = str(zapret.get("preset", "") or "")
        self._zapret_auto = zapret.get("auto") is True
        # Mirror policy: "auto" falls back to BMCLAPI when a host is blocked,
        # "always" skips the official host, "never" keeps it for the bypass.
        mirror = str(self._saved("mirror", "auto") or "auto").strip().lower()
        self.mirror = mirror if mirror in MIRROR_MODES else "auto"
        set_mirror_mode(self.mirror)
        # Proxy and custom DNS for the launcher's own connections only.
        try:
            self.proxy = normalize_proxy(self._saved("proxy", ""))
        except ValueError:
            self.proxy = ""
        set_proxy(self.proxy)
        self.dns = set_dns(self._saved("dns", ""))
        ms = self._saved("ms", {})
        if not isinstance(ms, dict):
            ms = {}
        self._ms_client_id = str(ms.get("client_id", "") or "").strip()
        # Account tokens and the Ely.by client secret live in accounts.json,
        # never in settings.json — that file is safe to copy or share.
        stored = self._read_accounts_file()
        self._accounts = self._load_accounts(ms, stored)
        stored_cf = (stored or {}).get("curseforge")
        stored_cf = stored_cf if isinstance(stored_cf, dict) else {}
        self._curseforge_key = str(stored_cf.get("api_key", "") or "").strip()
        curseforge.set_api_key(self._curseforge_key)
        ids = {account["id"] for account in self._accounts}
        saved_active = str((stored or {}).get("active_account")
                           or self._saved("active_account", "") or "")
        self._active_account_id = saved_active if saved_active in ids \
            else (self._accounts[0]["id"] if self._accounts else "")
        active_account = self._active_account()
        if active_account is not None and active_account["type"] == "offline":
            self.player = active_account["name"]
        self._ms_device_stop = threading.Event()
        self._ms_device_thread = None
        ely = self._saved("ely", {})
        if not isinstance(ely, dict):
            ely = {}
        oauth = ely.get("oauth")
        if not isinstance(oauth, dict):
            oauth = {}
        self._ely_oauth_client_id = str(oauth.get("client_id", "") or "")
        stored_ely = (stored or {}).get("ely")
        stored_ely = stored_ely if isinstance(stored_ely, dict) else {}
        self._ely_oauth_secret = str(stored_ely.get("client_secret", "")
                                     or oauth.get("client_secret", "") or "")
        self._ely_oauth_redirect = str(
            oauth.get("redirect_uri", "") or ELY_OAUTH_REDIRECT_DEFAULT)
        self._ely_oauth_stop = threading.Event()
        self._ely_oauth_thread = None
        # Attributes starting with "_" are skipped by pywebview when it builds
        # the JS bridge, so internal queues/events never get exposed.
        self._events = queue.Queue()
        # The first automatic mirror fallback shows the two-option prompt.
        set_mirror_notifier(self._mirror_fallback_event)
        self._log_queue = queue.Queue()
        self.busy = ""
        self._cancel_event = None
        self._lock = threading.RLock()
        self._launching = set()
        self._game_processes = {}
        self._game_stop_requested = set()
        self._game_lock = threading.RLock()
        self._log_path = None
        self._log_pos = 0
        self._game_log_path = None
        self._game_log_pos = 0
        if stored is None or self._settings_has_secrets():
            # First run of this layout, or an older settings.json still holds
            # tokens: write them to accounts.json and scrub the settings file.
            self._save_accounts()
            self._save()
            self._scrub_legacy_settings()
        self.refresh_instances(select=self.selected_slug)
        self._install_trace()
        log.info("api ready: player=%r ram=%s default_ram=%s java=%r "
                 "instance=%r profiles=%d accounts=%d active=%r",
                 self.player, self.ram, self.default_ram,
                 self.java_path or "(auto)", self.selected_slug,
                 len(self.instances), len(self._accounts),
                 self._account_label())

    def _install_trace(self):
        """Log every bridged call: if the UI hangs, the log shows the culprit."""
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if name.startswith("_") or name in {
                    "poll", "log_js", "ely_login", "set_ely_oauth",
                    "nexi_login", "nexi_verify", "nexi_handle_link",
                    "nexi_link_start", "nexi_link_account",
                    "set_proxy", "set_curseforge_key",
                    "logs_open", "logs_read", "network_log"}:
                # ely_login/nexi_login receive a password and set_ely_oauth a
                # secret; never write any of them to the log. nexi_verify takes
                # the e-mail code; the nexi_link* calls carry a short-lived
                # one-time link token. logs_read/network_log are polled every
                # second: tracing them would grow launcher.log forever with
                # their own entries (the log panel tails the file, so it would
                # scroll non-stop).
                continue
            setattr(self, name, self._make_traced(name, func))

    def _make_traced(self, name, func):
        def wrapper(*args, **kwargs):
            shown = ", ".join(repr(arg) for arg in args)
            if len(shown) > 200:
                shown = shown[:200] + "…"
            started = time.monotonic()
            log.debug("call %s(%s)", name, shown)
            try:
                result = func(self, *args, **kwargs)
            except Exception:
                log.exception("call %s failed after %.2fs", name,
                              time.monotonic() - started)
                raise
            log.debug("done %s in %.2fs", name, time.monotonic() - started)
            return result
        return wrapper

    def log_js(self, message):
        """Diagnostics and uncaught JS errors forwarded by the page."""
        log.warning("page: %s", str(message)[:4000])
        return {"ok": True}

    def _event(self, kind, **payload):
        payload["t"] = kind
        # The page drains a few hundred events every 160 ms; a small cap keeps
        # a stalled page from ballooning memory with queued game log lines.
        if self._events.qsize() < 4000:
            self._events.put(payload)

    def _mirror_fallback_event(self, host, mirror=""):
        """Ask the page to offer a permanent mirror-or-bypass choice."""
        self._event("mirror", host=str(host), mirror=str(mirror))

    def _status(self, screen, text, error=False):
        self._event("status", screen=screen, text=str(text), error=bool(error))

    def _log(self, channel, line):
        self._event("log", channel=channel, line=str(line))

    def _progress(self, done, total):
        self._event("progress", value=int(done), total=int(total))

    def _stream_log(self, channel):
        def log(text):
            self._log(channel, text)
        return log

    def _saved(self, key, default):
        for path in (Path(self._settings_path()), app_dir() / "settings.json"):
            data = _read_json(path)
            if not isinstance(data, dict):
                continue
            return data.get(key, default)
        return default

    @staticmethod
    def _settings_path():
        return DATA_DIR / "settings.json"

    @staticmethod
    def _accounts_path():
        return DATA_DIR / "accounts.json"

    def _read_accounts_file(self):
        """The token store: accounts and the Ely.by client secret."""
        data = _read_json(self._accounts_path())
        return data if isinstance(data, dict) else None

    def _save_accounts(self):
        """Write tokens to accounts.json, away from settings.json."""
        data = {
            "accounts": [
                {key: value for key, value in account.items()
                 if not key.startswith("_")}
                for account in self._accounts],
            "active_account": self._active_account_id,
            "ely": {"client_secret": self._ely_oauth_secret},
            "curseforge": {"api_key": self._curseforge_key},
        }
        try:
            path = Path(self._accounts_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _settings_has_secrets(self):
        """True while any settings.json still carries account tokens."""
        found = False
        for path in (Path(self._settings_path()), app_dir() / "settings.json"):
            data = _read_json(path)
            if not isinstance(data, dict):
                continue
            if data.get("accounts") or data.get("active_account"):
                found = True
            ely = data.get("ely") if isinstance(data.get("ely"), dict) else {}
            if any(ely.get(key) for key in (
                    "access_token", "client_token", "refresh_token", "profile")):
                found = True
            oauth = ely.get("oauth")
            if isinstance(oauth, dict) and oauth.get("client_secret"):
                found = True
            ms = data.get("ms") if isinstance(data.get("ms"), dict) else {}
            if any(ms.get(key) for key in (
                    "refresh_token", "access_token", "profile", "xuid")):
                found = True
        return found

    def _scrub_legacy_settings(self):
        """Remove tokens from an old settings.json left next to the exe."""
        path = app_dir() / "settings.json"
        if path.resolve() == Path(self._settings_path()).resolve():
            return
        data = _read_json(path)
        if not isinstance(data, dict):
            return
        changed = False
        for key in ("accounts", "active_account"):
            if key in data:
                data.pop(key)
                changed = True
        ms = data.get("ms")
        if isinstance(ms, dict):
            for key in ("refresh_token", "access_token", "profile", "xuid"):
                if key in ms:
                    ms.pop(key)
                    changed = True
        ely = data.get("ely")
        if isinstance(ely, dict):
            for key in ("access_token", "client_token", "refresh_token",
                        "profile"):
                if key in ely:
                    ely.pop(key)
                    changed = True
            oauth = ely.get("oauth")
            if isinstance(oauth, dict) and "client_secret" in oauth:
                oauth.pop("client_secret")
                changed = True
        if changed:
            try:
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except OSError:
                pass

    @staticmethod
    def _normalize_account(item):
        if not isinstance(item, dict):
            return None
        kind = str(item.get("type", "") or "")
        if kind not in ("microsoft", "ely", "offline", "nexi"):
            return None
        name = str(item.get("name", "") or "").strip()[:16]
        account = {
            "id": str(item.get("id", "") or uuid.uuid4().hex),
            "type": kind,
            "name": name or "Player",
            "uuid": str(item.get("uuid", "") or ""),
        }
        if kind == "microsoft":
            account["refresh_token"] = str(
                item.get("refresh_token", "") or "")
            account["xuid"] = str(item.get("xuid", "") or "")
        elif kind == "ely":
            account["access_token"] = str(
                item.get("access_token", "") or "")
            account["client_token"] = str(
                item.get("client_token", "") or "")
            account["refresh_token"] = str(
                item.get("refresh_token", "") or "")
            account["kind"] = str(item.get("kind", "") or "")
        elif kind == "nexi":
            # Nexi site account: the signed token, the public profile and the
            # Minecraft identity linked to it on the site.
            account["token"] = str(item.get("token", "") or "")
            account["nexi_id"] = str(item.get("nexi_id", "") or "")
            account["account_name"] = str(
                item.get("account_name", "") or "")
            account["username"] = str(item.get("username", "") or "")
            account["email"] = str(item.get("email", "") or "")
            mc = item.get("mc")
            mc = mc if isinstance(mc, dict) else {}
            account["mc"] = {
                "type": str(mc.get("type") or "offline").strip().lower(),
                "label": str(mc.get("label") or ""),
                "name": str(mc.get("name") or "")[:16],
                "uuid": str(mc.get("uuid") or "").lower(),
                "custom": bool(mc.get("custom")),
                "linked_at": mc.get("linked_at") or None,
            }
        variant = str(item.get("skin_variant", "") or "")
        if variant in ("classic", "slim"):
            account["skin_variant"] = variant
        return account

    def _load_accounts(self, legacy_ms, stored=None):
        """Load the account list (accounts.json first, then old settings)."""
        raw = None
        if isinstance(stored, dict):
            raw = stored.get("accounts")
        if not isinstance(raw, list):
            raw = self._saved("accounts", None)
        if isinstance(raw, list):
            accounts = []
            for item in raw:
                account = self._normalize_account(item)
                if account is not None:
                    accounts.append(account)
            return accounts
        accounts = []
        profile = legacy_ms.get("profile")
        profile = profile if isinstance(profile, dict) else {}
        if profile.get("id") and legacy_ms.get("refresh_token"):
            accounts.append({
                "id": uuid.uuid4().hex, "type": "microsoft",
                "name": str(profile.get("name", "") or ""),
                "uuid": str(profile.get("id", "") or ""),
                "refresh_token": str(legacy_ms.get("refresh_token", "") or ""),
                "xuid": str(legacy_ms.get("xuid", "") or "")})
        ely = self._saved("ely", {})
        if not isinstance(ely, dict):
            ely = {}
        ely_profile = ely.get("profile")
        ely_profile = ely_profile if isinstance(ely_profile, dict) else {}
        if ely_profile.get("id") and ely.get("access_token"):
            accounts.append({
                "id": uuid.uuid4().hex, "type": "ely",
                "name": str(ely_profile.get("name", "") or ""),
                "uuid": str(ely_profile.get("id", "") or ""),
                "access_token": str(ely.get("access_token", "") or ""),
                "client_token": str(ely.get("client_token", "") or ""),
                "refresh_token": str(ely.get("refresh_token", "") or ""),
                "kind": str(ely.get("kind", "") or "")})
        if not accounts:
            accounts.append({"id": uuid.uuid4().hex, "type": "offline",
                             "name": self.player, "uuid": ""})
        return accounts

    def _account_by_id(self, account_id):
        account_id = str(account_id or "")
        for account in self._accounts:
            if account["id"] == account_id:
                return account
        return None

    def _active_account(self):
        return self._account_by_id(self._active_account_id)

    def _account_for_profile(self, kind, profile_id):
        profile_id = str(profile_id or "")
        for account in self._accounts:
            if account["type"] == kind and account["uuid"] == profile_id:
                return account
        return None

    def _account_public(self, account):
        public = {
            "id": account["id"],
            "type": account["type"],
            "name": account["name"],
            "uuid": account.get("uuid", ""),
            "active": account["id"] == self._active_account_id,
            "signed_in": account["type"] == "offline" or (
                account["type"] == "nexi" and bool(account.get("token")))
            or bool(account.get("uuid")
                    and (account.get("refresh_token")
                         or account.get("access_token"))),
        }
        if account["type"] == "nexi":
            handle_name = (account.get("username") or account.get("nexi_id")
                           or account.get("account_name") or "")
            public["nexi_id"] = str(account.get("nexi_id", "") or "")
            public["handle"] = f"@{handle_name}" if handle_name else ""
            public["mc"] = dict(account.get("mc") or {})
        return public

    def _account_label(self):
        account = self._active_account()
        if account is None:
            return "offline"
        return f'{account["name"]} ({account["type"]})'

    def _upsert_account(self, account):
        """Store an account and make it active; returns the stored entry."""
        if account.get("type") == "nexi":
            # Two site accounts can share a Minecraft UUID (both may use the
            # same offline nickname), so match them by their Nexi ID.
            existing = next(
                (item for item in self._accounts
                 if item.get("type") == "nexi"
                 and item.get("nexi_id") == account.get("nexi_id")), None)
        else:
            existing = self._account_for_profile(
                account["type"], account.get("uuid", ""))
        if existing is not None:
            existing.update(account)
            stored = existing
        else:
            if not account.get("id"):
                account["id"] = uuid.uuid4().hex
            self._accounts.append(account)
            stored = account
        self._active_account_id = stored["id"]
        return stored

    def _save(self):
        # settings.json keeps preferences only; account tokens and the Ely.by
        # client secret go to accounts.json (_save_accounts).
        data = {"player": self.player, "ram": int(self.ram),
                "default_ram": int(self.default_ram),
                "theme": self.theme,
                "color_mode": self.color_mode,
                "language": self.language,
                "pet": self.pet,
                "onboarded": bool(self._onboarded),
                "java": self.java_path,
                "instance": self.selected_slug,
                "instance_order": self.instance_order,
                "background": self._background,
                "mirror": self.mirror,
                "proxy": self.proxy,
                "dns": self.dns,
                "zapret": {"path": self._zapret_path,
                           "preset": self._zapret_preset,
                           "auto": bool(self._zapret_auto)},
                "ms": {"client_id": self._ms_client_id},
                "nexi": {"base_url": self.nexi_base_url},
                "ely": {"oauth": {
                    "client_id": self._ely_oauth_client_id,
                    "redirect_uri": self._ely_oauth_redirect}}}
        if isinstance(self.default_game_options, dict):
            data["default_game_options"] = normalize_defaults(
                self.default_game_options)
        try:
            Path(self._settings_path()).write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass
        self._save_accounts()

    def on_close(self):
        self._save()

    def set_default_ram(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.default_ram
        self.default_ram = max(self.RAM_MIN, min(self.RAM_MAX, value))
        self._save()
        return {"state": self.state()}

    def set_theme(self, theme):
        theme = str(theme or "").strip().lower()
        if theme not in self.THEMES:
            return {"ok": False, "error": "Unknown theme.",
                    "state": self.state()}
        with self._lock:
            self.theme = theme
            self._save()
        log.info("Theme: %s", theme)
        return {"ok": True, "state": self.state()}

    def set_color_mode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in ("dark", "light"):
            return {"ok": False, "error": "Unknown colour mode.",
                    "state": self.state()}
        with self._lock:
            self.color_mode = mode
            self._save()
        log.info("Colour mode: %s", mode)
        return {"ok": True, "state": self.state()}

    def set_language(self, language):
        language = str(language or "").strip().lower()
        if language not in ("en", "ru"):
            return {"ok": False, "error": "Unknown language.",
                    "state": self.state()}
        with self._lock:
            self.language = language
            self._save()
        log.info("Language: %s", language)
        return {"ok": True, "state": self.state()}

    def set_pet(self, pet):
        pet = str(pet or "").strip().lower()
        if pet not in self.PETS:
            return {"ok": False, "error": "Unknown companion.",
                    "state": self.state()}
        with self._lock:
            self.pet = pet
            self._save()
        log.info("Companion: %s", pet)
        return {"ok": True, "state": self.state()}

    def complete_onboarding(self):
        """Remember that the first-run setup was finished (or skipped)."""
        with self._lock:
            self._onboarded = True
            self._save()
        log.info("First-run setup completed")
        return {"ok": True, "state": self.state()}

    def set_java(self, path):
        path = str(path or "").strip()
        if path:
            target = Path(path)
            if target.is_dir():
                names = ("javaw.exe", "java.exe") if os.name == "nt" \
                    else ("java",)
                found = next((target / "bin" / name for name in names
                              if (target / "bin" / name).is_file()), None)
                if found is not None:
                    target = found
                else:
                    return {"ok": False,
                            "error": f"No Java found inside {path}",
                            "state": self.state()}
            if not target.is_file():
                return {"ok": False, "error": f"Java not found at {path}",
                        "state": self.state()}
            path = str(target)
        self.java_path = path
        config.JAVA_OVERRIDE = path
        self._save()
        return {"ok": True, "state": self.state()}

    def pick_java(self):
        """Native Windows file picker in its own STA process.

        pywebview dialogs must run on the GUI thread, while JS API calls run
        on worker threads, so the picker is opened through PowerShell instead.
        """
        if os.name != "nt":
            return {"ok": False,
                    "error": "Type the path to the Java executable."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = 'Select javaw.exe'; "
            "$d.Filter = 'Java executables (javaw.exe;java.exe)|"
            "javaw.exe;java.exe|All files (*.*)|*.*'; "
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
        return self.set_java(picked)

    def open_shared(self):
        try:
            MC.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False, "path": str(MC)}
        open_in_system(MC)
        return {"ok": True, "path": str(MC)}

    def poll(self):
        events = []
        while len(events) < 400:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        while len(events) < 400:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            events.append({"t": "game", "line": line})
        return {"events": events, "busy": self.busy,
                "launching": bool(self._launching)}
