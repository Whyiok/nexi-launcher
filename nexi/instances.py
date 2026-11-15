"""Isolated game profiles: files, mods, packs, icons."""

import base64
import hashlib
import json
import logging
import re
import shutil
import tomllib
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from .config import INSTANCES_DIR, USER_AGENT
from .util import safe_filename
from .versions import game_version_of, version_meta


def _instance_slug(name: str, taken) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._") or "instance"
    slug = base
    index = 2
    while slug.lower() in taken:
        slug = f"{base}-{index}"
        index += 1
    return slug


def instance_game_dir(root: Path) -> Path:
    """Per-profile game directory — mods, configs and worlds live here."""
    return Path(root) / "minecraft"


def instance_mods_dir(root: Path) -> Path:
    return instance_game_dir(root) / "mods"


MODS_STATE_FILE = "installed_mods.json"


def read_mods_state(root: Path) -> dict:
    """project_id -> {filename, version_id, …} of mods installed by us."""
    try:
        data = json.loads((Path(root) / MODS_STATE_FILE)
                          .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_mods_state(root: Path, data: dict):
    try:
        (Path(root) / MODS_STATE_FILE).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


MODRINTH_CACHE_FILE = "modrinth_cache.json"


def read_modrinth_cache(root: Path) -> dict:
    """Cached Modrinth names/icons and jar metadata for one profile."""
    try:
        data = json.loads((Path(root) / MODRINTH_CACHE_FILE)
                          .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ("projects", "files", "jars"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def write_modrinth_cache(root: Path, data: dict):
    try:
        (Path(root) / MODRINTH_CACHE_FILE).write_text(
            json.dumps(data, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


_ICON_MIMES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}


def _icon_data_url(data: bytes, name: str) -> str:
    if not data:
        return ""
    mime = _ICON_MIMES.get(Path(name).suffix.lower().lstrip("."))
    if not mime:
        return ""
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def jar_mod_meta(path: Path) -> dict:
    """Name, id, version and icon embedded in a mod jar (works offline)."""
    info = {"id": "", "name": "", "version": "", "icon": ""}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())

            def read_bytes(member):
                try:
                    return archive.read(member)
                except (KeyError, OSError, zipfile.BadZipFile):
                    return b""

            if "fabric.mod.json" in names:
                try:
                    data = json.loads(
                        read_bytes("fabric.mod.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    data = {}
                if isinstance(data, dict):
                    info["id"] = str(data.get("id") or "")
                    info["name"] = str(data.get("name") or "")
                    info["version"] = str(data.get("version") or "")
                    icon = data.get("icon")
                    if isinstance(icon, dict):
                        # {"128": "icon_128.png"}: take the largest entry.
                        icon = icon[max(icon, key=lambda k: str(k))] if icon else ""
                    icon = str(icon or "").lstrip("/")
                    if icon in names:
                        info["icon"] = _icon_data_url(read_bytes(icon), icon)

            if not info["name"]:
                member = ""
                for candidate in ("META-INF/neoforge.mods.toml",
                                  "META-INF/mods.toml"):
                    if candidate in names:
                        member = candidate
                        break
                if member:
                    try:
                        data = tomllib.loads(
                            read_bytes(member).decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        data = {}
                    blocks = data.get("mods") if isinstance(data, dict) else None
                    block = blocks[0] if isinstance(blocks, list) and blocks else {}
                    if isinstance(block, dict):
                        info["id"] = info["id"] or str(block.get("modId") or "")
                        info["name"] = str(block.get("displayName") or "")
                        info["version"] = str(block.get("version") or "")
                        logo = str(block.get("logoFile") or "").lstrip("/")
                        if logo and logo in names:
                            info["icon"] = info["icon"] or _icon_data_url(
                                read_bytes(logo), logo)

            if not info["name"]:
                manifest = read_bytes("META-INF/MANIFEST.MF").decode(
                    "utf-8", "replace")
                for line in manifest.splitlines():
                    if line.lower().startswith("implementation-title:"):
                        info["name"] = line.split(":", 1)[1].strip()
                        break
    except (OSError, zipfile.BadZipFile):
        pass
    return info


def _jar_meta_cached(path: Path, jars: dict) -> dict:
    """jar_mod_meta() memoised by file size and mtime."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    signature = f"icon2:{stat.st_size}:{stat.st_mtime_ns}"
    entry = jars.get(path.name)
    if isinstance(entry, dict) and entry.get("signature") == signature:
        return entry
    meta = jar_mod_meta(path)
    meta["signature"] = signature
    jars[path.name] = meta
    return meta


def _file_sha1(path: Path) -> str:
    try:
        digest = hashlib.sha1()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


ICON_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


ICON_MAX_BYTES = 4 * 1024 * 1024


IMAGE_SUFFIXES = ICON_SUFFIXES | {".tga"}


def profile_icon_data_url(root, name) -> str:
    """Inline data URL for a profile icon; icons are small enough for state."""
    filename = safe_filename(str(name or ""))
    if not filename:
        return ""
    path = Path(root) / filename
    suffix = path.suffix.lower()
    if suffix not in ICON_SUFFIXES:
        return ""
    try:
        if not path.is_file() or path.stat().st_size > ICON_MAX_BYTES:
            return ""
        raw = path.read_bytes()
    except OSError:
        return ""
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else f"image/{suffix[1:]}"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def download_profile_icon(root, url: str) -> str:
    """Save a remote image (a Modrinth project icon) as icon.<ext>.

    Returns the stored filename, or "" when the image cannot be used. Never
    raises: a missing icon must not break a modpack install.
    """
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return ""
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in ICON_SUFFIXES:
        suffix = ".png"
    target = Path(root) / f"icon{suffix}"
    part = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, \
                part.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if part.stat().st_size > ICON_MAX_BYTES:
            part.unlink(missing_ok=True)
            return ""
        for old in Path(root).glob("icon.*"):
            if old.is_file() and old != target and old.suffix.lower() in ICON_SUFFIXES:
                old.unlink(missing_ok=True)
        part.replace(target)
    except Exception as exc:  # best effort: the profile works without art
        logging.debug("Could not download a profile icon: %s", exc)
        part.unlink(missing_ok=True)
        return ""
    return target.name


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _dir_size(path: Path, limit: int = 5000) -> int:
    total = 0
    count = 0
    try:
        for item in path.rglob("*"):
            if count >= limit or not item.is_file():
                continue
            count += 1
            try:
                total += item.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def _mtime_label(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M")
    except OSError:
        return ""


def _pack_entries(folder: Path) -> list:
    items = []
    if not folder.is_dir():
        return items
    try:
        children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return items
    for path in children:
        if path.is_dir():
            items.append({"name": path.name, "kind": "folder",
                          "size": _dir_size(path),
                          "modified": _mtime_label(path)})
        elif path.is_file() and path.suffix.lower() in (".zip", ".jar"):
            items.append({"name": path.name, "kind": "file",
                          "size": _file_size(path),
                          "modified": _mtime_label(path)})
    return items


def instance_contents(root: Path) -> dict:
    """Mods, packs, worlds and screenshots of one isolated profile."""
    root = Path(root)
    game = instance_game_dir(root)
    state = read_mods_state(root)
    tracked = {}
    for pid, entry in state.items():
        if isinstance(entry, dict) and entry.get("filename"):
            tracked[safe_filename(str(entry["filename"]))] = (str(pid), entry)

    cache = read_modrinth_cache(root)
    projects = cache["projects"]
    file_projects = cache["files"]
    jar_cache = cache["jars"]
    cache_before = (len(projects), len(file_projects), dict(jar_cache))

    mods = []
    mods_dir = instance_mods_dir(root)
    if mods_dir.is_dir():
        try:
            jars = sorted(mods_dir.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            jars = []
        for path in jars:
            if not path.is_file() or path.suffix.lower() != ".jar":
                continue
            pid, entry = tracked.get(path.name, ("", {}))
            meta = _jar_meta_cached(path, jar_cache)
            if not pid:
                pid = str(file_projects.get(path.name) or "")
            project = projects.get(pid) if pid else None
            project = project if isinstance(project, dict) else {}
            title = (str(project.get("title") or "")
                     or str(entry.get("title") or "")
                     or str(meta.get("name") or "") or path.stem)
            mods.append({
                "filename": path.name,
                "project_id": pid,
                "slug": str(entry.get("slug") or project.get("slug") or ""),
                "title": title,
                "version": str(entry.get("version_number", "")),
                "tracked": bool(entry),
                "size": _file_size(path),
                "modified": _mtime_label(path),
                "icon": str(meta.get("icon") or ""),
                "icon_url": str(project.get("icon_url") or ""),
            })
    present = {str(item.get("filename") or "") for item in mods}
    for name in list(jar_cache):
        # Forget metadata (and base64 icons) of jars that are gone.
        if name not in present:
            jar_cache.pop(name, None)
    if (len(projects), len(file_projects), jar_cache) != cache_before:
        write_modrinth_cache(root, cache)

    worlds = []
    saves = game / "saves"
    if saves.is_dir():
        try:
            children = sorted(saves.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            children = []
        for path in children:
            if not path.is_dir():
                continue
            level = path / "level.dat"
            worlds.append({
                "name": path.name,
                "size": _dir_size(path),
                "modified": _mtime_label(level if level.is_file() else path),
            })

    screenshots = []
    shots = game / "screenshots"
    if shots.is_dir():
        try:
            files = [item for item in shots.iterdir()
                     if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES]
        except OSError:
            files = []
        files.sort(key=lambda item: _file_size(item), reverse=True)
        for path in files[:160]:
            try:
                url = path.resolve().as_uri()
            except (OSError, ValueError):
                url = ""
            screenshots.append({"name": path.name, "url": url,
                                "size": _file_size(path),
                                "modified": _mtime_label(path)})

    data = {
        "mods": mods,
        "resourcepacks": _pack_entries(game / "resourcepacks"),
        "shaderpacks": _pack_entries(game / "shaderpacks"),
        "worlds": worlds,
        "screenshots": screenshots,
    }
    data["counts"] = {key: len(value) for key, value in data.items()}
    return data


def installed_mod_entry(root: Path, project_id: str, slug: str = "") -> dict:
    """Recorded install for a project, or a best guess from the file name."""
    root = Path(root)
    mods_dir = instance_mods_dir(root)
    entry = read_mods_state(root).get(str(project_id))
    if isinstance(entry, dict) and entry.get("filename"):
        if (mods_dir / safe_filename(entry["filename"])).is_file():
            return entry
    slug = str(slug or "").strip().lower()
    if slug and mods_dir.is_dir():
        # "sodium-fabric-0.6.jar" -> Sodium, but not "sodium-extra-…".
        pattern = re.compile(
            r"^" + re.escape(slug)
            + r"(?:-(?:fabric|forge|neoforge|quilt|common)|[-_]\d)")
        for path in sorted(mods_dir.glob("*.jar")):
            if pattern.match(path.name.lower()):
                return {"filename": path.name, "version_id": "",
                        "version_number": "", "slug": slug}
    return {}


def mod_state_entry(version: dict, file: dict, project: str, slug="",
                    title="") -> dict:
    return {
        "filename": safe_filename(file.get("filename", "mod.jar")),
        "version_id": str(version.get("id") or ""),
        "version_number": str(version.get("version_number") or ""),
        "date_published": str(version.get("date_published") or ""),
        "project_id": str(project),
        "slug": str(slug or ""),
        "title": str(title or version.get("name") or ""),
    }


PACK_STATE_FILE = "installed_packs.json"


PACK_DIRS = {"resourcepack": "resourcepacks", "shader": "shaderpacks"}


PACK_LABELS = {"resourcepack": "resource pack", "shader": "shader pack"}


def read_packs_state(root: Path) -> dict:
    """kind -> {project_id: {filename, version_id, …}} for packs we installed."""
    try:
        data = json.loads((Path(root) / PACK_STATE_FILE)
                          .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_packs_state(root: Path, data: dict):
    try:
        (Path(root) / PACK_STATE_FILE).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def instance_pack_dir(root: Path, kind: str) -> Path:
    return instance_game_dir(root) / PACK_DIRS.get(kind, "resourcepacks")


def installed_pack_entry(root: Path, kind: str, project_id: str,
                         slug: str = "") -> dict:
    """Recorded install for a resource/shader pack, or a file-name guess."""
    root = Path(root)
    folder = instance_pack_dir(root, kind)
    state = read_packs_state(root)
    bucket = state.get(kind)
    entry = (bucket.get(str(project_id))
             if isinstance(bucket, dict) else None)
    if isinstance(entry, dict) and entry.get("filename"):
        if (folder / safe_filename(entry["filename"])).is_file():
            return entry
    slug = str(slug or "").strip().lower()
    if slug and folder.is_dir():
        pattern = re.compile(
            r"^" + re.escape(slug) + r"(?:[-_]\d|\.(?:zip|jar)$)")
        try:
            children = sorted(folder.iterdir())
        except OSError:
            children = []
        for path in children:
            if (path.is_file()
                    and path.suffix.lower() in (".zip", ".jar")
                    and pattern.match(path.name.lower())):
                return {"filename": path.name, "version_id": "",
                        "version_number": "", "slug": slug}
    return {}


def instance_log_file(root: Path) -> Path:
    return instance_game_dir(root) / "logs" / "latest.log"


def read_instance(root: Path):
    try:
        data = json.loads((Path(root) / "instance.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("version"):
        return None
    data["name"] = str(data.get("name") or Path(root).name)
    data["_root"] = Path(root)
    data["_slug"] = Path(root).name
    return data


def list_instances():
    found = []
    if not INSTANCES_DIR.is_dir():
        return found
    for entry in INSTANCES_DIR.iterdir():
        if not entry.is_dir():
            continue
        data = read_instance(entry)
        if data is not None:
            found.append(data)
    found.sort(key=lambda item: item["name"].lower())
    return found


def write_instance(root: Path, data: dict):
    payload = {key: value for key, value in data.items() if not key.startswith("_")}
    try:
        (Path(root) / "instance.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def create_instance(name: str, version_id: str, ram=None):
    """Make a new isolated profile folder; nothing is copied from .minecraft."""
    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    taken = {entry.name.lower() for entry in INSTANCES_DIR.iterdir() if entry.is_dir()}
    slug = _instance_slug(name, taken)
    root = INSTANCES_DIR / slug
    root.mkdir(parents=True, exist_ok=True)
    instance_game_dir(root).mkdir(parents=True, exist_ok=True)
    data = {
        "name": name.strip() or slug,
        "version": version_id,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    if ram is not None:
        data["ram"] = int(ram)
    write_instance(root, data)
    data["_root"] = root
    data["_slug"] = slug
    return data


def delete_instance(root: Path):
    shutil.rmtree(Path(root), ignore_errors=True)


def instance_base_version(data: dict) -> str:
    return game_version_of(version_meta(str(data.get("version", ""))))


def instance_label(data: dict) -> str:
    name = data.get("name") or data.get("_slug", "")
    version = str(data.get("version", ""))
    return name if name == version else f"{name}  ·  {version}"


def profile_loader_version(version_id: str, loader_key: str,
                           base: str = "") -> str:
    """The loader build encoded in a profile id ("fabric-loader-0.16-1.21")."""
    vid = str(version_id or "")
    if not vid:
        return ""
    if loader_key in ("fabric", "quilt"):
        match = re.match(
            r"(?:fabric|quilt)-loader-(.+?)(?:-" + re.escape(base) + r")?$",
            vid, re.IGNORECASE)
        return match.group(1) if match else ""
    if loader_key == "forge":
        match = re.search(r"-forge-(.+)$", vid, re.IGNORECASE)
        return match.group(1) if match else ""
    if loader_key == "neoforge":
        match = re.match(r"neoforge-(.+)$", vid, re.IGNORECASE)
        return match.group(1) if match else ""
    return ""


DUPLICATE_SKIP = {"saves", "backups", "logs", "crash-reports", "screenshots"}


def duplicate_instance(root: Path) -> dict:
    """Copy a profile's mods and configs into a new folder (no worlds/logs)."""
    source = Path(root)
    data = read_instance(source) or {}
    name = f'{data.get("name") or source.name} (copy)'
    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    taken = {entry.name.lower() for entry in INSTANCES_DIR.iterdir()
             if entry.is_dir()}
    slug = _instance_slug(name, taken)
    target = INSTANCES_DIR / slug

    def ignore(directory, names):
        if Path(directory) == instance_game_dir(source):
            return {name for name in names if name.lower() in DUPLICATE_SKIP}
        return set()

    shutil.copytree(instance_game_dir(source), instance_game_dir(target),
                    ignore=ignore)
    for item in source.iterdir():
        if item.name in ("instance.json", "minecraft"):
            continue
        if item.name.lower() in DUPLICATE_SKIP:
            continue
        destination = target / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
        except OSError:
            pass
    payload = {key: value for key, value in data.items()
               if not key.startswith("_")}
    payload["name"] = name
    payload["created"] = datetime.now().isoformat(timespec="seconds")
    write_instance(target, payload)
    payload["_root"] = target
    payload["_slug"] = slug
    return payload


def backup_instance_worlds(root: Path) -> dict:
    """Zip the profile's saves folder into <instance>/backups/."""
    saves = instance_game_dir(root) / "saves"
    if not saves.is_dir():
        raise RuntimeError("This profile has no worlds to back up yet.")
    worlds = list(saves.iterdir())
    if not worlds:
        raise RuntimeError("This profile has no worlds to back up yet.")
    backups = Path(root) / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups / f"worlds-{stamp}.zip"
    files = 0
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in saves.rglob("*"):
                if path.is_file():
                    archive.write(path, Path("saves") / path.relative_to(saves))
                    files += 1
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return {"path": target, "worlds": len(worlds), "files": files}
