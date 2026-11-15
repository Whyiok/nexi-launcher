"""Log and network panels."""

from pathlib import Path

from ..config import LOG_FILE, MAX_LOG_BACKLOG
from ..instances import instance_log_file
from ..net import NETWORK_LOG, _network_log_lock, network_check


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
