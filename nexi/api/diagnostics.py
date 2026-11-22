"""Log and network panels."""

import urllib.parse
from pathlib import Path

from .. import curseforge
from ..config import LOG_FILE, MAX_LOG_BACKLOG
from ..instances import instance_log_file
from ..logging_setup import log
from ..net import (
    MIRROR_MODES, NETWORK_LOG, _network_log_lock, mirror_mode, network_check,
    normalize_proxy, parse_dns_servers, reset_host_state,
    set_dns as apply_dns, set_mirror_mode, set_proxy as apply_proxy,
)
from ..util import open_in_system


class DiagnosticsApi:
    def game_logs_open(self):
        """Tail the selected profile's Minecraft log (logs/latest.log)."""
        instance = self.active_instance()
        self._game_log_path = None
        self._game_log_pos = 0
        if instance is None:
            return {"path": "", "text": "", "exists": False}
        path = instance_log_file(instance["_root"])
        self._game_log_path = path
        try:
            size = path.stat().st_size
        except OSError:
            return {"path": str(path), "text": "", "exists": False}
        start = max(0, size - MAX_LOG_BACKLOG)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return {"path": str(path), "text": "", "exists": False}
        self._game_log_pos = size
        text = data.decode("utf-8", "replace")
        if start:
            text = text.partition("\n")[2]
        return {"path": str(path), "text": text, "exists": True}

    def game_logs_read(self):
        if self._game_log_path is None:
            return {"text": ""}
        try:
            size = self._game_log_path.stat().st_size
        except OSError:
            return {"text": ""}
        reset = size < self._game_log_pos
        if reset:
            self._game_log_pos = 0
        if size == self._game_log_pos:
            return {"text": "", "reset": False}
        try:
            with self._game_log_path.open("rb") as handle:
                handle.seek(self._game_log_pos)
                data = handle.read()
        except OSError:
            return {"text": ""}
        self._game_log_pos = size
        return {"text": data.decode("utf-8", "replace"), "reset": reset}

    def logs_open(self):
        """Tail the launcher's own rotating log file."""
        path = Path(LOG_FILE)
        self._log_path = path
        self._log_pos = 0
        try:
            size = path.stat().st_size
        except OSError:
            return {"path": str(path), "text": "", "exists": False}
        start = max(0, size - MAX_LOG_BACKLOG)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return {"path": str(path), "text": "", "exists": False}
        self._log_pos = size
        text = data.decode("utf-8", "replace")
        if start:
            text = text.partition("\n")[2]
        return {"path": str(path), "text": text, "exists": True}

    def logs_read(self):
        if self._log_path is None:
            return {"text": ""}
        try:
            size = self._log_path.stat().st_size
        except OSError:
            return {"text": ""}
        reset = size < self._log_pos
        if reset:
            self._log_pos = 0
        if size == self._log_pos:
            return {"text": "", "reset": False}
        try:
            with self._log_path.open("rb") as handle:
                handle.seek(self._log_pos)
                data = handle.read()
        except OSError:
            return {"text": ""}
        self._log_pos = size
        return {"text": data.decode("utf-8", "replace"), "reset": reset}

    def network_log(self):
        """Events from http_get/downloads/Modrinth, in memory only."""
        with _network_log_lock:
            return {"events": list(NETWORK_LOG)}

    def network_clear(self):
        with _network_log_lock:
            NETWORK_LOG.clear()
        return {"ok": True}

    def network_check(self):
        """Probe every host the launcher uses and report what is broken."""
        try:
            return network_check()
        except Exception as exc:  # never let a probe kill the settings screen
            return {"results": [], "blocked": [], "error": str(exc)}

    def mirror_get(self):
        return {"ok": True, "mode": mirror_mode()}

    def mirror_set_mode(self, mode):
        """Persist the standing mirror choice: auto, always or never."""
        mode = str(mode or "").strip().lower()
        if mode not in MIRROR_MODES:
            return {"ok": False, "error": "Unknown mirror mode."}
        with self._lock:
            self.mirror = mode
            self._save()
        set_mirror_mode(mode)
        log.info("Mirror mode: %s", mode)
        return {"ok": True, "mode": mode, "state": self.state()}

    def set_proxy(self, value):
        """Route the launcher's connections through an HTTP/HTTPS proxy."""
        text = str(value or "").strip()
        if text.lower() in ("none", "off", "direct", "system"):
            text = ""
        try:
            proxy_url = normalize_proxy(text)
        except ValueError:
            return {"ok": False,
                    "error": "Enter a proxy as host:port or "
                             "http://host:port. Proxies that need a "
                             "password are not supported.",
                    "state": self.state()}
        with self._lock:
            self.proxy = proxy_url
            self._save()
        apply_proxy(proxy_url)
        reset_host_state()
        if proxy_url:
            parts = urllib.parse.urlsplit(proxy_url)
            log.info("Proxy: %s://%s:%s", parts.scheme,
                     parts.hostname or "", parts.port)
        else:
            log.info("Proxy: direct connection")
        return {"ok": True, "proxy": proxy_url, "state": self.state()}

    def set_dns(self, value):
        """Use custom DNS servers for the launcher's own name lookups."""
        text = str(value or "").strip()
        if text.lower() in ("auto", "system", "off", "none"):
            text = ""
        try:
            servers = parse_dns_servers(text)
        except ValueError:
            return {"ok": False,
                    "error": "DNS servers must be IP addresses, for "
                             "example 1.1.1.1, 8.8.8.8.",
                    "state": self.state()}
        if len(servers) > 3:
            return {"ok": False, "error": "Use up to three DNS servers.",
                    "state": self.state()}
        value = ", ".join(servers)
        with self._lock:
            self.dns = value
            self._save()
        apply_dns(value)
        reset_host_state()
        log.info("DNS servers: %s", value or "system")
        return {"ok": True, "dns": value, "state": self.state()}

    def set_curseforge_key(self, value):
        """Store a personal CurseForge API key in accounts.json."""
        text = str(value or "").strip()
        if len(text) > 200 or any(char.isspace() for char in text):
            return {"ok": False,
                    "error": "That does not look like a CurseForge API key.",
                    "state": self.state()}
        with self._lock:
            self._curseforge_key = text
            self._save_accounts()
        curseforge.set_api_key(text)
        log.info("CurseForge API key: %s", "saved" if text else "cleared")
        return {"ok": True, "set": bool(text), "state": self.state()}

    def curseforge_key_page(self):
        """Open the CurseForge console where personal API keys are created."""
        open_in_system(curseforge.CF_KEY_PAGE)
        return {"ok": True}
