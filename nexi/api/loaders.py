"""Loader installation endpoint."""

import threading

from ..config import LOADER_LABELS
from ..instances import instance_base_version, write_instance
from ..java_runtime import ensure_java
from ..loaders import console_java_for, install_loader
from ..util import InstallCancelled
from ..vanilla import (
    fetch_version_manifest, install_vanilla, manifest_entry,
    version_installed,
)
from ..versions import load_version, version_meta


class LoadersApi:
    def loader_install(self, loader_key, loader_version):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        loader_key = str(loader_key or "")
        if loader_key not in LOADER_LABELS:
            return {"ok": False, "error": "Pick a loader first."}
        label = LOADER_LABELS[loader_key]
        base = instance_base_version(instance)
        if not base:
            return {"ok": False,
                    "error": "This profile has no base Minecraft version."}
        self.busy = "loaders"
        self._cancel_event = threading.Event()
        log = self._stream_log("loaders")
        self._event("busy", task="loaders", on=True)
        self._status("loaders",
                     f"Installing {label} {loader_version} for {base}…")
        try:
            if not version_installed(base):
                entry = manifest_entry(fetch_version_manifest(), base)
                if entry is None:
                    raise RuntimeError(
                        f"Minecraft {base} is not installed and Mojang's list "
                        f"has no entry for it")
                log(f"Downloading Minecraft {base} from Mojang…")
                self._status("loaders", f"Downloading Minecraft {base}…")
                install_vanilla(base, entry, log=log,
                                progress=self._progress,
                                cancel=self._cancel_event)
                log("Minecraft files are ready.")
            try:
                ensure_java(load_version(version_meta(base)), log,
                            self._progress, self._cancel_event)
            except InstallCancelled:
                raise
            except Exception as exc:
                log(f"WARNING: Java could not be prepared automatically: {exc}")
            java = console_java_for(base)
            log(f"Java: {java}")
            profile = install_loader(loader_key, base, loader_version, java, log,
                                     progress=self._progress,
                                     cancel=self._cancel_event)
            if not profile:
                raise RuntimeError(
                    "installer finished, but no new profile appeared")
            instance["version"] = profile
            write_instance(instance["_root"], instance)
            self.refresh_instances(select=instance["_slug"])
            message = (f'Installed {label} {loader_version} — this profile now '
                       f'runs "{profile}"')
            self._status("loaders", message)
            self._event("refresh", select=instance["_slug"])
            log(message)
            return {"ok": True, "message": message, "state": self.state()}
        except InstallCancelled:
            self._status("loaders", "Cancelled.")
            return {"ok": False, "cancelled": True, "error": "Cancelled"}
        except Exception as exc:
            message = f"Install failed: {exc}"
            self._status("loaders", message, error=True)
            log("ERROR: " + str(exc))
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._cancel_event = None
            self._event("busy", task="loaders", on=False)
            self._progress(0, 0)
