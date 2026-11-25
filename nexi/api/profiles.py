"""Profiles: selection, state and per-build contents."""

import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

from ..config import ELY_SKIN_SITE, INSTANCES_DIR, LOG_DIR, LOG_FILE, MC
from ..ely_auth import ELY_OAUTH_CLIENT_ID_DEFAULT
from .. import media
from ..game_options import normalize_defaults, write_game_options
from ..logging_setup import log
from ..instances import (
    BANNER_SUFFIXES, BANNER_VIDEO_SUFFIXES, ICON_MAX_BYTES, ICON_SUFFIXES,
    IMAGE_SUFFIXES, _file_sha1, delete_instance, instance_contents,
    instance_game_dir, instance_log_file, instance_mods_dir, list_instances,
    profile_banner_path, profile_icon_data_url, profile_loader_version,
    read_instance, read_modrinth_cache, screenshot_entries, write_instance,
    write_modrinth_cache,
)
from ..modpacks import _zip_member_target
from ..modrinth import modrinth_get
from ..ms_auth import MS_CLIENT_ID_DEFAULT
from ..util import copy_image_to_clipboard, open_in_system, pick_file
from ..version import VERSION
from ..versions import (
    detect_loader, game_version_of, load_version, version_meta,
)


BANNER_MAX_BYTES = 20 * 1024 * 1024
BANNER_VIDEO_MAX_BYTES = 50 * 1024 * 1024


def _attach_shot_urls(entries):
    """Replace file-system paths with loopback preview URLs for the page."""
    for entry in entries:
        path = entry.pop("path", "")
        entry["url"] = media.url_for(path) if path else ""
    return entries


