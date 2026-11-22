"""Creating, editing, importing and verifying profiles."""

import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path

from ..config import LOADER_LABELS
from ..instances import (
    backup_instance_worlds, create_instance, delete_instance,
    download_profile_icon, duplicate_instance, instance_base_version,
    instance_game_dir, profile_loader_version, write_instance,
)
from ..java_runtime import ensure_java
from ..loaders import (
    console_java_for, find_loader_profile, install_loader, loader_builds,
    vanilla_versions,
)
from ..modpacks import (
    _curseforge_loader, _download_curseforge_manifest,
    _download_modpack_files, _extract_zip, _modpack_loader,
)
from ..util import InstallCancelled, _version_key
from ..vanilla import (
    fetch_version_manifest, install_vanilla, manifest_entry,
    verify_version_files, version_installed,
)
from ..versions import detect_loader, load_version, version_meta


class CreateApi:
    def versions(self, force=False):
        try:
            manifest = fetch_version_manifest(force=bool(force))
            error = ""
        except Exception as exc:
            manifest, error = [], str(exc)
        installed = sorted(vanilla_versions(), key=_version_key, reverse=True)
        entries = []
        seen = set()
        for entry in manifest:
            version_id = entry.get("id")
            if not version_id or version_id in seen:
                continue
            seen.add(version_id)
            entries.append({"id": version_id,
                            "type": entry.get("type", "release")})
        for version_id in installed:
            if version_id not in seen:
                entries.append({"id": version_id, "type": "installed"})
        return {"versions": entries, "installed": installed, "error": error}

    def builds(self, loader_key, game_version):
        notes = []
        try:
            pairs = loader_builds(str(loader_key), str(game_version),
                                  notes.append)
        except Exception as exc:
            return {"builds": [], "error": str(exc), "note": ""}
        return {"builds": [{"version": value, "label": label}
                           for value, label in pairs], "error": "",
                "note": notes[-1] if notes else ""}

    def create(self, name, version_id, loader_key=None, loader_version=None):
        version_id = str(version_id or "").strip()
        if not version_id:
            return {"ok": False, "error": "Select a Minecraft version first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        name = str(name or "").strip() or version_id
        loader_key = loader_key or None
        label = LOADER_LABELS.get(loader_key, "")
        self.busy = "create"
        self._cancel_event = threading.Event()
        cancel = self._cancel_event
        log = self._stream_log("create")
        self._event("busy", task="create", on=True)
        self._status("create", f'Creating "{name}"…')
        log(f'Creating "{name}"…')
        try:
            if version_installed(version_id):
                log(f"Minecraft {version_id} is already installed.")
            else:
                entry = manifest_entry(fetch_version_manifest(), version_id)
                if entry is None:
                    raise RuntimeError(
                        f"Minecraft {version_id} is not installed and is not "
                        f"in Mojang's version list")
                log(f"Downloading Minecraft {version_id} from Mojang…")
                self._status("create", f"Downloading Minecraft {version_id}…")
                install_vanilla(version_id, entry, log=log,
                                progress=self._progress, cancel=cancel)
                log("Minecraft files are ready.")
            if cancel.is_set():
                raise InstallCancelled()
            try:
                java = ensure_java(load_version(version_meta(version_id)),
                                   log, self._progress, cancel)
                log(f"Java: {java}")
            except InstallCancelled:
                raise
            except Exception as exc:
                log(f"WARNING: Java could not be prepared automatically: {exc}")
            if cancel.is_set():
                raise InstallCancelled()
            instance = create_instance(name, version_id, ram=self.default_ram)
            log(f'Created profile "{instance["name"]}" — {instance["_root"]}')
            if not loader_key:
                message = f'Created "{instance["name"]}".'
                self.refresh_instances(select=instance["_slug"])
                self._event("refresh", select=instance["_slug"])
                return {"ok": True, "message": message,
                        "instance": self._summary(instance)}
            self._status("create", f"Installing {label} {loader_version}…")
            try:
                java = console_java_for(version_id)
                log(f"Java: {java}")
                profile = install_loader(loader_key, version_id,
                                         loader_version, java, log,
                                         progress=self._progress,
                                         cancel=cancel)
            except Exception as exc:
                message = (f'Profile "{instance["name"]}" was created, but '
                           f'the loader did not install: {exc}. You can add '
                           f'it later from Loaders.')
                self._status("create", message, error=True)
                log("ERROR: " + str(exc))
                self.refresh_instances(select=instance["_slug"])
                self._event("refresh", select=instance["_slug"])
                return {"ok": True, "partial": True, "message": message,
                        "instance": self._summary(instance)}
            if not profile:
                message = (f'Profile "{instance["name"]}" was created, but '
                           f'{label} {loader_version} produced no new profile. '
                           f'You can retry from Loaders.')
                self._status("create", message, error=True)
                log("ERROR: no new profile appeared")
                self.refresh_instances(select=instance["_slug"])
                self._event("refresh", select=instance["_slug"])
                return {"ok": True, "partial": True, "message": message,
                        "instance": self._summary(instance)}
            instance["version"] = profile
            write_instance(instance["_root"], instance)
            message = (f'Created "{instance["name"]}" with '
                       f'{label} {loader_version}.')
            self._status("create", message)
            log(message)
            self.refresh_instances(select=instance["_slug"])
            self._event("refresh", select=instance["_slug"])
            return {"ok": True, "message": message,
                    "instance": self._summary(instance)}
        except InstallCancelled:
            self._status("create", "Cancelled — no profile was created.")
            log("Cancelled.")
            self._event("refresh")
            return {"ok": False, "cancelled": True, "error": "Cancelled"}
        except Exception as exc:
            message = f"Could not install Minecraft {version_id}: {exc}"
            self._status("create", message, error=True)
            log("ERROR: " + message)
            self._event("refresh")
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._cancel_event = None
            self._event("busy", task="create", on=False)
            self._progress(0, 0)

    def cancel(self):
        if self.busy and self._cancel_event is not None:
            self._cancel_event.set()
            return {"ok": True}
        return {"ok": False}

    def update_instance(self, name, version_id, loader_key=None,
                        loader_version=None):
        """Change an existing profile's name, game version or loader."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        if self._instance_running(instance["_slug"]):
            return {"ok": False, "error": "Close the game before editing the profile."}
        version_id = str(version_id or "").strip()
        if not version_id:
            return {"ok": False, "error": "Select a Minecraft version first."}
        name = str(name or "").strip() or str(instance.get("name") or version_id)
        loader_key = loader_key or None
        if loader_key is not None and loader_key not in LOADER_LABELS:
            return {"ok": False, "error": "Unknown mod loader."}
        loader_version = str(loader_version or "").strip()
        if loader_key and not loader_version:
            return {"ok": False, "error": "Pick a loader build."}

        current_version = str(instance.get("version") or "")
        try:
            current_base = instance_base_version(instance)
        except Exception:
            current_base = current_version
        try:
            current_loader = detect_loader(
                load_version(version_meta(current_version))) or "any"
        except Exception:
            current_loader = "any"
        current_build = profile_loader_version(
            current_version, current_loader, current_base)
        unchanged = (version_id == current_base
                     and (loader_key or "any") == current_loader
                     and (not loader_key
                          or loader_version.lower() == current_build.lower()))
        if unchanged:
            if name != instance.get("name"):
                instance["name"] = name
                write_instance(instance["_root"], instance)
                self.refresh_instances(select=instance["_slug"])
                self._save()
                self._event("refresh", select=instance["_slug"])
                message = f'Renamed to "{name}".'
                self._status("create", message)
                return {"ok": True, "message": message, "state": self.state()}
            message = "Profile settings are unchanged."
            self._status("create", message)
            return {"ok": True, "message": message, "state": self.state()}

        self.busy = "create"
        self._cancel_event = threading.Event()
        cancel = self._cancel_event
        log = self._stream_log("create")
        self._event("busy", task="create", on=True)
        self._status("create", f'Updating "{instance["name"]}"…')
        log(f'Updating "{instance["name"]}"…')
        try:
            if not version_installed(version_id):
                entry = manifest_entry(fetch_version_manifest(), version_id)
                if entry is None:
                    raise RuntimeError(
                        f"Minecraft {version_id} is not installed and is not "
                        f"in Mojang's version list")
                log(f"Downloading Minecraft {version_id} from Mojang…")
                self._status("create", f"Downloading Minecraft {version_id}…")
                install_vanilla(version_id, entry, log=log,
                                progress=self._progress, cancel=cancel)
                log("Minecraft files are ready.")
            if cancel.is_set():
                raise InstallCancelled()
            try:
                ensure_java(load_version(version_meta(version_id)),
                            log, self._progress, cancel)
            except InstallCancelled:
                raise
            except Exception as exc:
                log(f"WARNING: Java could not be prepared automatically: {exc}")
            if cancel.is_set():
                raise InstallCancelled()

            version = version_id
            label = ""
            if loader_key:
                label = LOADER_LABELS[loader_key]
                self._status("create", f"Installing {label} {loader_version}…")
                profile = find_loader_profile(loader_key, version_id,
                                              loader_version)
                if profile:
                    log(f"Reusing existing {label} profile {profile}")
                else:
                    java = console_java_for(version_id)
                    log(f"Java: {java}")
                    profile = install_loader(loader_key, version_id,
                                             loader_version, java, log,
                                             progress=self._progress,
                                             cancel=cancel)
                if not profile:
                    raise RuntimeError(
                        "installer finished, but no new profile appeared")
                version = profile

            instance["name"] = name
            instance["version"] = version
            write_instance(instance["_root"], instance)
            self.refresh_instances(select=instance["_slug"])
            self._save()
            self._event("refresh", select=instance["_slug"])
            if loader_key:
                message = (f'"{name}" now runs Minecraft {version_id} with '
                           f'{label} {loader_version}.')
            else:
                message = f'"{name}" now runs Minecraft {version_id}.'
            self._status("create", message)
            log(message)
            return {"ok": True, "message": message, "state": self.state()}
        except InstallCancelled:
            message = "Cancelled — the profile was not changed."
            self._status("create", message, error=True)
            log("Cancelled.")
            return {"ok": False, "cancelled": True, "error": message}
        except Exception as exc:
            message = f"Could not update the profile: {exc}"
            self._status("create", message, error=True)
            log("ERROR: " + message)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._cancel_event = None
            self._event("busy", task="create", on=False)
            self._progress(0, 0)

    def duplicate_profile(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        try:
            copy = duplicate_instance(instance["_root"])
        except Exception as exc:
            message = f"Could not duplicate the profile: {exc}"
            self._status("profiles", message, error=True)
            return {"ok": False, "error": message}
        self.refresh_instances(select=copy["_slug"])
        self._save()
        message = (f'Duplicated "{instance["name"]}" as "{copy["name"]}" — '
                   f"worlds and logs were not copied.")
        self._status("profiles", message)
        return {"ok": True, "message": message, "state": self.state()}

    def verify_files(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        if self._instance_running(instance["_slug"]):
            return {"ok": False, "error": "Close the game before verifying files."}
        version = str(instance.get("version") or "")
        self.busy = "verify"
        self._cancel_event = threading.Event()
        log = self._stream_log("create")
        self._event("busy", task="verify", on=True)
        self._status("profiles", f'Checking files for "{instance["name"]}"…')
        try:
            result = verify_version_files(version, log, self._progress,
                                          self._cancel_event)
            checked, fixed = result["checked"], result["fixed"]
            if fixed:
                message = (f"Checked {checked} files — re-downloaded {fixed} "
                           f"missing or damaged file(s).")
            else:
                message = f"Checked {checked} files — everything is intact."
            self._status("profiles", message, error=bool(fixed))
            log(message)
            return {"ok": True, "message": message}
        except InstallCancelled:
            message = "Verification cancelled."
            self._status("profiles", message)
            return {"ok": False, "cancelled": True, "error": message}
        except Exception as exc:
            message = f"Could not verify the files: {exc}"
            self._status("profiles", message, error=True)
            log("ERROR: " + message)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._cancel_event = None
            self._event("busy", task="verify", on=False)
            self._progress(0, 0)

    def backup_worlds(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        if self._instance_running(instance["_slug"]):
            return {"ok": False,
                    "error": "Close the game before backing up its worlds."}
        try:
            result = backup_instance_worlds(instance["_root"])
        except Exception as exc:
            message = str(exc) or "Could not back up the worlds."
            self._status("profiles", message, error=True)
            return {"ok": False, "error": message}
        message = (f'Backed up {result["worlds"]} world(s) to '
                   f'backups/{result["path"].name} '
                   f'({result["files"]} file(s)).')
        self._status("profiles", message)
        return {"ok": True, "message": message}

    def pick_modpack(self):
        """Native file picker for a .mrpack or .zip modpack."""
        if os.name != "nt":
            return {"ok": False, "error": "Type the path to the modpack file."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = 'Select a modpack'; "
            "$d.Filter = 'Modpacks (*.mrpack;*.zip)|*.mrpack;*.zip|"
            "Modrinth packs (*.mrpack)|*.mrpack|Zip archives (*.zip)|*.zip|"
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
        picked = (result.stdout or "").strip()
        if not picked:
            return {"ok": False, "cancelled": True}
        return {"ok": True, "path": picked}

    def import_modpack(self, path, version_id=None, loader_key=None,
                       loader_version=None, icon_url=None):
        """Create a profile from a Modrinth .mrpack or a zipped pack."""
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        source = Path(str(path or "").strip().strip('"'))
        if not source.is_file():
            return {"ok": False, "error": "The selected archive was not found."}
        if source.suffix.lower() not in (".mrpack", ".zip"):
            return {"ok": False, "error": "Pick a .mrpack or .zip file."}
        try:
            archive = zipfile.ZipFile(source)
        except (OSError, zipfile.BadZipFile) as exc:
            return {"ok": False, "error": f"Could not open the archive: {exc}"}

        with archive:
            names = {name.replace("\\", "/") for name in archive.namelist()}
            index = None
            manifest = None
            if "modrinth.index.json" in names:
                try:
                    index = json.loads(
                        archive.read("modrinth.index.json").decode("utf-8"))
                except (OSError, ValueError, KeyError) as exc:
                    return {"ok": False,
                            "error": f"The Modrinth pack is damaged: {exc}"}
            elif "manifest.json" in names:
                try:
                    manifest = json.loads(
                        archive.read("manifest.json").decode("utf-8"))
                except (OSError, ValueError, KeyError):
                    manifest = None
            if not isinstance(index, dict):
                index = None
            if not isinstance(manifest, dict):
                manifest = None

            pack_loader = ""
            pack_loader_version = ""
            if index is not None:
                dependencies = index.get("dependencies") or {}
                base = str(dependencies.get("minecraft") or "").strip()
                pack_loader, pack_loader_version = _modpack_loader(dependencies)
                name = str(index.get("name") or source.stem)
            elif manifest is not None:
                minecraft = manifest.get("minecraft") or {}
                base = str(minecraft.get("version") or "").strip()
                pack_loader, pack_loader_version = _curseforge_loader(manifest)
                name = str(manifest.get("name") or source.stem)
            else:
                base = str(version_id or "").strip()
                pack_loader = str(loader_key or "")
                pack_loader_version = str(loader_version or "")
                name = source.stem

            if not base:
                return {"ok": False,
                        "error": "This archive has no pack metadata — pick a "
                                 "Minecraft version on the New screen first, "
                                 "then import it again."}
            if pack_loader == "quilt":
                return {"ok": False,
                        "error": "Quilt modpacks are not supported yet."}
            if pack_loader and pack_loader not in LOADER_LABELS:
                return {"ok": False,
                        "error": f"Unknown mod loader in the pack: {pack_loader}"}
            if pack_loader and not pack_loader_version:
                return {"ok": False,
                        "error": "The pack does not name a loader build."}
            name = name.strip()[:48] or source.stem[:48] or "Modpack"

            self.busy = "import"
            self._cancel_event = threading.Event()
            cancel = self._cancel_event
            log = self._stream_log("create")
            self._event("busy", task="import", on=True)
            self._status("import", f'Importing "{name}"…')
            log(f'Importing "{name}" from {source.name}…')
            created = None
            try:
                if not version_installed(base):
                    entry = manifest_entry(fetch_version_manifest(), base)
                    if entry is None:
                        raise RuntimeError(
                            f"Minecraft {base} is not installed and is not "
                            f"in Mojang's version list")
                    log(f"Downloading Minecraft {base} from Mojang…")
                    self._status("import", f"Downloading Minecraft {base}…")
                    install_vanilla(base, entry, log=log,
                                    progress=self._progress, cancel=cancel)
                    log("Minecraft files are ready.")
                if cancel.is_set():
                    raise InstallCancelled()
                try:
                    ensure_java(load_version(version_meta(base)), log,
                                self._progress, cancel)
                except InstallCancelled:
                    raise
                except Exception as exc:
                    log(f"WARNING: Java could not be prepared: {exc}")

                created = create_instance(name, base, ram=self.default_ram)
                game_dir = instance_game_dir(created["_root"])
                log(f'Created profile "{created["name"]}" — {created["_root"]}')

                # A .mrpack carries no artwork; Modrinth serves the project
                # icon separately, so fetch it for the sidebar.
                icon_file = ""
                if icon_url:
                    icon_file = download_profile_icon(created["_root"], icon_url)
                    log("Profile icon saved." if icon_file
                        else "WARNING: the pack icon could not be downloaded.")

                version = base
                if pack_loader:
                    label = LOADER_LABELS[pack_loader]
                    self._status("import",
                                 f"Installing {label} {pack_loader_version}…")
                    profile = find_loader_profile(pack_loader, base,
                                                  pack_loader_version)
                    if profile:
                        log(f"Reusing existing {label} profile {profile}")
                    else:
                        java = console_java_for(base)
                        log(f"Java: {java}")
                        profile = install_loader(pack_loader, base,
                                                 pack_loader_version, java, log,
                                                 progress=self._progress,
                                                 cancel=cancel)
                    if not profile:
                        raise RuntimeError(
                            "installer finished, but no new profile appeared")
                    version = profile

                downloaded = 0
                if index is not None:
                    self._status("import", "Downloading modpack files…")
                    downloaded = _download_modpack_files(
                        index.get("files"), game_dir, log, self._progress,
                        cancel)
                elif manifest is not None and manifest.get("files"):
                    self._status("import", "Downloading CurseForge files…")
                    downloaded = _download_curseforge_manifest(
                        manifest.get("files"), game_dir, log, self._progress,
                        cancel)

                extracted = 0
                if index is not None:
                    for prefix in ("overrides", "client-overrides"):
                        extracted += _extract_zip(archive, game_dir, prefix,
                                                  log, cancel)
                elif manifest is not None:
                    prefixes = [str(manifest.get("overrides") or "overrides"),
                                "client-overrides"]
                    for prefix in prefixes:
                        extracted += _extract_zip(archive, game_dir, prefix,
                                                  log, cancel)
                else:
                    extracted = _extract_zip(archive, game_dir, "", log,
                                             cancel, strip_top=True)
                log(f"Modpack files: {downloaded} downloaded, "
                    f"{extracted} extracted.")

                created["version"] = version
                if icon_file:
                    created["icon"] = icon_file
                write_instance(created["_root"], created)
                self.refresh_instances(select=created["_slug"])
                self._save()
                self._event("refresh", select=created["_slug"])
                message = f'Imported "{created["name"]}" — Minecraft {base}'
                if pack_loader:
                    message += (f" with {LOADER_LABELS[pack_loader]} "
                                f"{pack_loader_version}")
                if downloaded or extracted:
                    message += (f" ({downloaded} file(s) downloaded, "
                                f"{extracted} extracted)")
                message += "."
                self._status("import", message)
                log(message)
                return {"ok": True, "message": message,
                        "state": self.state()}
            except InstallCancelled:
                if created is not None:
                    delete_instance(created["_root"])
                    self.refresh_instances(select="")
                message = "Import cancelled — the partial profile was removed."
                self._status("import", message, error=True)
                log(message)
                return {"ok": False, "cancelled": True, "error": message}
            except Exception as exc:
                if created is not None:
                    delete_instance(created["_root"])
                    self.refresh_instances(select="")
                message = f"Could not import the modpack: {exc}"
                self._status("import", message, error=True)
                log("ERROR: " + message)
                return {"ok": False, "error": message}
            finally:
                self.busy = ""
                self._cancel_event = None
                self._event("busy", task="import", on=False)
                self._progress(0, 0)
