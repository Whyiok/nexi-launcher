"""Content browser actions (mods, packs, shaders, worlds)."""

import logging
import tempfile
from pathlib import Path

from ..instances import (
    PACK_DIRS, PACK_LABELS, installed_mod_entry, installed_pack_entry,
    instance_pack_dir, mod_state_entry, read_packs_state, write_packs_state,
)
from ..modrinth import (
    mod_versions, modrinth_get, primary_file, search_modrinth,
)
from ..net import download_file
from ..util import safe_filename


class ContentApi:
    @staticmethod
    def _content_kind(kind):
        kind = str(kind or "mod")
        return kind if kind in ("mod", "resourcepack", "shader",
                                "modpack") else "mod"

    def content_search(self, kind, query="", loader="any", offset=0,
                       game_version=None):
        kind = self._content_kind(kind)
        try:
            offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            offset = 0
        game = ""
        if game_version is None:
            # Legacy callers: derive the filters from the selected profile.
            if kind != "modpack":
                instance, game, detected = self._instance_game()
                if instance is None:
                    return {"hits": [], "game": "", "loader": str(loader or "any"),
                            "total": 0, "offset": offset,
                            "error": "No profile selected."}
                if kind == "mod" and detected == "any":
                    return {"hits": [], "game": game,
                            "loader": str(loader or "any"), "kind": kind,
                            "total": 0, "offset": offset,
                            "error": ("This profile has no mod loader — install "
                                      "Fabric, Forge or NeoForge first.")}
        else:
            # The browser passes explicit filters; "" means no version filter.
            game = str(game_version or "")
            if kind != "modpack" and self.active_instance() is None:
                return {"hits": [], "game": game, "loader": str(loader or "any"),
                        "total": 0, "offset": offset,
                        "error": "No profile selected."}
        loader = str(loader or "any")
        try:
            hits, total = search_modrinth(str(query or ""), game, loader, kind,
                                          offset=offset)
        except Exception as exc:
            return {"hits": [], "game": game, "loader": loader,
                    "total": 0, "offset": offset,
                    "error": f"Search failed: {exc}"}
        return {
            "hits": [{
                "project_id": hit.get("project_id", ""),
                "slug": hit.get("slug", ""),
                "title": hit.get("title", kind),
                "downloads": hit.get("downloads", 0),
                "author": hit.get("author") or "",
                "description": hit.get("description", ""),
                "icon_url": hit.get("icon_url") or "",
            } for hit in hits],
            "game": game, "loader": loader, "kind": kind, "total": total,
            "offset": offset, "error": "",
        }

    def content_status(self, kind, project_id, loader="any", slug=None):
        kind = self._content_kind(kind)
        instance = self.active_instance()
        if instance is None:
            return {"installed": False}
        root = instance["_root"]
        project = str(project_id or "")
        if kind == "mod":
            entry = installed_mod_entry(root, project, str(slug or ""))
        elif kind in PACK_DIRS:
            entry = installed_pack_entry(root, kind, project, str(slug or ""))
        else:
            entry = {}
        return {
            "installed": bool(entry),
            "filename": str(entry.get("filename") or ""),
            "version_id": str(entry.get("version_id") or ""),
            "version_number": str(entry.get("version_number") or ""),
        }

    def content_install(self, kind, project_id, loader="any", slug=None,
                        game_version=None):
        kind = self._content_kind(kind)
        if kind == "mod":
            return self.mods_install(project_id, loader, slug, game_version)
        if kind == "modpack":
            return self.modpack_install(project_id, slug)
        return self.pack_install(kind, project_id, loader, slug, game_version)

    def content_uninstall(self, kind, project_id, filename=None):
        kind = self._content_kind(kind)
        if kind == "mod":
            return self.mods_uninstall(project_id, filename)
        if kind in PACK_DIRS:
            return self.pack_uninstall(kind, project_id, filename)
        return {"ok": False,
                "error": "Modpacks are profiles — remove the profile instead."}

    def content_update(self, kind, project_id, loader="any", slug=None,
                       game_version=None):
        kind = self._content_kind(kind)
        if kind == "mod":
            return self.mods_update(project_id, loader, slug, game_version)
        if kind in PACK_DIRS:
            return self.pack_update(kind, project_id, loader, slug,
                                    game_version)
        return {"ok": False, "error": "Modpacks are installed as profiles."}

    def pack_install(self, kind, project_id, loader="any", slug=None,
                     game_version=None):
        instance, profile_game, _detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if kind not in PACK_DIRS:
            return {"ok": False, "error": "Unknown pack type."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "packs"
        self._event("busy", task="packs", on=True)
        loader = str(loader or "any")
        game = str(game_version or "") or profile_game
        root = instance["_root"]
        folder = instance_pack_dir(root, kind)
        project = str(project_id or "")
        label = PACK_LABELS.get(kind, "pack")
        where = f"Minecraft {game}" if game else "this version"
        try:
            versions = mod_versions(project, game, loader, kind)
            if not versions:
                return {"ok": False,
                        "error": f"No {label} files for {where}."}
            version = versions[0]
            file = primary_file(version)
            if file is None:
                return {"ok": False,
                        "error": f"This {label} has no downloadable file."}
            target = folder / safe_filename(
                file.get("filename") or "pack.zip")
            if target.is_file():
                message = f"{target.name} is already installed."
            else:
                self._status("mods", f"Downloading {target.name}…")
                self._event("busy", task="packs", on=True,
                            label=f"Downloading {target.name}")
                folder.mkdir(parents=True, exist_ok=True)
                download_file(file["url"], target)
                message = f"Installed {target.name}."
            state = read_packs_state(root)
            bucket = state.get(kind)
            if not isinstance(bucket, dict):
                bucket = {}
            bucket[project] = mod_state_entry(
                version, file, project, slug=str(slug or ""))
            state[kind] = bucket
            write_packs_state(root, state)
            self._status("mods", message)
            return {"ok": True, "message": message}
        except Exception as exc:
            message = f"Install failed: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._event("busy", task="packs", on=False)

    def pack_uninstall(self, kind, project_id, filename=None):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if kind not in PACK_DIRS:
            return {"ok": False, "error": "Unknown pack type."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        root = instance["_root"]
        folder = instance_pack_dir(root, kind)
        state = read_packs_state(root)
        bucket = state.get(kind)
        bucket = bucket if isinstance(bucket, dict) else {}
        project = str(project_id or "")
        entry = bucket.get(project)
        entry = entry if isinstance(entry, dict) else {}
        target_name = str(entry.get("filename") or filename or "")
        target = folder / safe_filename(target_name) if target_name else None
        if target is None:
            return {"ok": False,
                    "error": "This pack is not installed in this profile."}
        try:
            if target.is_file():
                target.unlink()
        except OSError as exc:
            message = f"Could not delete {target.name}: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        for pid, value in list(bucket.items()):
            if (pid == project or (isinstance(value, dict)
                                   and value.get("filename") == target.name)):
                bucket.pop(pid, None)
        state[kind] = bucket
        write_packs_state(root, state)
        message = f"Removed {target.name}."
        self._status("mods", message)
        return {"ok": True, "message": message}

    def pack_update(self, kind, project_id, loader="any", slug=None,
                    game_version=None):
        instance, profile_game, _detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if kind not in PACK_DIRS:
            return {"ok": False, "error": "Unknown pack type."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "packs"
        self._event("busy", task="packs", on=True)
        loader = str(loader or "any")
        game = str(game_version or "") or profile_game
        root = instance["_root"]
        folder = instance_pack_dir(root, kind)
        project = str(project_id or "")
        label = PACK_LABELS.get(kind, "pack")
        where = f"Minecraft {game}" if game else "this version"
        try:
            entry = installed_pack_entry(root, kind, project, str(slug or ""))
            if not entry:
                return {"ok": False,
                        "error": f"This {label} is not installed in this profile."}
            versions = mod_versions(project, game, loader, kind)
            if not versions:
                return {"ok": False,
                        "error": f"No {label} files for {where}."}
            latest = versions[0]
            file = primary_file(latest)
            if file is None:
                return {"ok": False,
                        "error": f"This {label} has no downloadable file."}
            old_name = safe_filename(entry.get("filename") or "")
            same = (str(entry.get("version_id") or "")
                    == str(latest.get("id") or ""))
            if same and old_name and (folder / old_name).is_file():
                message = f"{old_name} is already up to date."
                self._status("mods", message)
                return {"ok": True, "unchanged": True, "message": message}
            target = folder / safe_filename(
                file.get("filename") or "pack.zip")
            self._status("mods", f"Downloading {target.name}…")
            self._event("busy", task="packs", on=True,
                        label=f"Downloading {target.name}")
            folder.mkdir(parents=True, exist_ok=True)
            download_file(file["url"], target)
            if old_name and old_name != target.name:
                try:
                    (folder / old_name).unlink()
                except OSError:
                    pass
            state = read_packs_state(root)
            bucket = state.get(kind)
            if not isinstance(bucket, dict):
                bucket = {}
            bucket[project] = mod_state_entry(
                latest, file, project,
                slug=str(slug or entry.get("slug") or ""),
                title=str(entry.get("title") or ""))
            state[kind] = bucket
            write_packs_state(root, state)
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
            self._event("busy", task="packs", on=False)

    def modpack_install(self, project_id, slug=None):
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "modpack"
        self._event("busy", task="modpack", on=True)
        project = str(project_id or "")
        try:
            versions = mod_versions(project, "", "", "modpack")
            if not versions:
                return {"ok": False,
                        "error": "No downloadable modpack versions found."}
            version = versions[0]
            file = primary_file(version)
            if file is None:
                return {"ok": False,
                        "error": "This modpack has no downloadable file."}
            if not str(file.get("filename", "")).lower().endswith(".mrpack"):
                candidates = [item for item in version.get("files") or []
                              if str(item.get("filename", "")).lower()
                              .endswith(".mrpack")]
                if candidates:
                    file = candidates[0]
            name = safe_filename(file.get("filename") or "modpack.mrpack")
            # The .mrpack has no artwork; the project page has the icon.
            icon_url = ""
            try:
                project_info = modrinth_get(f"/project/{project}", timeout=10)
                if isinstance(project_info, dict):
                    icon_url = str(project_info.get("icon_url") or "")
            except Exception as exc:
                logging.debug("Modpack icon lookup failed: %s", exc)
            self._status("mods", f"Downloading {name}…")
            self._event("busy", task="modpack", on=True,
                        label=f"Downloading {name}")
            with tempfile.TemporaryDirectory(prefix="launcher-pack-") as tmp:
                target = Path(tmp) / name
                download_file(file["url"], target)
                self.busy = ""
                self._event("busy", task="modpack", on=False)
                return self.import_modpack(str(target), icon_url=icon_url)
        except Exception as exc:
            message = f"Could not install the modpack: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._event("busy", task="modpack", on=False)
