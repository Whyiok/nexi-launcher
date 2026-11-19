"""Launcher update endpoints."""

import threading

from ..logging_setup import log
from ..update import (
    UpdateError, apply_update, can_replace_running_exe, check_latest,
    download_update, is_newer,
)
from ..util import InstallCancelled
from ..version import VERSION


class UpdateApi:
    def _update_prepare(self):
        """Release the busy flag and stop the progress bar after a task."""
        self.busy = ""
        self._cancel_event = None
        self._event("busy", task="update", on=False)
        self._progress(0, 0)

    def update_check(self):
        """Ask GitHub for the latest release; never starts a download."""
        try:
            info = check_latest(VERSION)
        except UpdateError as exc:
            log.warning("update check failed: %s", exc)
            return {"ok": False, "error": f"Could not check for updates: {exc}"}
        except Exception as exc:
            log.exception("update check failed")
            return {"ok": False, "error": f"Could not check for updates: {exc}"}
        if info.get("available"):
            message = f"Nexi Launcher {info['latest']} is available."
        else:
            message = f"You are running the latest version ({VERSION})."
        log.info("update check: current=%s latest=%s available=%s", VERSION,
                 info.get("latest"), info.get("available"))
        return {"ok": True, **info, "message": message}

    def update_install(self):
        """Download and apply the newest release, then restart the launcher."""
        if self.busy:
            return {"ok": False,
                    "error": "Another task is already running."}
        ok, reason = can_replace_running_exe()
        if not ok:
            return {"ok": False, "error": reason}
        self.busy = "update"
        self._cancel_event = threading.Event()
        self._event("busy", task="update", on=True)
        self._status("update", "Checking for updates…")
        try:
            info = check_latest(VERSION)
            if not info.get("available"):
                self._status("update", f"You are running the latest version "
                                      f"({VERSION}).")
                return {"ok": True, "up_to_date": True,
                        "version": VERSION}
            version = str(info.get("latest") or "")
            if not is_newer(version, VERSION):
                return {"ok": True, "up_to_date": True,
                        "version": VERSION}
            self._status("update", f"Downloading Nexi Launcher {version}…")
            log.info("update: downloading %s", version)

            def progress(done, total):
                self._progress(done, total)

            downloaded = download_update(
                info, on_progress=progress, cancel=self._cancel_event)
            if (self._cancel_event is not None
                    and self._cancel_event.is_set()):
                raise InstallCancelled()
            self._status("update",
                         "Update downloaded. The launcher will close and "
                         "restart.")
            apply_update(downloaded)
            return {"ok": True, "restarting": True, "version": version}
        except InstallCancelled:
            log.info("update: cancelled")
            self._status("update", "Update cancelled.")
            return {"ok": False, "cancelled": True}
        except UpdateError as exc:
            log.warning("update failed: %s", exc)
            self._status("update", f"Update failed: {exc}", error=True)
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("update failed")
            self._status("update", f"Update failed: {exc}", error=True)
            return {"ok": False, "error": str(exc)}
        finally:
            self._update_prepare()
