"""zapret (DPI bypass) endpoints."""

import re
import threading
from pathlib import Path

from ..config import DATA_DIR
from ..logging_setup import log
from ..net import clear_failed_hosts, failed_hosts
from ..util import InstallCancelled, open_in_system, pick_folder
from ..zapret import (
    ZAPRET_DOMAINS, ZAPRET_SITE, detect_install, elevate_apply,
    find_missing, install_bundle, is_windows, merge_domains,
)


class ZapretApi:
    def _zapret_pin(self, root="", preset=""):
        """Remember the folder/preset; settings.json holds no secrets."""
        changed = False
        if root and str(root) != self._zapret_path:
            self._zapret_path = str(root)
            changed = True
        if preset and str(preset) != self._zapret_preset:
            self._zapret_preset = str(preset)
            changed = True
        if changed:
            with self._lock:
                self._save()

    def _zapret_read_status(self, root=""):
        status = detect_install(root or self._zapret_path)
        preset = self._zapret_preset
        # A Windows service starts the strategy stored in its registry key, so
        # that strategy is the truth while the service exists.
        if status.get("strategy") and status.get("service") in ("running",
                                                                "stopped"):
            preset = status.get("preset") or preset
        if preset and preset not in status.get("presets", []):
            preset = ""
        if not preset:
            preset = status.get("preset", "")
        status["preset"] = preset
        if status.get("root"):
            self._zapret_pin(root=status["root"], preset=preset)
        return status

    def zapret_status(self):
        try:
            status = self._zapret_read_status()
        except Exception as exc:  # never let detection break Settings
            return {"ok": False, "error": f"Could not inspect zapret: {exc}"}
        status["auto"] = bool(self._zapret_auto)
        failed = failed_hosts()
        # Hosts that failed to load and are not in the bypass list yet: the
        # card offers to add them and turn the bypass on.
        suggest = []
        if status.get("found") and status.get("list_path") and failed:
            try:
                suggest = find_missing(Path(status["list_path"]), failed)
            except OSError:
                suggest = []
        return {"ok": True, "status": status, "suggest": suggest,
                "failed": failed, "domains": list(ZAPRET_DOMAINS),
                "site": ZAPRET_SITE}

    def zapret_set_auto(self, value=True):
        enabled = value is True or str(value).strip().lower() in (
            "1", "true", "yes", "on")
        with self._lock:
            self._zapret_auto = enabled
            self._save()
        log.info("Zapret autostart: %s", enabled)
        return {"ok": True, "auto": enabled}

    def zapret_autostart(self):
        """Turn the bypass on after start-up when the user asked for it."""
        if not self._zapret_auto:
            return {"ok": True, "skipped": "disabled"}
        try:
            status = detect_install(self._zapret_path)
            if not status.get("found") or not status.get("root"):
                log.info("zapret autostart: not installed")
                return {"ok": True, "skipped": "missing"}
            if status.get("running") or status.get("service") == "running":
                log.info("zapret autostart: already running")
                return {"ok": True, "skipped": "running"}
            if self.busy:
                log.info("zapret autostart: launcher busy")
                return {"ok": True, "skipped": "busy"}
            log.info("zapret autostart: turning the bypass on")
            return self.zapret_apply(False)
        except Exception as exc:
            log.warning("zapret autostart failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def zapret_pick_folder(self):
        if not is_windows():
            return {"ok": False, "error": "Folder picking is Windows-only."}
        current = detect_install(self._zapret_path)
        initial = current.get("root") or self._zapret_path or ""
        try:
            picked = pick_folder("Select the zapret folder", initial)
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not open the folder picker: {exc}"}
        if not picked:
            return {"ok": False, "cancelled": True}
        checked = detect_install(picked, prefer_saved=True)
        try:
            same = (checked.get("root")
                    and Path(checked["root"]) == Path(picked).resolve())
        except OSError:
            same = False
        if not same:
            return {"ok": False,
                    "error": "That folder does not look like a zapret install "
                             "(winws.exe or the lists folder is missing)."}
        with self._lock:
            self._zapret_path = checked["root"]
            if checked.get("preset"):
                self._zapret_preset = checked["preset"]
            self._save()
        log.info("Zapret folder: %s", checked["root"])
        return {"ok": True, "status": checked}

    def zapret_set_preset(self, name):
        name = Path(str(name or "")).name
        status = detect_install(self._zapret_path)
        if name not in status.get("presets", []):
            return {"ok": False, "error": "Pick a preset from the list."}
        with self._lock:
            self._zapret_preset = name
            self._save()
        status["preset"] = name
        return {"ok": True, "status": status}

    def zapret_apply(self, download=False, extra=""):
        download = download is True or str(download).strip().lower() in (
            "1", "true", "yes")
        domains = list(ZAPRET_DOMAINS)
        # Hosts the launcher failed to reach (typed in by the UI) are added
        # alongside the fixed launcher list.
        for host in re.split(r"[\s,;]+", str(extra or "")):
            host = host.strip().lower().strip(".")
            if not host or "." not in host or "/" in host:
                continue
            if host not in domains:
                domains.append(host)
        if self.busy:
            return {"ok": False,
                    "error": "Another task is already running."}
        self.busy = "zapret"
        self._cancel_event = threading.Event()
        cancel = self._cancel_event
        log_stream = self._stream_log("zapret")
        self._event("busy", task="zapret", on=True)
        self._status("zapret", "Looking for zapret…")
        try:
            status = detect_install(self._zapret_path)
            if not status.get("found"):
                if not download:
                    return {"ok": False, "needs_download": True,
                            "error": "Zapret was not found."}
                self._status("zapret", "Downloading zapret…")
                log_stream("Downloading the latest zapret release from GitHub…")
                bundle = install_bundle(DATA_DIR / "zapret", log_stream,
                                        progress=self._progress, cancel=cancel)
                log_stream(f"zapret {bundle.get('version', '')} unpacked.")
                with self._lock:
                    self._zapret_path = bundle["root"]
                    self._save()
                status = detect_install(bundle["root"], prefer_saved=True)

            if not status.get("found") or not status.get("root"):
                raise RuntimeError("The zapret folder could not be located.")
            root = Path(status["root"])
            presets = status.get("presets") or []
            preset = self._zapret_preset or status.get("preset") or ""
            if preset not in presets:
                preset = status.get("preset") or ""
            if not preset and presets:
                preset = presets[0]

            list_path = Path(status["list_path"]) if status.get("list_path") \
                else root / "lists" / "list-general-user.txt"
            added = 0
            pending = None
            try:
                added, _total = merge_domains(list_path, domains)
                if added:
                    log_stream(f"Added {added} address(es) to "
                               f"{list_path.name}.")
                else:
                    log_stream(f"{list_path.name} already contains every "
                               "launcher address.")
            except OSError as exc:
                log_stream("Writing the list needs administrator rights "
                           f"({exc}); the elevated step will do it.")
                try:
                    pending = find_missing(list_path, domains)
                except OSError:
                    pending = list(domains)

            self._status("zapret", "Turning the bypass on…")
            log_stream("Applying the list and (re)starting the bypass — "
                       "confirm the Windows administrator prompt…")
            streamed = []

            def relay(line):
                streamed.append(line)
                log_stream(line)

            outcome = elevate_apply(root, preset,
                                    list_path if pending else None, pending,
                                    cancel=cancel, on_log=relay)
            for line in outcome.get("log") or []:
                if line not in streamed:
                    log_stream(line)
            if not outcome.get("ok"):
                message = outcome.get("error") or "Could not turn the bypass on."
                self._status("zapret", message, error=not outcome.get("cancelled"))
                return {"ok": False, "error": message,
                        "cancelled": bool(outcome.get("cancelled")),
                        "status": detect_install(self._zapret_path)}

            with self._lock:
                self._zapret_path = str(root)
                if preset:
                    self._zapret_preset = preset
                self._save()
            clear_failed_hosts()
            fresh = detect_install(str(root), prefer_saved=True)
            label = fresh.get("strategy") or preset or "enabled"
            message = f"Bypass is running ({label})"
            if added:
                message += f"; added {added} address(es)"
            message += "."
            self._status("zapret", message)
            log_stream(message)
            return {"ok": True, "message": message, "status": fresh,
                    "added": added}
        except InstallCancelled:
            self._status("zapret", "Cancelled.")
            return {"ok": False, "cancelled": True, "error": "Cancelled"}
        except Exception as exc:
            message = f"Could not configure zapret: {exc}"
            self._status("zapret", message, error=True)
            log_stream("ERROR: " + str(exc))
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._cancel_event = None
            self._event("busy", task="zapret", on=False)
            self._progress(0, 0)

    def zapret_stop(self):
        if self.busy:
            return {"ok": False,
                    "error": "Another task is already running."}
        self.busy = "zapret"
        log_stream = self._stream_log("zapret")
        self._event("busy", task="zapret", on=True)
        self._status("zapret", "Stopping the bypass…")
        try:
            status = detect_install(self._zapret_path)
            if not status.get("found") or not status.get("root"):
                return {"ok": False, "error": "Zapret was not found."}
            root = Path(status["root"])
            preset = self._zapret_preset or status.get("preset") or ""
            streamed = []

            def relay(line):
                streamed.append(line)
                log_stream(line)

            outcome = elevate_apply(root, preset, None, None, stop_only=True,
                                    on_log=relay)
            for line in outcome.get("log") or []:
                if line not in streamed:
                    log_stream(line)
            if not outcome.get("ok"):
                message = outcome.get("error") or "Could not stop the bypass."
                self._status("zapret", message, error=True)
                return {"ok": False, "error": message,
                        "status": detect_install(self._zapret_path)}
            fresh = detect_install(self._zapret_path)
            self._status("zapret", "Bypass stopped.")
            log_stream("Bypass stopped.")
            return {"ok": True, "message": "Bypass stopped.", "status": fresh}
        except Exception as exc:
            message = f"Could not stop zapret: {exc}"
            self._status("zapret", message, error=True)
            log_stream("ERROR: " + str(exc))
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._event("busy", task="zapret", on=False)
            self._progress(0, 0)

    def zapret_open(self, kind="folder"):
        kind = str(kind or "folder").strip().lower()
        if kind == "site":
            open_in_system(ZAPRET_SITE)
            return {"ok": True}
        status = detect_install(self._zapret_path)
        target = Path(status["root"]) if status.get("root") \
            else DATA_DIR / "zapret"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        open_in_system(target)
        return {"ok": True, "path": str(target)}
