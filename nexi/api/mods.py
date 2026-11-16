"""Modrinth mod install / update / uninstall actions."""

from ..instances import (
    installed_mod_entry, instance_base_version, instance_mods_dir,
    mod_state_entry, read_mods_state, write_mods_state,
)
from ..modrinth import (
    mod_versions, primary_file, required_dependencies, resolve_dependency,
    search_modrinth,
)
from ..net import download_file
from ..util import safe_filename
from ..versions import detect_loader, load_version, version_meta


class ModsApi:
    def _instance_game(self):
        instance = self.active_instance()
        if instance is None:
            return None, "", "any"
        try:
            game = instance_base_version(instance)
        except Exception:
            game = str(instance.get("version", ""))
        try:
            detected = detect_loader(
                load_version(version_meta(str(instance.get("version", "")))))
        except Exception:
            detected = "any"
        return instance, game, detected

    def mods_search(self, query, loader):
        instance, game, _detected = self._instance_game()
        if instance is None:
            return {"hits": [], "error": "No profile selected."}
        loader = str(loader or "any")
        try:
            hits, total = search_modrinth(str(query or ""), game, loader)
        except Exception as exc:
            return {"hits": [], "game": game, "loader": loader, "total": 0,
                    "error": f"Search failed: {exc}"}
        return {
            "hits": [{
                "project_id": hit.get("project_id", ""),
                "slug": hit.get("slug", ""),
                "title": hit.get("title", "mod"),
                "downloads": hit.get("downloads", 0),
                "author": hit.get("author") or "",
                "description": hit.get("description", ""),
                "icon_url": hit.get("icon_url") or "",
            } for hit in hits],
            "game": game, "loader": loader, "total": total, "error": "",
        }

    def mods_install(self, project_id, loader, slug=None, game_version=None):
        instance, profile_game, detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if detected == "any":
            return {"ok": False,
                    "error": ("This profile has no mod loader — install "
                              "Fabric, Forge or NeoForge first.")}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "mods"
        self._event("busy", task="mods", on=True)
        loader = str(loader or "any")
        game = str(game_version or "") or profile_game
        root = instance["_root"]
        mods_dir = instance_mods_dir(root)
        where = f"Minecraft {game}" if game else "this version"
        try:
            versions = mod_versions(str(project_id), game, loader)
            if not versions:
                suffix = "" if loader == "any" else f" ({loader})"
                return {"ok": False, "error": f"No files for {where}{suffix}."}
            state = read_mods_state(root)
            pending = [versions[0]]
            handled = set()
            installed = []
            while pending and len(handled) < 25:
                version = pending.pop(0)
                project = version.get("project_id") or project_id
                if project in handled:
                    continue
                handled.add(project)
                file = primary_file(version)
                if file is None:
                    continue
                target = mods_dir / safe_filename(
                    file.get("filename", "mod.jar"))
                if target.is_file():
                    installed.append(f"{target.name} (already in mods)")
                else:
                    self._status("mods", f"Downloading {target.name}…")
                    self._event("busy", task="mods", on=True,
                                label=f"Downloading {target.name}")
                    mods_dir.mkdir(parents=True, exist_ok=True)
                    download_file(file["url"], target)
                    installed.append(target.name)
                state[str(project)] = mod_state_entry(
                    version, file, project,
                    slug=slug if str(project) == str(project_id) else "")
                for dep in required_dependencies(version):
                    dep_version = resolve_dependency(dep, game, loader)
                    if dep_version is not None:
                        pending.append(dep_version)
            if state:
                write_mods_state(root, state)
            if installed:
                message = "Installed: " + ", ".join(installed)
                self._status("mods", message)
                return {"ok": True, "message": message}
            return {"ok": False,
                    "error": "No downloadable files found for this mod."}
        except Exception as exc:
            message = f"Install failed: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._event("busy", task="mods", on=False)

    def mods_status(self, project_id, slug=None):
        instance = self.active_instance()
        if instance is None:
            return {"installed": False}
        entry = installed_mod_entry(instance["_root"], str(project_id or ""),
                                    str(slug or ""))
        return {
            "installed": bool(entry),
            "filename": str(entry.get("filename") or ""),
            "version_id": str(entry.get("version_id") or ""),
            "version_number": str(entry.get("version_number") or ""),
        }

    def mods_uninstall(self, project_id, filename=None):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        root = instance["_root"]
        mods_dir = instance_mods_dir(root)
        state = read_mods_state(root)
        project = str(project_id or "")
        entry = state.get(project)
        entry = entry if isinstance(entry, dict) else {}
        target_name = str(entry.get("filename") or filename or "")
        target = mods_dir / safe_filename(target_name) if target_name else None
        if target is None:
            return {"ok": False,
                    "error": "This mod is not installed in this profile."}
        try:
            if target.is_file():
                target.unlink()
        except OSError as exc:
            message = f"Could not delete {target.name}: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        for pid, value in list(state.items()):
            if (pid == project or (isinstance(value, dict)
                                   and value.get("filename") == target.name)):
                state.pop(pid, None)
        write_mods_state(root, state)
        message = f"Removed {target.name}."
        self._status("mods", message)
        return {"ok": True, "message": message}

    def mods_update(self, project_id, loader, slug=None, game_version=None):
        instance, profile_game, detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if detected == "any":
            return {"ok": False,
                    "error": ("This profile has no mod loader — install "
                              "Fabric, Forge or NeoForge first.")}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "mods"
        self._event("busy", task="mods", on=True)
        loader = str(loader or "any")
        game = str(game_version or "") or profile_game
        root = instance["_root"]
        mods_dir = instance_mods_dir(root)
        project = str(project_id or "")
        where = f"Minecraft {game}" if game else "this version"
        try:
            entry = installed_mod_entry(root, project, str(slug or ""))
            if not entry:
                return {"ok": False,
                        "error": "This mod is not installed in this profile."}
            versions = mod_versions(project, game, loader)
            if not versions:
                suffix = "" if loader == "any" else f" ({loader})"
                return {"ok": False, "error": f"No files for {where}{suffix}."}
            latest = versions[0]
            file = primary_file(latest)
            if file is None:
                return {"ok": False,
                        "error": "This mod has no downloadable file."}
            name = entry.get("title") or "This mod"
            same = (str(entry.get("version_id") or "")
                    == str(latest.get("id") or ""))
            if same and (mods_dir / safe_filename(entry["filename"])).is_file():
                message = f"{name} is already up to date."
                self._status("mods", message)
                return {"ok": True, "unchanged": True, "message": message}
            target = mods_dir / safe_filename(file.get("filename", "mod.jar"))
            self._status("mods", f"Downloading {target.name}…")
            self._event("busy", task="mods", on=True,
                        label=f"Downloading {target.name}")
            mods_dir.mkdir(parents=True, exist_ok=True)
            download_file(file["url"], target)
            old_name = safe_filename(entry.get("filename") or "")
            if old_name and old_name != target.name:
                try:
                    (mods_dir / old_name).unlink()
                except OSError:
                    pass
            state = read_mods_state(root)
            state[project] = mod_state_entry(
                latest, file, project,
                slug=str(slug or entry.get("slug") or ""),
                title=str(entry.get("title") or ""))
            write_mods_state(root, state)
            version = (latest.get("version_number")
                       or latest.get("name") or target.name)
            message = f"Updated to {version}."
            self._status("mods", message)
            return {"ok": True, "message": message}
        except Exception as exc:
            message = f"Update failed: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._event("busy", task="mods", on=False)

    def mods_update_all(self, loader):
        instance, game, _detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        loader = str(loader or "any")
        root = instance["_root"]
        mods_dir = instance_mods_dir(root)
        state = read_mods_state(root)
        tracked = []
        for project, entry in state.items():
            if not isinstance(entry, dict) or not entry.get("filename"):
                continue
            if (mods_dir / safe_filename(entry["filename"])).is_file():
                tracked.append((project, entry))
        if not tracked:
            return {"ok": False,
                    "error": "No tracked mods in this profile yet — install "
                             "a mod from Modrinth first."}
        self.busy = "mods"
        self._event("busy", task="mods", on=True)
        updated, skipped, failed = [], [], []
        try:
            for position, (project, entry) in enumerate(tracked, 1):
                name = str(entry.get("title") or entry.get("filename"))
                self._status(
                    "mods", f"Checking {name} ({position}/{len(tracked)})…")
                try:
                    versions = mod_versions(project, game, loader)
                    if not versions:
                        failed.append(f"{name}: no files for this version")
                        continue
                    latest = versions[0]
                    file = primary_file(latest)
                    if file is None:
                        failed.append(f"{name}: no downloadable file")
                        continue
                    old_name = safe_filename(entry.get("filename") or "")
                    same = (str(entry.get("version_id") or "")
                            == str(latest.get("id") or ""))
                    if same and (mods_dir / old_name).is_file():
                        skipped.append(name)
                        continue
                    target = mods_dir / safe_filename(
                        file.get("filename", "mod.jar"))
                    self._status("mods", f"Downloading {target.name}…")
                    self._event("busy", task="mods", on=True,
                                label=f"Downloading {target.name}")
                    mods_dir.mkdir(parents=True, exist_ok=True)
                    download_file(file["url"], target)
                    if old_name and old_name != target.name:
                        try:
                            (mods_dir / old_name).unlink()
                        except OSError:
                            pass
                    state[project] = mod_state_entry(
                        latest, file, project,
                        slug=str(entry.get("slug") or ""),
                        title=str(entry.get("title") or ""))
                    updated.append(name)
                except Exception as exc:
                    failed.append(f"{name}: {exc}")
            write_mods_state(root, state)
            parts = [f"Updated {len(updated)} mod(s)"]
            if skipped:
                parts.append(f"{len(skipped)} already up to date")
            if failed:
                parts.append(f"{len(failed)} failed")
            message = " — ".join(parts) + "."
            if failed:
                message += " " + "; ".join(failed[:3])
            self._status("mods", message, error=bool(failed))
            return {"ok": True, "message": message, "updated": len(updated),
                    "skipped": len(skipped), "failed": len(failed)}
        finally:
            self.busy = ""
            self._event("busy", task="mods", on=False)