class ProfilesApi:
    def active_instance(self):
        for instance in self.instances:
            if instance["_slug"] == self.selected_slug:
                return instance
        return None

    def _summary(self, instance):
        version = str(instance.get("version", ""))
        base, loader = version, "any"
        try:
            base = game_version_of(version_meta(version))
        except Exception:
            pass
        try:
            loader = detect_loader(load_version(version_meta(version)))
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        ram = instance.get("ram")
        try:
            ram = int(ram) if ram is not None else int(self.ram)
        except (TypeError, ValueError):
            ram = int(self.ram)
        ram = max(self.RAM_MIN, min(self.RAM_MAX, ram))
        try:
            playtime = max(0, int(instance.get("playtime") or 0))
        except (TypeError, ValueError):
            playtime = 0
        banner = profile_banner_path(
            instance["_root"], instance.get("banner"))
        account = self._account_by_id(instance.get("account", ""))
        shared = instance.get("shared")
        shared = shared if isinstance(shared, dict) else {}
        link = ({key: shared.get(key) for key in (
            "build_id", "owner", "revision", "name", "owner_name")}
            if shared.get("build_id") else {})
        return {
            "slug": instance.get("_slug", ""),
            "name": instance.get("name", ""),
            # The account this profile signs in with, or "" for the account
            # that is active in Settings.
            "account": account["id"] if account is not None else "",
            "version": version,
            "base": base,
            "loader": loader,
            "loader_version": profile_loader_version(version, loader, base),
            "loader_label": {"fabric": "Fabric", "forge": "Forge",
                             "neoforge": "NeoForge", "quilt": "Quilt"}
            .get(loader, "Fabric"),
            "ram": ram,
            # Game options written into options.txt before each launch.
            "defaults": normalize_defaults(instance.get("game_defaults")),
            "defaults_set": isinstance(instance.get("game_defaults"), dict),
            # Epoch seconds of the last launch (0 when never started), so the
            # Home screen can show the most recent build first.
            "last_played": float(instance.get("last_played") or 0),
            # Seconds played in this profile, counted while the game runs.
            "playtime": playtime,
            # The banner is served by the loopback media server: a URL is
            # enough, unlike the small inline profile icon.
            "banner": media.url_for(banner) if banner is not None else "",
            "banner_kind": (
                "video" if banner is not None
                and banner.suffix.lower() in BANNER_VIDEO_SUFFIXES
                else "image" if banner is not None else ""),
            "path": str(instance_game_dir(instance["_root"])),
            "icon": profile_icon_data_url(
                instance["_root"], instance.get("icon")),
            "shared": link,
        }

    def state(self):
        with self._lock:
            instance = self.active_instance()
            active_account = self._active_account()
            items = [self._summary(item) for item in self.instances]
            active = None
            if instance is not None:
                active = self._summary(instance)
                stored = instance.get("ram")
                if stored is not None:
                    try:
                        self.ram = max(self.RAM_MIN, min(
                            self.RAM_MAX, int(stored)))
                    except (TypeError, ValueError):
                        pass
            running = self._running_slugs()
            return {
                "instances": items,
                "selected": self.selected_slug if instance is not None else "",
                "instance": active,
                "player": self.player,
                "ram": int(self.ram),
                "default_ram": int(self.default_ram),
                "theme": self.theme,
                "design": self.design,
                "color_mode": self.color_mode,
                "language": self.language,
                "pet": self.pet,
                "onboarded": bool(getattr(self, "_onboarded", False)),
                "java": self.java_path,
                "mirror": self.mirror,
                "proxy": self.proxy,
                "dns": self.dns,
                "curseforge_key_set": bool(self._curseforge_key),
                "accounts": [self._account_public(account)
                             for account in self._accounts],
                "active_account": self._active_account_id,
                "ms": {"client_id": self._ms_client_id,
                       "built_in": bool(MS_CLIENT_ID_DEFAULT),
                       "signed_in": any(account["type"] == "microsoft"
                                        for account in self._accounts)},
                "ely": {"signed_in": any(account["type"] == "ely"
                                         for account in self._accounts),
                        "browser": any(
                            account["type"] == "ely"
                            and account.get("kind") == "oauth"
                            for account in self._accounts),
                        "oauth": {
                            "client_id": self._ely_oauth_client_id,
                            "redirect_uri": self._ely_oauth_redirect,
                            "pkce": not bool(self._ely_oauth_secret),
                            "built_in": bool(ELY_OAUTH_CLIENT_ID_DEFAULT),
                            "configured": bool(
                                self._ely_oauth_client_id
                                or ELY_OAUTH_CLIENT_ID_DEFAULT)}},
                "nexi": {
                    "base_url": str(getattr(self, "nexi_base_url", "") or ""),
                    "signed_in": any(account["type"] == "nexi"
                                     for account in self._accounts)},
                "account": (active_account["type"]
                            if active_account is not None else "offline"),
                "paths": {"shared": str(MC),
                          "instances": str(INSTANCES_DIR)},
                "background": self._background_payload(),
                "busy": self.busy,
                "launching": bool(self._launching),
                "launching_slugs": sorted(self._launching),
                "version": VERSION,
                "game_running": bool(running),
                "game_instance": (self.selected_slug
                                  if self.selected_slug in running else ""),
                "running": running,
            }

    def refresh_instances(self, select=None):
        with self._lock:
            previous = self.selected_slug if select is None else select
            self.instances = list_instances()
            # The rail keeps the drag order from settings; builds that are not
            # in it yet (created after the last reorder) follow alphabetically.
            rank = {slug: index for index, slug in enumerate(
                getattr(self, "instance_order", []))}
            self.instances.sort(key=lambda item: (
                rank.get(item["_slug"], len(rank)), item["name"].lower()))
            slugs = {instance["_slug"] for instance in self.instances}
            if previous not in slugs:
                previous = self.instances[0]["_slug"] if self.instances else ""
            self.selected_slug = previous

    def reorder_instances(self, order):
        """Save the build order of the left rail (a list of profile slugs)."""
        if not isinstance(order, list):
            return {"ok": False, "error": "Invalid build order."}
        with self._lock:
            slugs = [instance["_slug"] for instance in self.instances]
            known = set(slugs)
            clean = []
            for slug in order:
                slug = str(slug or "")
                if slug in known and slug not in clean:
                    clean.append(slug)
            clean += [slug for slug in slugs if slug not in clean]
            if clean == slugs:
                return {"ok": True, "state": self.state()}
            self.instance_order = clean
            self._save()
            self.refresh_instances(select=self.selected_slug)
        return {"ok": True, "state": self.state()}

    def select(self, slug):
        with self._lock:
            slugs = {instance["_slug"] for instance in self.instances}
            if slug not in slugs:
                return {"state": self.state()}
            self.selected_slug = slug
            self._save()
        return {"state": self.state()}

    def set_player(self, name):
        name = str(name or "").strip()[:16] or "Player"
        with self._lock:
            self.player = name
            account = self._active_account()
            if account is not None and account["type"] == "offline":
                account["name"] = name
            self._save()
        return {"player": self.player, "state": self.state()}

    def set_ram(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.ram
        value = max(self.RAM_MIN, min(self.RAM_MAX, value))
        with self._lock:
            self.ram = value
            instance = self.active_instance()
            if instance is not None and instance.get("ram") != value:
                instance["ram"] = value
                write_instance(instance["_root"], instance)
            self._save()
        return {"state": self.state()}

    def set_game_defaults(self, values):
        """Remember the per-profile game options applied on every launch."""
        with self._lock:
            instance = self.active_instance()
            if instance is None:
                return {"ok": False, "error": "Select a profile first.",
                        "state": self.state()}
            data = normalize_defaults(values)
            instance["game_defaults"] = data
            write_instance(instance["_root"], instance)
            self.refresh_instances(select=self.selected_slug)
        return {"ok": True, "state": self.state()}

    def apply_game_defaults(self, values=None):
        """Write the defaults into the profile's options.txt right away."""
        with self._lock:
            instance = self.active_instance()
            if instance is None:
                return {"ok": False, "error": "Select a profile first."}
            data = normalize_defaults(
                values if isinstance(values, dict)
                else instance.get("game_defaults"))
            instance["game_defaults"] = data
            write_instance(instance["_root"], instance)
            root = instance["_root"]
            slug = instance.get("_slug", "")
        try:
            updates = write_game_options(instance_game_dir(root), data)
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not write options.txt: {exc}",
                    "state": self.state()}
        log.info("Game defaults written: slug=%r keys=%s",
                 slug, ",".join(sorted(updates)))
        return {"ok": True,
                "message": "Game defaults written to options.txt.",
                "state": self.state()}

    def instance_set_account(self, account_id):
        """Pick the account this profile launches with ("" = the active one)."""
        account_id = str(account_id or "")
        with self._lock:
            instance = self.active_instance()
            if instance is None:
                return {"ok": False, "error": "Select a profile first.",
                        "state": self.state()}
            account = self._account_by_id(account_id) if account_id else None
            if account_id and account is None:
                return {"ok": False,
                        "error": "That account no longer exists.",
                        "state": self.state()}
            if account is None:
                instance.pop("account", None)
            else:
                instance["account"] = account["id"]
            write_instance(instance["_root"], instance)
            name = instance.get("name", "This profile")
            if account is None:
                message = (f'"{name}" now uses the active account from '
                           "Settings.")
            else:
                message = f'"{name}" now signs in as {account["name"]}.'
        log.info("Profile account set: slug=%r account=%r",
                 instance.get("_slug", ""), account_id or "(active)")
        return {"ok": True, "message": message, "state": self.state()}

    def delete(self, slug):
        with self._lock:
            instance = next(
                (item for item in self.instances if item["_slug"] == slug), None)
            if instance is None:
                return {"state": self.state()}
            name = instance.get("name", slug)
            delete_instance(instance["_root"])
            if self.selected_slug == slug:
                self.selected_slug = ""
            self.refresh_instances(select="")
            self._save()
            state = self.state()
        return {"state": state, "message": f'Deleted "{name}"'}

    def open(self, kind):
        if kind == "ely_skins":
            open_in_system(ELY_SKIN_SITE)
            return {"ok": True, "url": ELY_SKIN_SITE}
        if kind in ("launcher_log", "launcher_logs"):
            target = Path(LOG_FILE) if kind == "launcher_log" else LOG_DIR
            try:
                if target.suffix:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch(exist_ok=True)
                else:
                    target.mkdir(parents=True, exist_ok=True)
            except OSError:
                return {"ok": False, "path": str(target)}
            open_in_system(target)
            return {"ok": True, "path": str(target)}
        instance = self.active_instance()
        if instance is None:
            return {"ok": False}
        root = instance["_root"]
        if kind == "log":
            target = instance_log_file(root)
        else:
            target = {"game": instance_game_dir(root),
                      "mods": instance_mods_dir(root),
                      "logs": instance_game_dir(root) / "logs"}.get(
                kind, instance_game_dir(root))
        try:
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False, "path": str(target)}
        open_in_system(target)
        return {"ok": True, "path": str(target)}

    def open_instance(self, kind, name=""):
        """Open one of the profile's content folders (or one item inside)."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        root = instance["_root"]
        game = instance_game_dir(root)
        bases = {
            "mods": instance_mods_dir(root),
            "resourcepacks": game / "resourcepacks",
            "shaderpacks": game / "shaderpacks",
            "worlds": game / "saves",
            "screenshots": game / "screenshots",
            "logs": game / "logs",
            "backups": root / "backups",
        }
        base = bases.get(str(kind or ""))
        if base is None:
            return {"ok": False, "error": "Unknown folder."}
        name = str(name or "")
        target = base if not name else _zip_member_target(base, name)
        if target is None:
            return {"ok": False, "error": "That item path is not valid."}
        if name and not target.exists():
            return {"ok": False, "error": "That item no longer exists."}
        try:
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        open_in_system(target)
        return {"ok": True, "path": str(target)}

    def profile_contents(self):
        """List installed mods, packs, worlds and screenshots of the profile."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        try:
            data = instance_contents(instance["_root"])
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        _attach_shot_urls(data.get("screenshots", []))
        data["ok"] = True
        return data

    def screenshot_list(self):
        """Cheap screenshot poll with preview URLs (the pane refreshes often)."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        entries = screenshot_entries(instance_game_dir(instance["_root"]))
        _attach_shot_urls(entries)
        return {"ok": True, "screenshots": entries, "count": len(entries)}

    def screenshot_copy(self, name):
        """Put one screenshot on the Windows clipboard as an image."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        folder = instance_game_dir(instance["_root"]) / "screenshots"
        name = str(name or "")
        try:
            base = folder.resolve()
            target = (folder / name).resolve()
        except (OSError, ValueError):
            return {"ok": False, "error": "That screenshot is not valid."}
        if (base not in target.parents
                or target.suffix.lower() not in IMAGE_SUFFIXES):
            return {"ok": False, "error": "That screenshot is not valid."}
        if not target.is_file():
            return {"ok": False, "error": "That screenshot no longer exists."}
        if not copy_image_to_clipboard(target):
            return {"ok": False, "error": "Could not copy the screenshot."}
        return {"ok": True, "message": "Screenshot copied to the clipboard."}

    def resolve_mod_icons(self):
        """Modrinth names and icons for the installed mods, cached per profile."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        root = instance["_root"]
        try:
            data = instance_contents(root)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        cache = read_modrinth_cache(root)
        projects = cache["projects"]
        files = cache["files"]
        mods_dir = instance_mods_dir(root)
        resolved = {}
        offline = False
        deadline = time.time() + 20
        for mod in data.get("mods", []):
            filename = str(mod.get("filename") or "")
            pid = str(mod.get("project_id") or files.get(filename) or "")
            if not pid and filename:
                if offline or time.time() > deadline:
                    continue
                sha1 = _file_sha1(mods_dir / filename)
                if not sha1:
                    continue
                try:
                    version = modrinth_get(
                        f"/version_file/{sha1}", timeout=15)
                except urllib.error.HTTPError:
                    continue
                except Exception:
                    offline = True
                    continue
                pid = str(version.get("project_id") or "")
                if pid:
                    files[filename] = pid
            if not pid:
                continue
            info = projects.get(pid)
            if not isinstance(info, dict) or not info.get("icon_url"):
                if offline or time.time() > deadline:
                    continue
                try:
                    project = modrinth_get(f"/project/{pid}", timeout=15)
                except urllib.error.HTTPError:
                    continue
                except Exception:
                    offline = True
                    continue
                info = {
                    "title": str(project.get("title") or ""),
                    "slug": str(project.get("slug") or ""),
                    "icon_url": str(project.get("icon_url") or ""),
                }
                projects[pid] = info
            if isinstance(info, dict) and info:
                resolved[filename] = dict(info, project_id=pid)
        write_modrinth_cache(root, cache)
        return {
            "ok": True,
            "projects": resolved,
            "error": ("Modrinth is unreachable — showing names from the "
                      "mod files." if offline else ""),
        }

    def _apply_profile_icon(self, root, source: Path):
        suffix = source.suffix.lower()
        if suffix not in ICON_SUFFIXES:
            return {"ok": False,
                    "error": "Choose a PNG, JPG, WEBP, GIF or BMP image."}
        try:
            if not source.is_file():
                return {"ok": False, "error": "That image no longer exists."}
            if source.stat().st_size > ICON_MAX_BYTES:
                return {"ok": False,
                        "error": "That image is larger than 4 MB."}
            target = Path(root) / f"icon{suffix}"
            source_path = source.resolve()
            for old in Path(root).glob("icon.*"):
                if not old.is_file() or old.suffix.lower() not in ICON_SUFFIXES:
                    continue
                if old.resolve() == source_path:
                    continue
                old.unlink(missing_ok=True)
            if source_path != target.resolve():
                shutil.copyfile(source, target)
                if (source_path.parent == Path(root).resolve()
                        and source.name.lower().startswith("icon.")):
                    source.unlink(missing_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Could not set the icon: {exc}"}
        data = read_instance(root)
        if data is None:
            return {"ok": False, "error": "The profile could not be read."}
        data["icon"] = target.name
        write_instance(root, data)
        self.refresh_instances(select=self.selected_slug)
        return {"ok": True, "state": self.state()}

    def set_profile_icon(self):
        """Pick an image and use it as this profile's sidebar icon."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if os.name != "nt":
            return {"ok": False, "error": "The image picker needs Windows."}
        try:
            picked = pick_file(
                "Select a profile icon",
                (("Images", "*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp"),
                 ("All files", "*.*")))
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not open the file picker: {exc}"}
        if not picked:
            return {"ok": False, "cancelled": True}
        return self._apply_profile_icon(instance["_root"], Path(picked))

    def clear_profile_icon(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        root = instance["_root"]
        try:
            for old in Path(root).glob("icon.*"):
                if old.is_file() and old.suffix.lower() in ICON_SUFFIXES:
                    old.unlink(missing_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Could not remove the icon: {exc}"}
        data = read_instance(root)
        if data is not None:
            data.pop("icon", None)
            write_instance(root, data)
        self.refresh_instances(select=self.selected_slug)
        return {"ok": True, "state": self.state()}

    def _apply_profile_banner(self, root, source: Path):
        suffix = source.suffix.lower()
        if suffix not in BANNER_SUFFIXES:
            return {"ok": False,
                    "error": "Choose a PNG, JPG, WEBP, GIF, MP4 or WebM file."}
        video = suffix in BANNER_VIDEO_SUFFIXES
        try:
            if not source.is_file():
                return {"ok": False, "error": "That file no longer exists."}
            if source.stat().st_size > (BANNER_VIDEO_MAX_BYTES if video
                                        else BANNER_MAX_BYTES):
                return {"ok": False,
                        "error": ("That video is larger than 50 MB." if video
                                  else "That image is larger than 20 MB.")}
            target = Path(root) / f"banner{suffix}"
            source_path = source.resolve()
            for old in Path(root).glob("banner.*"):
                if not old.is_file() or old.suffix.lower() not in BANNER_SUFFIXES:
                    continue
                if old.resolve() == source_path:
                    continue
                old.unlink(missing_ok=True)
            if source_path != target.resolve():
                shutil.copyfile(source, target)
        except OSError as exc:
            return {"ok": False, "error": f"Could not set the banner: {exc}"}
        data = read_instance(root)
        if data is None:
            return {"ok": False, "error": "The profile could not be read."}
        data["banner"] = target.name
        write_instance(root, data)
        self.refresh_instances(select=self.selected_slug)
        return {"ok": True, "state": self.state()}

    def set_profile_banner(self):
        """Pick an image file and use it behind this profile's header."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        if os.name != "nt":
            return {"ok": False, "error": "The image picker needs Windows."}
        try:
            picked = pick_file(
                "Select a build banner",
                (("Images and videos",
                  "*.png;*.jpg;*.jpeg;*.webp;*.gif;*.mp4;*.webm"),
                 ("Images", "*.png;*.jpg;*.jpeg;*.webp;*.gif"),
                 ("Video", "*.mp4;*.webm"),
                 ("All files", "*.*")))
        except OSError as exc:
            return {"ok": False,
                    "error": f"Could not open the file picker: {exc}"}
        if not picked:
            return {"ok": False, "cancelled": True}
        return self._apply_profile_banner(instance["_root"], Path(picked))

    def clear_profile_banner(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        root = instance["_root"]
        try:
            for old in Path(root).glob("banner.*"):
                if old.is_file() and old.suffix.lower() in BANNER_SUFFIXES:
                    old.unlink(missing_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Could not remove the banner: {exc}"}
        data = read_instance(root)
        if data is not None:
            data.pop("banner", None)
            write_instance(root, data)
        self.refresh_instances(select=self.selected_slug)
        return {"ok": True, "state": self.state()}
