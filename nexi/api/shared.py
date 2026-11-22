"""Shared builds: publish a profile, invite friends, keep copies in sync.

Only the Minecraft version, the mod loader and the exact mod/pack versions
travel through the site. Worlds, screenshots, options and accounts stay in
each player's own profile.
"""

import hashlib
import json

from ..curseforge import curseforge_versions, resolve_manifest_file
from ..instances import (
    create_instance, instance_base_version, instance_mods_dir,
    instance_pack_dir, mod_state_entry, profile_loader_version,
    read_mods_state, read_packs_state, write_instance, write_mods_state,
    write_packs_state,
)
from ..java_runtime import ensure_java
from ..loaders import console_java_for, find_loader_profile, install_loader
from ..logging_setup import log
from ..modrinth import mod_versions, modrinth_get, primary_file
from ..net import download_file
from ..util import safe_filename
from ..vanilla import (
    fetch_version_manifest, install_vanilla, manifest_entry, version_installed,
)
from ..versions import detect_loader, load_version, version_meta

SHARED_LOADERS = ("fabric", "forge", "neoforge")
SHARED_PACK_KINDS = ("resourcepack", "shader")


class SharedBuildMissing(RuntimeError):
    pass


def shared_fingerprint(definition):
    text = json.dumps(definition or {}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shared_entry(entry):
    """One state-file entry in the shape the site accepts."""
    return {
        "project_id": str(entry.get("project_id") or ""),
        "source": str(entry.get("source") or "modrinth"),
        "version_id": str(entry.get("version_id") or ""),
        "version_number": str(entry.get("version_number") or ""),
        "filename": str(entry.get("filename") or ""),
        "slug": str(entry.get("slug") or ""),
        "title": str(entry.get("title") or ""),
        "icon_url": str(entry.get("icon_url") or ""),
    }


class SharedApi:
    # -------------------------------------------------------------- helpers

    def _shared_link(self, instance):
        link = instance.get("shared") if isinstance(
            instance, dict) and isinstance(instance.get("shared"), dict) else {}
        return link if link.get("build_id") else {}

    def _shared_store_link(self, instance, link):
        if link:
            instance["shared"] = link
        else:
            instance.pop("shared", None)
        write_instance(instance["_root"], instance)

    def _shared_profile_definition(self, instance):
        """The shareable part of a profile: version, loader and exact files."""
        root = instance["_root"]
        try:
            base = instance_base_version(instance)
        except Exception:
            base = str(instance.get("version") or "")
        version_id = str(instance.get("version") or "")
        try:
            loader = detect_loader(load_version(version_meta(version_id)))
        except Exception:
            loader = "any"
        if loader not in SHARED_LOADERS:
            if loader != "any":
                raise RuntimeError(f"{loader.capitalize()} profiles can't "
                                   "be shared yet.")
            loader = "any"
        loader_version = (profile_loader_version(version_id, loader, base)
                          if loader != "any" else "")
        mods = []
        mods_dir = instance_mods_dir(root)
        for project, entry in read_mods_state(root).items():
            if not isinstance(entry, dict) or not entry.get("filename"):
                continue
            if not (mods_dir / safe_filename(entry["filename"])).is_file():
                continue
            item = _shared_entry(dict(entry, project_id=str(project)))
            if item["project_id"]:
                mods.append(item)
        mods.sort(key=lambda item: item["project_id"])
        packs = {}
        pack_state = read_packs_state(root)
        for kind in SHARED_PACK_KINDS:
            bucket = pack_state.get(kind)
            bucket = bucket if isinstance(bucket, dict) else {}
            folder = instance_pack_dir(root, kind)
            items = []
            for project, entry in bucket.items():
                if not isinstance(entry, dict) or not entry.get("filename"):
                    continue
                if not (folder / safe_filename(entry["filename"])).is_file():
                    continue
                item = _shared_entry(dict(entry, project_id=str(project)))
                if item["project_id"]:
                    items.append(item)
            items.sort(key=lambda item: item["project_id"])
            packs[kind] = items
        return {
            "mc_version": base,
            "loader": loader,
            "loader_version": loader_version,
            "mods": mods,
            "packs": packs,
        }

    @staticmethod
    def _shared_site_id(account):
        return str((account or {}).get("site_id") or "")

    def _shared_unique_name(self, name):
        taken = {str(item.get("name") or "").lower()
                 for item in self.instances}
        base = str(name or "").strip()[:48] or "Shared build"
        candidate = base
        index = 2
        while candidate.lower() in taken:
            candidate = f"{base} ({index})"
            index += 1
        return candidate

    def _shared_local_slugs(self):
        found = {}
        for instance in self.instances:
            link = self._shared_link(instance)
            if link:
                found[str(link.get("build_id"))] = instance.get("_slug", "")
        return found

    # ----------------------------------------------------------- item files

    def _shared_item_file(self, item, kind, game, loader):
        """(file, version) for one shared item; exact versions never fall
        back to a different build, so everyone runs the same files."""
        source = str(item.get("source") or "modrinth").lower()
        project = str(item.get("project_id") or "")
        version_id = str(item.get("version_id") or "")
        if source == "curseforge":
            if version_id:
                resolved = resolve_manifest_file(project, version_id)
                if not resolved:
                    raise RuntimeError("CurseForge has no file for this "
                                       "version")
                return ({"url": resolved["url"],
                         "filename": resolved["filename"],
                         "size": int(resolved.get("filesize") or 0)}, None)
            versions = curseforge_versions(project, game, loader, kind)
            version = versions[0] if versions else None
            return (primary_file(version) if version else None, version)
        if version_id:
            try:
                version = modrinth_get(f"/version/{version_id}")
            except Exception as exc:
                raise RuntimeError(f"Modrinth has no file for this version "
                                   f"({exc})") from exc
            if not isinstance(version, dict):
                raise RuntimeError("Modrinth has no file for this version")
            file = primary_file(version)
            if file is None:
                raise RuntimeError("This version has no downloadable file")
            return (file, version)
        versions = mod_versions(project, game, loader, kind)
        version = versions[0] if versions else None
        return (primary_file(version) if version else None, version)

    def _shared_apply_items(self, root, items, kind, game, loader):
        """Install exact versions and drop tracked files no longer listed."""
        if kind == "mod":
            folder = instance_mods_dir(root)
            state = read_mods_state(root)

            def save_state():
                write_mods_state(root, state)
        else:
            folder = instance_pack_dir(root, kind)
            all_state = read_packs_state(root)
            bucket = all_state.get(kind)
            state = bucket if isinstance(bucket, dict) else {}
            all_state[kind] = state

            def save_state():
                write_packs_state(root, all_state)

        desired = {}
        for item in items or []:
            if isinstance(item, dict) and item.get("project_id"):
                desired[str(item["project_id"])] = item
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return 0, 0, [f"could not create the folder: {exc}"]

        changed = 0
        failed = []
        for project, item in desired.items():
            source = str(item.get("source") or "modrinth")
            title = str(item.get("title") or item.get("filename")
                        or project)
            version_id = str(item.get("version_id") or "")
            entry = state.get(project)
            entry = entry if isinstance(entry, dict) else {}
            current = safe_filename(str(entry.get("filename") or ""))
            if entry and (folder / current).is_file() and (
                    not version_id
                    or str(entry.get("version_id") or "") == version_id):
                continue
            try:
                file, version = self._shared_item_file(item, kind, game,
                                                       loader)
            except Exception as exc:
                failed.append(f"{title}: {exc}")
                continue
            raw_name = str((file or {}).get("filename")
                           or item.get("filename") or "")
            if not file or not raw_name:
                failed.append(f"{title}: no downloadable file")
                continue
            name = safe_filename(raw_name)
            target = folder / name
            if not target.is_file():
                self._status("profiles", f"Downloading {name}…")
                self._event("busy", task="shared", on=True,
                            label=f"Downloading {name}")
                try:
                    download_file(file["url"], target,
                                  size=file.get("size") or None)
                except Exception as exc:
                    failed.append(f"{title}: {exc}")
                    continue
            if version is not None:
                state[project] = mod_state_entry(
                    version, file, project, slug=item.get("slug") or "",
                    title=item.get("title") or "", source=source)
            else:
                state[project] = {
                    "filename": name,
                    "version_id": version_id
                    or str((version or {}).get("id") or ""),
                    "version_number": str(item.get("version_number") or ""),
                    "project_id": project,
                    "slug": str(item.get("slug") or ""),
                    "title": str(item.get("title") or ""),
                    "source": source,
                }
            if current and current != name:
                try:
                    (folder / current).unlink()
                except OSError:
                    pass
            changed += 1

        removed = 0
        for project, entry in list(state.items()):
            if project in desired:
                continue
            name = safe_filename(str(
                entry.get("filename") if isinstance(entry, dict) else ""))
            if name:
                try:
                    (folder / name).unlink()
                except OSError:
                    pass
            state.pop(project, None)
            removed += 1
        save_state()
        return changed, removed, failed

    # -------------------------------------------------------------- apply

    def _shared_apply(self, instance, build):
        """Make a profile match a shared build; worlds are never touched."""
        definition = build.get("definition")
        definition = definition if isinstance(definition, dict) else {}
        base = str(definition.get("mc_version") or "").strip()
        if not base:
            raise RuntimeError("the shared build has no Minecraft version")
        loader = str(definition.get("loader") or "any").lower()
        loader_version = str(definition.get("loader_version") or "").strip()
        name = str(build.get("name") or "shared build")
        root = instance["_root"]

        def say(text):
            log.info("shared %r: %s", instance.get("_slug"), text)

        self._status("profiles", f"Applying “{name}”…")
        if not version_installed(base):
            self._status("profiles", f"Downloading Minecraft {base}…")
            entry = manifest_entry(fetch_version_manifest(), base)
            if entry is None:
                raise RuntimeError(f"Minecraft {base} is not in Mojang's "
                                   "version list")
            install_vanilla(base, entry, log=say, progress=self._progress)
        version = base
        if loader in SHARED_LOADERS and loader_version:
            profile = find_loader_profile(loader, base, loader_version)
            if profile is None:
                try:
                    ensure_java(load_version(version_meta(base)), say,
                                self._progress)
                except Exception as exc:
                    log.warning("shared: Java could not be prepared: %s", exc)
                self._status("profiles",
                             f"Installing {loader} {loader_version}…")
                profile = install_loader(loader, base, loader_version,
                                         console_java_for(base), say,
                                         progress=self._progress)
            if not profile:
                raise RuntimeError(f"{loader} {loader_version} could not be "
                                   "installed")
            version = profile
        instance["version"] = version

        changed, removed, failed = self._shared_apply_items(
            root, definition.get("mods") or [], "mod", base, loader)
        packs = definition.get("packs")
        packs = packs if isinstance(packs, dict) else {}
        for kind in SHARED_PACK_KINDS:
            c, r, f = self._shared_apply_items(
                root, packs.get(kind) or [], kind, base, loader)
            changed += c
            removed += r
            failed += f

        link = self._shared_link(instance)
        if link and not failed:
            owner = build.get("owner") or {}
            link["revision"] = int(build.get("revision") or 1)
            link["fingerprint"] = shared_fingerprint(definition)
            link["name"] = name
            link["owner_name"] = str(owner.get("nick")
                                     or owner.get("account_name") or "")
            link["updated"] = str(build.get("updated") or "")
            instance["shared"] = link
        write_instance(root, instance)
        return changed, removed, failed

    # -------------------------------------------------------------- remote

    def _shared_push(self, instance, link, token, definition=None):
        if definition is None:
            definition = self._shared_profile_definition(instance)
        fingerprint = shared_fingerprint(definition)
        if fingerprint == str(link.get("fingerprint") or ""):
            return False
        payload = {
            "definition": definition,
            "name": str(link.get("name") or instance.get("name") or ""),
            "description": str(link.get("description") or ""),
        }
        ok, data = self._nexi_call(
            f"/api/nexi/builds/{int(link['build_id'])}", payload, token=token)
        if not ok:
            if data.get("status") == 404:
                raise SharedBuildMissing(
                    "The owner deleted this shared build.")
            raise RuntimeError(data.get("error")
                               or "Could not update the shared build.")
        build = data.get("build") or {}
        link["revision"] = int(build.get("revision")
                               or link.get("revision") or 1)
        link["fingerprint"] = fingerprint
        link["name"] = str(build.get("name") or link.get("name") or "")
        link["updated"] = str(build.get("updated") or "")
        instance["shared"] = link
        write_instance(instance["_root"], instance)
        return True

    def _shared_pull(self, instance, link, token, build=None):
        if build is None:
            ok, data = self._nexi_call(
                f"/api/nexi/builds/{int(link['build_id'])}", token=token)
            if not ok:
                if data.get("status") == 404:
                    raise SharedBuildMissing(
                        "The owner deleted this shared build.")
                raise RuntimeError(data.get("error")
                                   or "Could not read the shared build.")
            build = data.get("build") or {}
        changed, removed, failed = self._shared_apply(instance, build)
        return changed, removed, failed, build

    # ------------------------------------------------------------- public

    def shared_info(self):
        """The card in Profile settings: link, remote build and friends."""
        instance = self.active_instance()
        account, token, error = self._nexi_token_account()
        result = {
            "ok": True,
            "signed_in": token != "",
            "account": str((account or {}).get("name") or ""),
            "instance": str((instance or {}).get("name") or ""),
            "linked": False,
            "owner": False,
            "link": {},
            "build": None,
            "missing": False,
            "friends": [],
            "error": "",
        }
        if instance is None:
            return result
        link = self._shared_link(instance)
        if not link:
            return result
        result["linked"] = True
        result["owner"] = bool(link.get("owner"))
        result["link"] = {key: link.get(key) for key in (
            "build_id", "owner", "revision", "name", "owner_name",
            "description") if key in link}
        if not token:
            result["error"] = error
            return result
        ok, data = self._nexi_call(
            f"/api/nexi/builds/{int(link['build_id'])}", token=token)
        if not ok:
            if data.get("status") == 404:
                result["missing"] = True
            else:
                result["error"] = str(data.get("error")
                                      or "Could not read the shared build.")
            return result
        build = data.get("build") or {}
        result["build"] = build
        if result["owner"]:
            ok2, friends = self._nexi_call("/api/nexi/friends", token=token)
            members = {str(item.get("id"))
                       for item in build.get("members") or []}
            rows = friends.get("friends") if ok2 else []
            result["friends"] = [{
                "id": item.get("id"),
                "name": str(item.get("nick") or item.get("account_name")
                            or item.get("nexi_id") or ""),
                "handle": str(item.get("handle") or ""),
                "added": str(item.get("id")) in members,
                "online": bool(item.get("online")),
            } for item in rows or [] if isinstance(item, dict)]
        return result

    def shared_available(self):
        """Builds shared with the player, for the Home panel."""
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": True, "signed_in": False, "builds": [],
                    "error": error}
        ok, data = self._nexi_call("/api/nexi/builds", token=token)
        if not ok:
            return {"ok": False, "signed_in": True, "builds": [],
                    "error": data.get("error")
                    or "Could not load shared builds."}
        local = self._shared_local_slugs()
        builds = []
        for build in data.get("builds") or []:
            if not isinstance(build, dict):
                continue
            definition = build.get("definition")
            definition = definition if isinstance(definition, dict) else {}
            owner = build.get("owner")
            owner = owner if isinstance(owner, dict) else {}
            packs = definition.get("packs")
            packs = packs if isinstance(packs, dict) else {}
            builds.append({
                "id": build.get("id"),
                "name": str(build.get("name") or "Shared build"),
                "description": str(build.get("description") or ""),
                "revision": int(build.get("revision") or 1),
                "owner_name": str(owner.get("nick")
                                  or owner.get("account_name")
                                  or owner.get("nexi_id") or "Friend"),
                "owner_id": owner.get("id"),
                "is_owner": bool(build.get("is_owner")),
                "members": len(build.get("members") or []),
                "mc_version": str(definition.get("mc_version") or ""),
                "loader": str(definition.get("loader") or "any"),
                "loader_version": str(definition.get("loader_version") or ""),
                "mods": len(definition.get("mods") or []),
                "packs": sum(len(value or []) for value in packs.values()),
                "local_slug": local.get(str(build.get("id")), ""),
            })
        return {"ok": True, "signed_in": True, "builds": builds}

    def shared_publish(self, name="", description=""):
        """Publish the active profile, or update its shared definition."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": False, "signed_in": account is not None,
                    "error": error or "Sign in to Nexi first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        link = self._shared_link(instance)
        if link and not link.get("owner"):
            return {"ok": False,
                    "error": ("This profile follows a friend's build. Stop "
                              "following it first to publish your own.")}
        try:
            definition = self._shared_profile_definition(instance)
        except Exception as exc:
            return {"ok": False,
                    "error": f"Could not read this profile: {exc}"}
        if not definition["mc_version"]:
            return {"ok": False,
                    "error": "This profile has no Minecraft version."}
        try:
            loader = detect_loader(load_version(
                version_meta(str(instance.get("version") or ""))))
        except Exception:
            loader = definition["loader"]
        if loader not in SHARED_LOADERS and loader != "any":
            return {"ok": False,
                    "error": f"{loader} profiles can't be shared yet."}
        build_name = (str(name or "").strip()[:64]
                      or str(instance.get("name") or "")[:64]
                      or "Shared build")
        desc = str(description or "").strip()[:300]
        payload = {"name": build_name, "description": desc,
                   "definition": definition}
        if link:
            ok, data = self._nexi_call(
                f"/api/nexi/builds/{int(link['build_id'])}", payload,
                token=token)
        else:
            ok, data = self._nexi_call("/api/nexi/builds", payload,
                                       token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error")
                    or "Could not publish the shared build."}
        build = data.get("build") or {}
        old = link or {}
        self._shared_store_link(instance, {
            "build_id": int(build.get("id") or old.get("build_id") or 0),
            "owner": True,
            "revision": int(build.get("revision") or 1),
            "fingerprint": shared_fingerprint(definition),
            "name": str(build.get("name") or build_name),
            "owner_name": str(account.get("name") or ""),
            "description": desc,
        })
        log.info("Shared build %s saved for %r (revision %s)",
                 build.get("id"), instance.get("_slug"),
                 build.get("revision"))
        self._event("refresh", select=instance.get("_slug"))
        message = (f"Shared build updated (revision {build.get('revision')})."
                   if old else
                   f'Published "{build_name}" to your friends.')
        return {"ok": True, "message": message, "state": self.state()}

    def shared_unpublish(self):
        """Owner deletes the remote build; a member stops following it."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        link = self._shared_link(instance)
        if not link:
            return {"ok": False, "error": "This profile is not shared."}
        account, token, error = self._nexi_token_account()
        owner = bool(link.get("owner"))
        if token:
            build_id = int(link["build_id"])
            if owner:
                ok, data = self._nexi_call(
                    f"/api/nexi/builds/{build_id}", token=token,
                    method="DELETE")
                if not ok and data.get("status") != 404:
                    return {"ok": False,
                            "error": data.get("error")
                            or "Could not delete the shared build."}
            else:
                site_id = self._shared_site_id(account)
                if site_id:
                    self._nexi_call(
                        f"/api/nexi/builds/{build_id}/members/"
                        f"{int(site_id)}", token=token, method="DELETE")
        self._shared_store_link(instance, {})
        log.info("Shared build %s unlinked from %r", link.get("build_id"),
                 instance.get("_slug"))
        self._event("refresh", select=instance.get("_slug"))
        message = ("The shared build was deleted — friends keep their files "
                   "but stop receiving updates." if owner else
                   f'Stopped following "{link.get("name") or "the build"}".')
        return {"ok": True, "message": message, "state": self.state()}

    def shared_add_member(self, user_id=""):
        instance = self.active_instance()
        link = self._shared_link(instance) if instance else {}
        if not link or not link.get("owner"):
            return {"ok": False,
                    "error": "Publish this profile before adding friends."}
        try:
            user_id = int(str(user_id).strip())
        except (TypeError, ValueError):
            return {"ok": False, "error": "That friend is invalid."}
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": False, "error": error or "Sign in to Nexi first."}
        ok, data = self._nexi_call(
            f"/api/nexi/builds/{int(link['build_id'])}/members",
            {"id": user_id}, token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error")
                    or "Could not add that friend."}
        log.info("Shared build %s: added member %s", link.get("build_id"),
                 user_id)
        return {"ok": True, "message": "Friend added to the shared build.",
                "info": self.shared_info()}

    def shared_remove_member(self, user_id=""):
        instance = self.active_instance()
        link = self._shared_link(instance) if instance else {}
        if not link:
            return {"ok": False, "error": "This profile is not shared."}
        try:
            user_id = int(str(user_id).strip())
        except (TypeError, ValueError):
            return {"ok": False, "error": "That friend is invalid."}
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": False, "error": error or "Sign in to Nexi first."}
        ok, data = self._nexi_call(
            f"/api/nexi/builds/{int(link['build_id'])}/members/{user_id}",
            token=token, method="DELETE")
        if not ok:
            return {"ok": False,
                    "error": data.get("error")
                    or "Could not remove that friend."}
        return {"ok": True, "message": "Friend removed from the shared build.",
                "info": self.shared_info()}

    def shared_join(self, build_id=""):
        """Create a local profile that follows a build shared with the player."""
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": False, "signed_in": account is not None,
                    "error": error or "Sign in to Nexi first."}
        try:
            build_id = int(str(build_id).strip())
        except (TypeError, ValueError):
            return {"ok": False, "error": "That shared build is invalid."}
        for instance in self.instances:
            link = self._shared_link(instance)
            if str(link.get("build_id") or "") == str(build_id):
                return {"ok": False,
                        "error": ("This shared build is already in "
                                  f'"{instance.get("name")}".')}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        ok, data = self._nexi_call(f"/api/nexi/builds/{build_id}",
                                   token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error")
                    or "Could not read the shared build."}
        build = data.get("build") or {}
        definition = build.get("definition")
        definition = definition if isinstance(definition, dict) else {}
        base = str(definition.get("mc_version") or "").strip()
        if not base:
            return {"ok": False,
                    "error": "The shared build has no Minecraft version."}
        name = self._shared_unique_name(str(build.get("name")
                                            or "Shared build"))
        owner = build.get("owner")
        owner = owner if isinstance(owner, dict) else {}
        self.busy = "shared"
        self._event("busy", task="shared", on=True)
        try:
            instance = create_instance(name, base, ram=self.default_ram)
            self._shared_store_link(instance, {
                "build_id": build_id,
                "owner": False,
                "revision": 0,
                "fingerprint": "",
                "name": str(build.get("name") or name),
                "owner_name": str(owner.get("nick")
                                  or owner.get("account_name") or ""),
                "description": str(build.get("description") or ""),
            })
            self.refresh_instances(select=instance["_slug"])
            self._save()
            self._event("refresh", select=instance["_slug"])
            try:
                changed, removed, failed = self._shared_apply(instance, build)
            except Exception as exc:
                self.refresh_instances(select=instance["_slug"])
                message = (f'Added "{name}", but the files are not ready '
                           f"yet: {exc}. It will retry automatically.")
                self._status("profiles", message, error=True)
                return {"ok": False, "partial": True, "error": message,
                        "state": self.state()}
            self.refresh_instances(select=instance["_slug"])
            if failed:
                message = (f'Added "{name}" — {changed} item(s) downloaded, '
                           f"{len(failed)} will retry: "
                           + "; ".join(failed[:3]))
                self._status("profiles", message, error=True)
                return {"ok": True, "warning": True, "message": message,
                        "state": self.state()}
            message = (f'Added "{name}" with {changed} item(s) from the '
                       "shared build.")
            if removed:
                message += f" Removed {removed} leftover item(s)."
            self._status("profiles", message)
            log.info("Shared build %s joined as %r", build_id,
                     instance.get("_slug"))
            return {"ok": True, "message": message, "state": self.state()}
        finally:
            self.busy = ""
            self._event("busy", task="shared", on=False)

    def shared_sync(self):
        """Push owner changes or pull a newer revision for the active profile."""
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Select a profile first."}
        link = self._shared_link(instance)
        if not link:
            return {"ok": False,
                    "error": "This profile is not linked to a shared build."}
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": False, "signed_in": account is not None,
                    "error": error or "Sign in to Nexi first."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "shared"
        self._event("busy", task="shared", on=True)
        try:
            if link.get("owner"):
                changed = self._shared_push(instance, link, token)
                message = ("Shared build updated — friends get the new "
                           "revision on their next check." if changed else
                           "The shared build is already up to date.")
                self._status("profiles", message)
                return {"ok": True, "changed": changed, "message": message,
                        "state": self.state()}
            try:
                previous = int(link.get("revision") or 0)
                changed, removed, failed, build = self._shared_pull(
                    instance, link, token)
            except SharedBuildMissing as exc:
                self._status("profiles", str(exc), error=True)
                return {"ok": False, "missing": True, "error": str(exc),
                        "state": self.state()}
            if failed:
                message = (f"Updated {changed} item(s); {len(failed)} failed "
                           "and will retry: " + "; ".join(failed[:3]))
                self._status("profiles", message, error=True)
                return {"ok": True, "warning": True, "changed": changed,
                        "message": message, "state": self.state()}
            message = ("Updated to the latest revision."
                       if changed or removed
                       or int(build.get("revision") or 1) != previous else
                       "Already up to date with the shared build.")
            self._status("profiles", message)
            return {"ok": True, "changed": changed, "message": message,
                    "build": build, "state": self.state()}
        except SharedBuildMissing as exc:
            self._status("profiles", str(exc), error=True)
            return {"ok": False, "missing": True, "error": str(exc),
                    "state": self.state()}
        except Exception as exc:
            message = f"Shared build sync failed: {exc}"
            self._status("profiles", message, error=True)
            return {"ok": False, "error": message, "state": self.state()}
        finally:
            self.busy = ""
            self._event("busy", task="shared", on=False)

    def shared_auto_sync(self):
        """Quiet periodic sync: owners push changes, members pull revisions."""
        account, token, error = self._nexi_token_account()
        if not token:
            return {"ok": True, "signed_in": False, "changed": 0}
        if self.busy:
            return {"ok": True, "signed_in": True, "skipped": True}
        pending = []
        for instance in list(self.instances):
            link = self._shared_link(instance)
            if not link:
                continue
            try:
                if link.get("owner"):
                    definition = self._shared_profile_definition(instance)
                    if (shared_fingerprint(definition)
                            != str(link.get("fingerprint") or "")):
                        pending.append(("push", instance, link, definition))
                else:
                    ok, data = self._nexi_call(
                        f"/api/nexi/builds/{int(link['build_id'])}",
                        token=token)
                    if not ok:
                        continue
                    build = data.get("build") or {}
                    definition = build.get("definition")
                    definition = (definition if isinstance(definition, dict)
                                  else {})
                    if (int(build.get("revision") or 1)
                            != int(link.get("revision") or 0)
                            or shared_fingerprint(definition)
                            != str(link.get("fingerprint") or "")):
                        pending.append(("pull", instance, link, build))
            except Exception as exc:
                log.debug("shared auto check failed for %r: %s",
                          instance.get("_slug"), exc)
        if not pending:
            return {"ok": True, "signed_in": True, "changed": 0}
        self.busy = "shared"
        self._event("busy", task="shared", on=True)
        changed = 0
        try:
            for action, instance, link, payload in pending:
                try:
                    if action == "push":
                        if self._shared_push(instance, link, token,
                                             definition=payload):
                            changed += 1
                    else:
                        got, removed, failed, _build = self._shared_pull(
                            instance, link, token, build=payload)
                        if failed:
                            log.warning("shared auto sync: %d item(s) failed "
                                        "for %r", len(failed),
                                        instance.get("_slug"))
                        else:
                            # A revision can change without touching any
                            # files (loader or version only), so count it.
                            changed += max(1, got + removed)
                except Exception as exc:
                    log.warning("shared auto sync failed for %r: %s",
                                instance.get("_slug"), exc)
        finally:
            self.busy = ""
            self._event("busy", task="shared", on=False)
        if changed:
            self.refresh_instances(select=self.selected_slug)
            self._save()
            self._event("refresh", select=self.selected_slug)
            self._status("profiles",
                         f"Shared builds updated ({changed} change(s)).")
        return {"ok": True, "signed_in": True, "changed": changed}
