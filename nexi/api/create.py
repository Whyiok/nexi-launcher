"""Creating, editing, importing and verifying profiles."""

import json
import os
import sqlite3
import tempfile
import threading
import zipfile
from pathlib import Path

from ..config import LOADER_LABELS
from ..game_options import normalize_defaults
from ..instances import (
    backup_instance_worlds, create_instance, delete_instance,
    download_profile_icon, duplicate_instance, instance_base_version,
    instance_game_dir, profile_loader_version, write_instance,
)
from ..java_runtime import ensure_java
from ..loaders import (
    console_java_for, find_loader_profile, install_fabric, install_loader,
    loader_builds, vanilla_versions,
)
from ..modpacks import (
    _curseforge_loader, _download_curseforge_manifest,
    _download_modpack_files, _extract_zip, _modpack_loader,
)
from ..util import InstallCancelled, _version_key, pick_file, pick_folder
from ..vanilla import (
    fetch_version_manifest, install_vanilla, manifest_entry,
    verify_version_files, version_installed,
)
from ..versions import detect_loader, load_version, version_meta


class CreateApi:
    def _inherit_setup(self, instance):
        """New profiles start with the options chosen at first launch."""
        defaults = getattr(self, "default_game_options", None)
        if isinstance(defaults, dict):
            instance["game_defaults"] = normalize_defaults(defaults)
            write_instance(instance["_root"], instance)

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
            self._inherit_setup(instance)
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
                message = (f"Checked {checked} files — fixed {fixed} "
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

    @staticmethod
    def _launcher_instance_roots():
        """Known default roots, plus paths explicitly set in launcher configs."""
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        local = Path(os.environ.get("LOCALAPPDATA", appdata))
        roots = {
            "Modrinth App": [appdata / "com.modrinth.theseus" / "profiles",
                             appdata / "ModrinthApp" / "profiles",
                             appdata / "Modrinth App" / "profiles",
                             local / "ModrinthApp" / "profiles"],
            "Prism Launcher": [appdata / "PrismLauncher" / "instances",
                               appdata / "Prism Launcher" / "instances",
                               local / "PrismLauncher" / "instances"],
        }
        config_paths = [appdata / "PrismLauncher" / "prismlauncher.cfg",
                        appdata / "Prism Launcher" / "prismlauncher.cfg",
                        local / "PrismLauncher" / "prismlauncher.cfg"]
        for config in config_paths:
            try:
                for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
                    key, sep, value = line.partition("=")
                    if not sep:
                        continue
                    setting = key.strip().lower()
                    raw_path = value.strip().strip('"')
                    if setting == "instancesshareddir":
                        if raw_path:
                            path = Path(raw_path)
                            if not path.is_absolute():
                                path = config.parent / path
                            roots["Prism Launcher"].append(path)
                    elif setting == "instancedir":
                        if raw_path:
                            path = Path(raw_path)
                            if not path.is_absolute():
                                path = config.parent / path
                            roots["Prism Launcher"].append(path)
            except OSError:
                pass
        found = []
        seen = set()
        for launcher, candidates in roots.items():
            for candidate in candidates:
                try:
                    resolved = candidate.resolve()
                except OSError:
                    resolved = candidate
                key = str(resolved).lower()
                if key not in seen and resolved.is_dir():
                    seen.add(key)
                    found.append((launcher, resolved))
        return found

    def discover_launcher_instances(self):
        """List local Modrinth App and Prism builds from their own registries."""
        result = []
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        local = Path(os.environ.get("LOCALAPPDATA", appdata))
        db_candidates = (appdata / "ModrinthApp" / "app.db",
                         appdata / "com.modrinth.theseus" / "app.db",
                         local / "ModrinthApp" / "app.db")
        database = next((path for path in db_candidates if path.is_file()), None)
        if database is not None:
            try:
                uri = database.as_uri() + "?mode=ro"
                with sqlite3.connect(uri, uri=True, timeout=3) as connection:
                    rows = connection.execute(
                        "SELECT i.path, i.name, cs.game_version, cs.loader, "
                        "cs.loader_version FROM instances i "
                        "LEFT JOIN instance_content_sets cs "
                        "ON cs.id=i.applied_content_set_id "
                        "WHERE i.install_stage='installed' "
                        "ORDER BY lower(i.name), i.id").fetchall()
                for raw_path, name, game, loader, loader_version in rows:
                    folder = Path(raw_path)
                    if not folder.is_absolute():
                        profiles_root = database.parent / "profiles"
                        folder = profiles_root / folder
                        if not folder.is_dir():
                            folder = database.parent / Path(raw_path)
                    if not folder.is_dir():
                        continue
                    loader_label = str(loader or "").strip().capitalize()
                    if loader_label == "Neoforge":
                        loader_label = "NeoForge"
                    if loader_label and loader_version:
                        loader_label += f" {loader_version}"
                    result.append({
                        "launcher": "Modrinth App", "source": "modrinth",
                        "name": str(name or folder.name),
                        "game": str(game or ""),
                        "loader": loader_label or "Vanilla",
                        "path": str(folder.resolve()),
                    })
            except (sqlite3.Error, OSError, ValueError) as exc:
                return {"ok": False,
                        "error": f"Could not read Modrinth App profiles: {exc}"}

        for launcher, root in self._launcher_instance_roots():
            if launcher != "Prism Launcher":
                continue
            try:
                children = sorted(root.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                continue
            for folder in children:
                if not folder.is_dir() or folder.is_symlink():
                    continue
                metadata = folder / "mmc-pack.json"
                if not metadata.is_file():
                    continue
                name, game, loader_label = folder.name, "", ""
                try:
                    pack = json.loads(metadata.read_text(encoding="utf-8"))
                    config = folder / "instance.cfg"
                    if config.is_file():
                        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
                            if line.startswith("name="):
                                name = line.split("=", 1)[1].strip() or name
                                break
                    for component in pack.get("components", []):
                        if not isinstance(component, dict):
                            continue
                        uid = str(component.get("uid") or "").lower()
                        version = str(component.get("version") or component.get("cachedVersion") or "")
                        if uid == "net.minecraft":
                            game = version
                        elif uid == "net.fabricmc.fabric-loader":
                            loader_label = f"Fabric {version}"
                        elif uid == "net.minecraftforge":
                            loader_label = f"Forge {version}"
                        elif uid == "net.neoforged.neoforge":
                            loader_label = f"NeoForge {version}"
                        elif uid == "org.quiltmc.quilt-loader":
                            loader_label = f"Quilt {version}"
                except (OSError, ValueError, TypeError):
                    continue
                result.append({"launcher": launcher, "source": "prism",
                               "name": name, "game": game,
                               "loader": loader_label or "Vanilla",
                               "path": str(folder.resolve())})
        return {"ok": True, "instances": result}

    def import_launcher_instance(self, path, source):
        """Import a chosen local instance listed by discover_launcher_instances."""
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        if source not in ("modrinth", "prism"):
            return {"ok": False, "error": "Unknown launcher source."}
        try:
            folder = Path(str(path or "")).resolve()
        except (OSError, ValueError):
            return {"ok": False, "error": "Could not validate the selected instance."}
        if source == "modrinth":
            appdata = Path(os.environ.get("APPDATA", Path.home()))
            databases = (appdata / "ModrinthApp" / "app.db",
                         appdata / "com.modrinth.theseus" / "app.db")
            for database in databases:
                if not database.is_file():
                    continue
                try:
                    with sqlite3.connect(database.as_uri() + "?mode=ro",
                                         uri=True, timeout=3) as connection:
                        row = connection.execute(
                            "SELECT i.path FROM instances i WHERE "
                            "i.path=? OR i.path=? OR i.path=? OR i.path=? LIMIT 1",
                            (folder.name, str(folder), str(folder.resolve()),
                             str(folder.relative_to(database.parent / "profiles"))
                             if folder.is_relative_to(database.parent / "profiles") else ""),
                        ).fetchone()
                    if row:
                        return self._import_launcher_instance_folder(folder, "modrinth")
                except sqlite3.Error:
                    continue
            return {"ok": False,
                    "error": "This Modrinth App instance is no longer registered."}
        allowed = {str(root / child.name).lower()
                   for launcher, root in self._launcher_instance_roots()
                   if launcher == "Prism Launcher"
                   for child in root.iterdir() if child.is_dir()}
        if str(folder).lower() not in allowed:
            return {"ok": False, "error": "This instance is not in the detected Prism folders."}
        return self._import_launcher_instance_folder(folder, "prism")

    def _import_launcher_instance_folder(self, root: Path, launcher: str):
        """Copy an installed Modrinth/Prism instance into a safe import archive."""
        root = Path(root)
        launcher = str(launcher or "").lower()
        name = root.name
        pack = None
        if launcher == "prism":
            metadata = root / "mmc-pack.json"
            if not metadata.is_file():
                return {"ok": False,
                        "error": "This folder is not a Prism instance (mmc-pack.json is missing)."}
            try:
                pack = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return {"ok": False, "error": f"Could not read Prism metadata: {exc}"}
            config = root / "instance.cfg"
            if config.is_file():
                try:
                    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("name="):
                            name = line.split("=", 1)[1].strip() or name
                            break
                except OSError:
                    pass
        elif launcher == "modrinth":
            metadata = next((path for path in (root / "profile.json",
                                               root / "instance.json",
                                               root / ".minecraft" / "profile.json",
                                               root / ".minecraft" / "instance.json")
                             if path.is_file()), None)
            if metadata is not None:
                try:
                    app_profile = json.loads(metadata.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    return {"ok": False, "error": f"Could not read Modrinth App metadata: {exc}"}
            else:
                app_profile = None
                appdata = Path(os.environ.get("APPDATA", Path.home()))
                for database in (appdata / "ModrinthApp" / "app.db",
                                 appdata / "com.modrinth.theseus" / "app.db"):
                    if not database.is_file():
                        continue
                    try:
                        with sqlite3.connect(database.as_uri() + "?mode=ro",
                                             uri=True, timeout=3) as connection:
                            row = connection.execute(
                                "SELECT i.name, cs.game_version, cs.loader, "
                                "cs.loader_version FROM instances i "
                                "LEFT JOIN instance_content_sets cs "
                                "ON cs.id=i.applied_content_set_id "
                        "WHERE i.path=? OR i.path=? OR i.path=? OR i.path=? LIMIT 1",
                                (root.name, str(root), str(root.resolve()),
                                 str(root.relative_to(database.parent / "profiles"))
                                 if root.is_relative_to(database.parent / "profiles")
                                 else "")).fetchone()
                        if row:
                            app_profile = {
                                "name": row[0],
                                "game": {"version": row[1],
                                         "modLoaders": ([{"id": row[2],
                                                          "version": row[3]}]
                                                        if row[2] else [])}}
                            break
                    except sqlite3.Error:
                        continue
                if app_profile is None:
                    return {"ok": False,
                            "error": "This folder is not a detected Modrinth App instance."}
            if not isinstance(app_profile, dict):
                return {"ok": False, "error": "The Modrinth App instance metadata is invalid."}
            try:
                game_data = app_profile.get("game") or {}
                if not isinstance(game_data, dict):
                    game_data = {}
                game = str(game_data.get("version")
                           or game_data.get("gameVersion")
                           or app_profile.get("gameVersion") or "").strip()
                loader_data = (game_data.get("modLoaders")
                               or game_data.get("loaders")
                               or game_data.get("loader") or [])
                if isinstance(loader_data, dict):
                    loader_data = [loader_data]
                loader_entry = next((item for item in loader_data
                                     if isinstance(item, dict)), {})
                loader_raw = str(loader_entry.get("id")
                                 or loader_entry.get("name")
                                 or loader_entry.get("type") or "").lower()
                loader_version = str(loader_entry.get("version") or "").strip()
                if not game:
                    app_version = app_profile.get("version") or {}
                    if isinstance(app_version, dict):
                        game = str(app_version.get("gameVersion")
                                   or app_version.get("minecraft") or "").strip()
                        loader_data = (app_version.get("modLoaders")
                                       or app_version.get("loaders")
                                       or app_version.get("loader") or [])
                        if isinstance(loader_data, dict):
                            loader_data = [loader_data]
                        loader_entry = next((item for item in loader_data
                                             if isinstance(item, dict)), {})
                        loader_raw = str(loader_entry.get("id")
                                         or loader_entry.get("name") or "").lower()
                        loader_version = str(loader_entry.get("version") or "").strip()
            except (TypeError, AttributeError):
                game, loader_raw, loader_version = "", "", ""
            name = str(app_profile.get("name") or app_profile.get("instanceName") or name)
            if not game:
                game = str(app_profile.get("gameVersion") or app_profile.get("game_version")
                           or app_profile.get("minecraftVersion") or app_profile.get("versionId")
                           or app_profile.get("mcVersion") or "").strip()
            if not loader_raw:
                loader_data = app_profile.get("loader") or app_profile.get("modLoader")
                if isinstance(loader_data, dict):
                    loader_raw = str(loader_data.get("id") or loader_data.get("name") or loader_data.get("type") or "").lower()
                    loader_version = str(loader_data.get("version") or loader_version).strip()
                else:
                    loader_raw = str(loader_data or app_profile.get("loaderType") or "").lower()
                    loader_version = str(app_profile.get("loaderVersion")
                                         or app_profile.get("loader_version") or loader_version).strip()
            aliases = {"fabric": "net.fabricmc.fabric-loader",
                       "forge": "net.minecraftforge",
                       "neoforge": "net.neoforged.neoforge",
                       "neo forge": "net.neoforged.neoforge",
                       "quilt": "org.quiltmc.quilt-loader"}
            components = []
            if game:
                components.append({"uid": "net.minecraft", "version": game})
            uid = aliases.get(loader_raw, "")
            if uid and loader_version:
                components.append({"uid": uid, "version": loader_version})
            # Some Modrinth App versions store the loader under a nested object.
            if not components:
                for key, value in app_profile.items():
                    if not isinstance(value, dict):
                        continue
                    nested_type = str(value.get("type") or key).lower()
                    nested_version = str(value.get("version") or "").strip()
                    if nested_type in aliases:
                        components.append({"uid": aliases[nested_type],
                                           "version": nested_version})
                    elif nested_type in ("minecraft", "net.minecraft"):
                        components.append({"uid": "net.minecraft",
                                           "version": nested_version})
            if not any(item.get("uid") == "net.minecraft" for item in components):
                # As a fallback, inspect version JSON files included in this instance.
                versions_dir = root / ".minecraft" / "versions"
                if versions_dir.is_dir():
                    for version_file in versions_dir.glob("*/*.json"):
                        try:
                            version_data = json.loads(version_file.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            continue
                        game = str(version_data.get("inheritsFrom") or "").strip()
                        if game:
                            components.append({"uid": "net.minecraft", "version": game})
                            break
            if not any(item.get("uid") == "net.minecraft" for item in components):
                return {"ok": False,
                        "error": "Could not determine the Minecraft version from this Modrinth App instance."}
            pack = {"components": components}
        else:
            return {"ok": False, "error": "Choose Modrinth App or Prism Launcher."}

        descriptor, archive_name = tempfile.mkstemp(
            prefix="nexi-launcher-import-", suffix=".zip")
        os.close(descriptor)
        archive_path = Path(archive_name)
        game_dir = root / ".minecraft"
        if not game_dir.is_dir():
            game_dir = root
        excluded = {"saves", "screenshots", "logs", "crash-reports",
                    "versions", "assets", "libraries", "backups",
                    "cache", "caches", "runtime", "runtimes"}
        metadata_files = {"profile.json", "instance.json", "mmc-pack.json",
                          "instance.cfg", "launcher_profiles.json"}
        try:
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("mmc-pack.json", json.dumps(pack))
                archive.writestr("instance.cfg", f"name={name}\n")
                if game_dir.is_dir() and not game_dir.is_symlink():
                    collected = 0
                    for file in game_dir.rglob("*"):
                        if not file.is_file() or file.is_symlink():
                            continue
                        relative = file.relative_to(game_dir)
                        if relative.parts and relative.parts[0].lower() in excluded:
                            continue
                        if len(relative.parts) == 1 and relative.name.lower() in metadata_files:
                            continue
                        try:
                            size = file.stat().st_size
                        except OSError:
                            continue
                        if size > 512 * 1024 * 1024:
                            continue
                        collected += size
                        if collected > 2 * 1024 * 1024 * 1024:
                            raise RuntimeError("Instance files exceed the 2 GB import limit.")
                        archive.write(file, ".minecraft/" + relative.as_posix())
            return self.import_modpack(str(archive_path))
        except (OSError, RuntimeError) as exc:
            return {"ok": False, "error": f"Could not read the selected instance: {exc}"}
        finally:
            archive_path.unlink(missing_ok=True)

    def pick_modrinth_instance(self):
        """Choose and copy an installed Modrinth App instance directory."""
        if os.name != "nt":
            return {"ok": False, "error": "Choose a Modrinth App instance folder."}
        try:
            appdata = Path(os.environ.get("APPDATA", ""))
            candidates = (
                appdata / "com.modrinth.theseus" / "profiles",
                appdata / "ModrinthApp" / "profiles",
                appdata / "Modrinth App" / "profiles",
            )
            initial = next((str(path) for path in candidates if path.is_dir()), "")
            picked = pick_folder("Select a Modrinth App instance", initial)
        except OSError as exc:
            return {"ok": False, "error": f"Could not open the folder picker: {exc}"}
        if not picked:
            return {"ok": False, "cancelled": True}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        return self._import_launcher_instance_folder(Path(picked), "modrinth")

    def pick_prism_instance(self):
        """Choose and copy a Prism Launcher instance directory."""
        if os.name != "nt":
            return {"ok": False, "error": "Choose a Prism instance folder."}
        try:
            picked = pick_folder("Select a Prism Launcher instance")
        except OSError as exc:
            return {"ok": False, "error": f"Could not open the folder picker: {exc}"}
        if not picked:
            return {"ok": False, "cancelled": True}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        return self._import_launcher_instance_folder(Path(picked), "prism")

    def pick_modpack(self):
        """Native file picker for a .mrpack or .zip modpack."""
        if os.name != "nt":
            return {"ok": False, "error": "Type the path to the modpack file."}
        try:
            picked = pick_file(
                "Select a modpack",
                (("Modpacks", "*.mrpack;*.zip"),
                 ("Modrinth packs", "*.mrpack"),
                 ("Zip archives", "*.zip"),
                 ("All files", "*.*")))
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not open the file picker: {exc}"}
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
            prism_pack = None
            prism_prefix = ""
            prism_candidates = sorted(
                (name for name in names
                 if name == "mmc-pack.json" or name.endswith("/mmc-pack.json")),
                key=lambda name: (name.count("/"), name))
            prism_index = prism_candidates[0] if prism_candidates else ""
            if prism_index:
                prism_prefix = prism_index[:-len("mmc-pack.json")]
                try:
                    prism_pack = json.loads(
                        archive.read(prism_index).decode("utf-8"))
                except (OSError, ValueError, KeyError) as exc:
                    return {"ok": False,
                            "error": f"The Prism pack is damaged: {exc}"}
            elif "modrinth.index.json" in names:
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
            base = ""
            if prism_pack is not None:
                components = prism_pack.get("components") or []
                for component in components:
                    if not isinstance(component, dict):
                        continue
                    uid = str(component.get("uid") or "").lower()
                    component_version = str(component.get("version")
                                            or component.get("cachedVersion")
                                            or component.get("instanceVersion")
                                            or "").strip()
                    if uid == "net.minecraft":
                        base = component_version
                    elif uid == "net.fabricmc.fabric-loader":
                        pack_loader, pack_loader_version = "fabric", component_version
                    elif uid == "net.minecraftforge":
                        pack_loader, pack_loader_version = "forge", component_version
                    elif uid == "net.neoforged.neoforge":
                        pack_loader, pack_loader_version = "neoforge", component_version
                    elif uid == "org.quiltmc.quilt-loader":
                        pack_loader, pack_loader_version = "quilt", component_version
                name = source.stem
                config_name = next((item for item in names
                                    if item == prism_prefix + "instance.cfg"), "")
                if config_name:
                    try:
                        for line in archive.read(config_name).decode(
                                "utf-8", "replace").splitlines():
                            if line.startswith("name="):
                                name = line.split("=", 1)[1].strip() or name
                                break
                    except (OSError, KeyError):
                        pass
            elif index is not None:
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
                self._inherit_setup(created)
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
                        if pack_loader == "fabric":
                            profile = install_fabric(
                                base, pack_loader_version, log,
                                progress=self._progress, cancel=cancel)
                        else:
                            profile = install_loader(
                                pack_loader, base, pack_loader_version, java,
                                log, progress=self._progress, cancel=cancel)
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
                elif prism_pack is not None:
                    prism_game_dir = prism_prefix + ".minecraft"
                    if any(name.startswith(prism_game_dir + "/")
                           for name in names):
                        extracted = _extract_zip(
                            archive, game_dir, prism_game_dir, log, cancel)
                    else:
                        extracted = _extract_zip(
                            archive, game_dir, prism_prefix, log, cancel,
                            strip_top=True)
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
