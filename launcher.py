"""Nexi Launcher — minimal Minecraft launcher.

Isolated Prism-style profiles, Mojang version downloads, Fabric/Forge/NeoForge
installers and a Modrinth mod browser. The interface is HTML/CSS/JS rendered
by pywebview; this module is the backend and its JS bridge. Accounts: Microsoft
(device-code OAuth), Ely.by (Yggdrasil, with authlib-injector at launch) and
offline mode.
"""

import base64
import hashlib
import http.server
import inspect
import json
import logging
import os
import platform
import queue
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "Nexi Launcher"


def app_dir() -> Path:
    """Folder that holds the exe (frozen) or this script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


LOG_DIR = app_dir() / "logs"
LOG_FILE = LOG_DIR / "launcher.log"

log = logging.getLogger("launcher")


class _LogStream:
    """Send stray prints and tracebacks to the log (windowed exe has no console)."""

    def __init__(self, level):
        self._level = level

    def write(self, text):
        text = str(text).rstrip()
        if text:
            log.log(self._level, "%s", text)

    def flush(self):
        pass

    def isatty(self):
        return False


def setup_logging():
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        logging.getLogger("pywebview").setLevel(logging.DEBUG)
        logging.raiseExceptions = False
    except OSError:
        pass
    sys.stdout = _LogStream(logging.INFO)
    sys.stderr = _LogStream(logging.ERROR)

    def handle_exception(exc_type, exc, tb):
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = handle_exception

    def handle_thread_exception(args):
        name = args.thread.name if args.thread else "?"
        log.critical("Uncaught exception in thread %s", name,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = handle_thread_exception
    log.info("=== launcher start: python %s, frozen=%s, log=%s ===",
             sys.version.split()[0], bool(getattr(sys, "frozen", False)),
             LOG_FILE)


# Set from the Settings screen; empty means "use the bundled/automatic Java".
JAVA_OVERRIDE = ""

OS_NAME = {"Windows": "windows", "Linux": "linux", "Darwin": "osx"}.get(
    platform.system(), "linux"
)
ARCH = "x86" if platform.architecture()[0] == "32bit" else "x64"


def minecraft_dir() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / ".minecraft"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "minecraft"
    return Path.home() / ".minecraft"


MC = minecraft_dir()


# ---------------------------------------------------------------------------
# Version scanning
# ---------------------------------------------------------------------------

def list_versions():
    """Return playable versions: (id, json path), newest first."""
    root = MC / "versions"
    found = []
    if not root.is_dir():
        return found
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = entry / f"{entry.name}.json"
        if not meta.is_file():
            meta = next(entry.glob("*.json"), None)
        if meta is None:
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "mainClass" not in data and "inheritsFrom" not in data:
            continue
        found.append((data.get("id", entry.name), meta, data.get("releaseTime", "")))
    found.sort(key=lambda item: item[2], reverse=True)
    return [(vid, meta) for vid, meta, _ in found]


def version_meta(version_id: str) -> Path:
    """Path of a version's JSON, tolerating a differently named file."""
    folder = MC / "versions" / version_id
    meta = folder / f"{version_id}.json"
    if meta.is_file():
        return meta
    if folder.is_dir():
        candidate = next(folder.glob("*.json"), None)
        if candidate is not None:
            return candidate
    return meta


def load_version(meta: Path) -> dict:
    """Load a version JSON, merging a parent version if it inherits one."""
    data = json.loads(Path(meta).read_text(encoding="utf-8"))
    parent_id = data.get("inheritsFrom")
    if not parent_id:
        return data
    parent = load_version(version_meta(parent_id))

    merged = dict(parent)
    for key in ("id", "mainClass", "assets", "assetIndex", "minecraftArguments",
                "javaVersion", "jar", "logging", "complianceLevel", "type"):
        if key in data:
            merged[key] = data[key]
    merged["libraries"] = parent.get("libraries", []) + data.get("libraries", [])

    # A loader profile has no client jar of its own — it launches the jar of
    # the base version it inherits from.
    if "jar" not in merged:
        merged["jar"] = parent_id

    if "arguments" in data or "arguments" in parent:
        merged["arguments"] = {
            "game": _arg_list(parent, "game") + _arg_list(data, "game"),
            "jvm": _arg_list(parent, "jvm") + _arg_list(data, "jvm"),
        }
    return merged


def _arg_list(data: dict, side: str):
    return list((data.get("arguments") or {}).get(side, []))


# ---------------------------------------------------------------------------
# Launch command
# ---------------------------------------------------------------------------

def rule_allows(rules, features=None) -> bool:
    if not rules:
        return True
    allowed = False
    for rule in rules:
        os_req = rule.get("os")
        feat_req = rule.get("features")
        matches = True
        if os_req:
            if "name" in os_req and os_req["name"] != OS_NAME:
                matches = False
            if "arch" in os_req and os_req["arch"] != ARCH:
                matches = False
        if feat_req:
            features = features or {}
            if any(features.get(name) != value for name, value in feat_req.items()):
                matches = False
        if matches:
            allowed = rule.get("action") == "allow"
    return allowed


def library_path(name: str) -> Path:
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    file_name = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "") + ".jar"
    return MC / "libraries" / group.replace(".", "/") / artifact / version / file_name


def _classifier(lib: dict):
    parts = lib.get("name", "").split(":")
    return parts[3] if len(parts) > 3 else ""


def _for_this_machine(lib: dict) -> bool:
    """Native jars are often gated by OS only, so the arch lives in the name."""
    classifier = _classifier(lib)
    if not classifier:
        return True
    if OS_NAME == "windows":
        if "linux" in classifier or "macos" in classifier or classifier.endswith("-osx"):
            return False
        if classifier.endswith("-x86") and ARCH != "x86":
            return False
        if "arm64" in classifier:
            return False
    return True


def _artifact_path(lib: dict):
    """Path of a library's plain jar, ignoring native-only classifiers."""
    downloads = lib.get("downloads") or {}
    artifact = downloads.get("artifact")
    if artifact and artifact.get("path"):
        return MC / "libraries" / artifact["path"]
    if "name" in lib and not lib.get("natives"):
        return library_path(lib["name"])
    return None


def collect_classpath(version: dict):
    jars = []
    missing = []
    seen = set()
    for lib in version.get("libraries", []):
        if not rule_allows(lib.get("rules")) or not _for_this_machine(lib):
            continue
        path = _artifact_path(lib)
        if path is None:
            continue
        # NeoForge/Forge JSONs list some vanilla libraries twice; a duplicate
        # classpath entry makes BootstrapLauncher die with "Duplicate key".
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            jars.append(path)
        else:
            missing.append(path.name)
    return jars, missing


def client_jar(version: dict, meta: Path) -> Path:
    jar_id = version.get("jar") or version.get("id")
    candidate = MC / "versions" / jar_id / f"{jar_id}.jar"
    if candidate.is_file():
        return candidate
    sibling = Path(meta).with_suffix(".jar")
    if sibling.is_file():
        return sibling
    return candidate


def natives_dir(version_id: str) -> Path:
    target = MC / "versions" / version_id / "natives"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _native_matches(classifier: str) -> bool:
    """True if a natives-* classifier belongs to this OS and CPU arch."""
    if not classifier.startswith("natives-"):
        return False
    rest = classifier[len("natives-"):]
    os_name = rest.split("-")[0]
    if os_name == "macos":
        os_name = "osx"
    if os_name != OS_NAME:
        return False
    if OS_NAME == "windows":
        arch = rest[len("natives-windows"):]
        return arch in ("", "-x64") if ARCH == "x64" else arch in ("", "-x86")
    if OS_NAME == "linux":
        arch = rest[len("natives-linux"):]
        return arch in ("", "-x64") if ARCH == "x64" else arch in ("", "-x86")
    return True


def extract_natives(version: dict, version_id: str):
    """Unpack native libraries, supporting both old (natives map) and
    new (natives-<os> classifier library) JSON formats."""
    target = natives_dir(version_id)
    for lib in version.get("libraries", []):
        if not rule_allows(lib.get("rules")):
            continue
        jar = None
        classifier = _classifier(lib)
        if classifier and _native_matches(classifier):
            # modern LWJGL3: the artifact itself is a natives jar
            downloads = lib.get("downloads") or {}
            artifact = downloads.get("artifact")
            if artifact and artifact.get("path"):
                jar = MC / "libraries" / artifact["path"]
            else:
                jar = library_path(lib["name"])
        else:
            # legacy: "natives" field picks the platform classifier
            natives = lib.get("natives")
            if not natives:
                continue
            native_cls = natives.get(OS_NAME)
            if not native_cls:
                continue
            native_cls = native_cls.replace("${arch}", "64" if ARCH == "x64" else "32")
            downloads = lib.get("downloads") or {}
            classified = (downloads.get("classifiers") or {}).get(native_cls)
            if classified and classified.get("path"):
                jar = MC / "libraries" / classified["path"]
            else:
                jar = library_path(lib["name"] + ":" + native_cls)
        if jar is None or not jar.is_file():
            continue
        exclude = set((lib.get("extract") or {}).get("exclude", []))
        with zipfile.ZipFile(jar) as archive:
            for info in archive.infolist():
                name = info.filename
                if info.is_dir() or name.startswith("META-INF"):
                    continue
                if any(name.startswith(prefix) for prefix in exclude):
                    continue
                archive.extract(info, target)
    return target


def java_executable(version: dict) -> str:
    if JAVA_OVERRIDE:
        return JAVA_OVERRIDE
    component = (version.get("javaVersion") or {}).get("component", "")
    runtime = MC / "runtime" / component
    if component and runtime.is_dir():
        for javaw in runtime.rglob("javaw.exe" if platform.system() == "Windows" else "java"):
            if javaw.is_file():
                return str(javaw)
    found = shutil.which("javaw") or shutil.which("java")
    if found:
        return found
    return "javaw" if platform.system() == "Windows" else "java"


def expand_arg(value, variables: dict):
    text = value
    for key, replacement in variables.items():
        text = text.replace("${" + key + "}", replacement)
    return text


def _materialize_assets(objects: dict, root: Path):
    """Copy index objects to their plain names (legacy/virtual layouts)."""
    for name, obj in objects.items():
        parts = Path(str(name)).parts
        if not parts or ".." in parts:
            continue
        digest = str(obj.get("hash") or "")
        if len(digest) < 2:
            continue
        source = MC / "assets" / "objects" / digest[:2] / digest
        target = root / name
        try:
            if (target.is_file()
                    and target.stat().st_size == int(obj.get("size") or 0)):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        except (OSError, ValueError):
            continue


def prepare_legacy_assets(version: dict, game_dir: Path) -> Path:
    """Assets dir for the game, materialising the pre-1.7 layouts.

    Very old versions read sounds from <game_dir>/resources
    (``map_to_resources``); 1.6–1.6.4 expect plain asset names in a
    ``virtual/<index>`` folder.
    """
    index_id = ((version.get("assetIndex") or {}).get("id")
                or version.get("assets") or "")
    if not index_id:
        return MC / "assets"
    index_path = MC / "assets" / "indexes" / f"{index_id}.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MC / "assets"
    objects = index.get("objects") or {}
    if not objects:
        return MC / "assets"
    if index.get("map_to_resources"):
        _materialize_assets(objects, Path(game_dir) / "resources")
        return MC / "assets"
    if index.get("virtual"):
        virtual = MC / "assets" / "virtual" / index_id
        _materialize_assets(objects, virtual)
        return virtual
    return MC / "assets"


def build_command(version: dict, meta: Path, player: str, ram_gb: int,
                  game_dir: Path = None, auth: dict = None):
    version_id = version.get("id", Path(meta).stem)
    jars, missing = collect_classpath(version)
    client = client_jar(version, meta)
    if not client.is_file():
        missing.append(client.name)
    natives = extract_natives(version, version_id)
    game_directory = Path(game_dir) if game_dir else MC
    assets_root = prepare_legacy_assets(version, game_directory)

    classpath = os.pathsep.join(str(jar) for jar in jars + [client])
    player_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:" + player))
    variables = {
        "natives_directory": str(natives),
        "launcher_name": APP_NAME,
        "launcher_version": "1",
        "classpath": classpath,
        "auth_player_name": player,
        "version_name": version_id,
        "game_directory": str(game_directory),
        "assets_root": str(assets_root),
        "game_assets": str(assets_root),
        "assets_index_name": (version.get("assetIndex") or {}).get("id")
        or version.get("assets", ""),
        "auth_uuid": player_uuid,
        "auth_access_token": "0",
        "auth_session": "0",
        "user_type": "legacy",
        "version_type": version.get("type", "release"),
        "user_properties": "{}",
        "clientid": "0",
        "auth_xuid": "0",
        "classpath_separator": os.pathsep,
        "library_directory": str(MC / "libraries"),
    }
    if auth:
        variables.update({
            "auth_player_name": str(auth.get("name") or player),
            "auth_uuid": str(auth.get("uuid") or ""),
            "auth_access_token": str(auth.get("token") or ""),
            # Pre-1.6.x versions take the token as the legacy session id.
            "auth_session": str(auth.get("token") or "0"),
            "user_type": "mojang" if auth.get("kind") == "ely" else "msa",
            "auth_xuid": str(auth.get("xuid") or "0"),
        })

    command = [java_executable(version), f"-Xmx{ram_gb}G", f"-Xms{ram_gb}G"]
    if auth and auth.get("authlib"):
        # Redirects the game's session/skin servers to Ely.by.
        command.append(f"-javaagent:{auth['authlib']}={ELY_JAVA_AGENT}")

    if "arguments" in version:
        for entry in version["arguments"].get("jvm", []):
            command += _resolved(entry, variables)
    else:
        command += [
            f"-Djava.library.path={natives}",
            "-cp", classpath,
        ]

    # NeoForge JSONs set "-DignoreList=client-extra,<loader>.jar" because the
    # official launcher keeps the client jar under the loader's version name.
    # We launch the base version's jar instead, so name it here too: otherwise
    # securejarhandler treats the vanilla jar as a second module that also
    # exports net.minecraft.server.
    client_name = client.name
    for index, arg in enumerate(command):
        if not arg.startswith("-DignoreList="):
            continue
        entries = [item for item in arg[len("-DignoreList="):].split(",") if item]
        if client_name not in entries:
            entries.append(client_name)
        command[index] = "-DignoreList=" + ",".join(entries)

    command.append(version["mainClass"])

    if "arguments" in version:
        for entry in version["arguments"].get("game", []):
            command += _resolved(entry, variables)
    else:
        for token in version.get("minecraftArguments", "").split():
            command.append(expand_arg(token, variables))

    return command, missing


def _resolved(entry, variables):
    if isinstance(entry, str):
        return [expand_arg(entry, variables)]
    if isinstance(entry, dict) and rule_allows(entry.get("rules")):
        value = entry.get("value", [])
        values = value if isinstance(value, list) else [value]
        return [expand_arg(item, variables) for item in values]
    return []


# ---------------------------------------------------------------------------
# Modrinth
# ---------------------------------------------------------------------------

MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "NexiLauncher/1.1 (local launcher, no account)"
LOADERS = ("any", "fabric", "forge", "neoforge", "quilt")


def modrinth_get(path: str, params=None, timeout: float = 20):
    url = MODRINTH_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            "Modrinth is unreachable from this network — check the "
            f"connection or a VPN ({reason})") from exc


def search_modrinth(query: str, game_version: str, loader: str,
                    project_type: str = "mod", offset: int = 0,
                    limit: int = 30):
    """(hits, total_hits) — Modrinth search is paginated by offset."""
    facets = [[f"project_type:{project_type}"]]
    if project_type == "modpack":
        game_version = ""
    if game_version:
        facets.append([f"versions:{game_version}"])
    if project_type == "mod" and loader and loader != "any":
        facets.append([f"categories:{loader}"])
    params = {
        "query": query,
        "limit": max(1, min(int(limit), 100)),
        "index": "relevance",
        "facets": json.dumps(facets),
    }
    if offset:
        params["offset"] = max(0, int(offset))
    data = modrinth_get("/search", params)
    return data.get("hits", []), int(data.get("total_hits") or 0)


def mod_versions(project_id: str, game_version: str, loader: str,
                 project_type: str = "mod"):
    params = {}
    if game_version and project_type != "modpack":
        params["game_versions"] = json.dumps([game_version])
    if project_type == "mod" and loader and loader != "any":
        params["loaders"] = json.dumps([loader])
    versions = modrinth_get(f"/project/{project_id}/version", params)
    versions.sort(
        key=lambda v: (v.get("version_type") == "release", v.get("date_published", "")),
        reverse=True,
    )
    return versions


def primary_file(version: dict):
    files = version.get("files") or []
    for file in files:
        if file.get("primary"):
            return file
    for file in files:
        if str(file.get("filename", "")).lower().endswith(".jar"):
            return file
    return files[0] if files else None


def required_dependencies(version: dict):
    return [dep for dep in version.get("dependencies") or []
            if dep.get("dependency_type") == "required"]


def resolve_dependency(dep: dict, game_version: str, loader: str):
    """Look up the version to install for a required dependency, if possible."""
    version_id = dep.get("version_id")
    if version_id:
        try:
            return modrinth_get(f"/version/{version_id}")
        except (OSError, ValueError, urllib.error.HTTPError):
            return None
    project_id = dep.get("project_id")
    if not project_id:
        return None
    try:
        versions = mod_versions(project_id, game_version, loader)
    except (OSError, ValueError, urllib.error.HTTPError):
        return None
    return versions[0] if versions else None


def safe_filename(name: str) -> str:
    base = Path(str(name)).name
    return base if base else "mod.jar"


def download_file(url: str, target: Path, size=None, cancel=None):
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    if size:
        try:
            if target.is_file() and target.stat().st_size == int(size):
                return
        except OSError:
            pass
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    target = Path(target)
    # On a clean PC the libraries/assets folders do not exist yet.
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=90) as response, \
                part.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def format_count(value) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return str(value)
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def game_version_of(meta: Path) -> str:
    """The vanilla version a profile is based on (inheritsFrom for modpacks)."""
    try:
        data = json.loads(Path(meta).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Path(meta).stem
    return str(data.get("inheritsFrom") or data.get("id") or Path(meta).stem)


def detect_loader(version: dict) -> str:
    blob = " ".join(
        [str(version.get("id", "")), str(version.get("inheritsFrom", "")),
         str(version.get("jar", ""))]
        + [str(lib.get("name", "")) for lib in version.get("libraries", [])]
    ).lower()
    for loader in ("neoforge", "fabric", "quilt", "forge"):
        if loader in blob:
            return loader
    return "any"


# ---------------------------------------------------------------------------
# Instances (isolated profiles)
# ---------------------------------------------------------------------------

INSTANCES_DIR = MC / "instances"


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



# ---------------------------------------------------------------------------
# Mod loaders
# ---------------------------------------------------------------------------

FABRIC_META = "https://meta.fabricmc.net/v2"
FORGE_PROMOTIONS = ("https://files.minecraftforge.net/net/minecraftforge/"
                    "forge/promotions_slim.json")
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_METADATA = FORGE_MAVEN + "/maven-metadata.xml"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
NEOFORGE_METADATA = NEOFORGE_MAVEN + "/maven-metadata.xml"
NEOFORGE_LEGACY_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/forge"
NEOFORGE_LEGACY_METADATA = NEOFORGE_LEGACY_MAVEN + "/maven-metadata.xml"

LOADER_KEYS = {"Fabric": "fabric", "Forge": "forge", "NeoForge": "neoforge"}
MAX_BUILDS = 20


def http_get(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def maven_path(coordinate: str) -> Path:
    """Relative library path for a Gradle-style coordinate."""
    extension = "jar"
    if "@" in coordinate:
        coordinate, extension = coordinate.split("@", 1)
    parts = coordinate.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else ""
    filename = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "")
    return Path(*group.split("."), artifact, version, f"{filename}.{extension}")


def _maven_versions(url: str):
    root = ET.fromstring(http_get(url))
    found = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "version" and element.text:
            found.append(element.text.strip())
    return found


def _versions_of_game(all_versions, game_version: str):
    """Maven versions whose coordinate embeds the game version."""
    direct = [v for v in all_versions
              if v == game_version or v.startswith(game_version + "-")]
    if direct:
        return list(reversed(direct))
    embedded = [v for v in all_versions
                if f"-{game_version}-" in v or v.endswith("-" + game_version)]
    return list(reversed(embedded))


def _is_legacy_neoforge(game_version: str) -> bool:
    base = game_version.split("-")[0].strip()
    return base.startswith(("1.16", "1.17", "1.18", "1.19")) or base == "1.20.1"


def neoforge_prefixes(game_version: str):
    """NeoForge release versions are numbered after the game version:
    1.21.1 -> 21.1.x, 1.20.4 -> 20.4.x, 1.21 -> 21.0.x."""
    base = game_version.split("-")[0].strip()
    parts = base.split(".")
    if parts[0] == "1" and len(parts) >= 2:
        patch = parts[2] if len(parts) > 2 else "0"
        return [f"{parts[1]}.{patch}."]
    return [base + "."]


def fabric_builds(game_version: str):
    """(value, label) pairs, newest first."""
    url = (f"{FABRIC_META}/versions/loader/"
           f"{urllib.parse.quote(game_version, safe='')}")
    data = json.loads(http_get(url).decode("utf-8"))
    builds = []
    for entry in data:
        loader = entry.get("loader") or {}
        version = loader.get("version")
        if not version:
            continue
        label = f"{version}  · stable" if loader.get("stable") else version
        builds.append((version, label))
        if len(builds) >= MAX_BUILDS:
            break
    return builds


def forge_builds(game_version: str):
    try:
        promotions = json.loads(http_get(FORGE_PROMOTIONS, timeout=20).decode("utf-8"))
    except (OSError, ValueError):
        promotions = {}
    table = promotions.get("promos") or {}
    picks = []
    seen = set()
    for channel in ("recommended", "latest"):
        value = table.get(f"{game_version}-{channel}")
        if value and value not in seen:
            seen.add(value)
            picks.append((value, f"{value}  · {channel}"))
    if picks:
        return picks
    try:
        versions = _versions_of_game(_maven_versions(FORGE_METADATA), game_version)
    except (OSError, ValueError, ET.ParseError):
        return []
    return [(value, value) for value in versions[:MAX_BUILDS]]


def neoforge_builds(game_version: str):
    if _is_legacy_neoforge(game_version):
        try:
            versions = _versions_of_game(
                _maven_versions(NEOFORGE_LEGACY_METADATA), game_version)
        except (OSError, ValueError, ET.ParseError):
            return []
        return [(value, value) for value in versions[:MAX_BUILDS]]
    try:
        all_versions = _maven_versions(NEOFORGE_METADATA)
    except (OSError, ValueError, ET.ParseError):
        return []
    for prefix in neoforge_prefixes(game_version):
        matching = [v for v in all_versions if v.startswith(prefix)]
        if not matching:
            continue
        stable = [v for v in matching if "-beta" not in v.lower()]
        chosen = list(reversed(stable or matching))[:MAX_BUILDS]
        return [(value, value) for value in chosen]
    return []


def loader_builds(loader_key: str, game_version: str):
    if loader_key == "fabric":
        return fabric_builds(game_version)
    if loader_key == "forge":
        return forge_builds(game_version)
    return neoforge_builds(game_version)


def loader_installer_url(loader_key: str, game_version: str, loader_version: str) -> str:
    if loader_key == "forge":
        version = (loader_version if loader_version.startswith(game_version + "-")
                   else f"{game_version}-{loader_version}")
        return f"{FORGE_MAVEN}/{version}/forge-{version}-installer.jar"
    if _is_legacy_neoforge(game_version):
        version = (loader_version if loader_version.startswith(game_version + "-")
                   else f"{game_version}-{loader_version}")
        return f"{NEOFORGE_LEGACY_MAVEN}/{version}/forge-{version}-installer.jar"
    return (f"{NEOFORGE_MAVEN}/{loader_version}/"
            f"neoforge-{loader_version}-installer.jar")


def console_java(version: dict) -> str:
    """The console build of Java — installers print progress to stdout."""
    exe = java_executable(version)
    if exe == "javaw":
        return "java"
    path = Path(exe)
    if path.name.lower() == "javaw.exe":
        candidate = path.with_name("java.exe")
        if candidate.is_file():
            return str(candidate)
    return exe


def installed_version_ids():
    return {vid for vid, _meta in list_versions()}


def vanilla_versions():
    """Installed versions that are not mod-loader profiles themselves."""
    found = []
    for vid, meta in list_versions():
        try:
            data = json.loads(Path(meta).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not data.get("inheritsFrom"):
            found.append(vid)
    return found


def ensure_launcher_profiles():
    """Forge-style installers want a launcher_profiles.json to exist."""
    target = MC / "launcher_profiles.json"
    if target.is_file():
        return
    try:
        target.write_text(
            json.dumps({"profiles": {}, "settings": {}, "version": 3}, indent=2),
            encoding="utf-8")
    except OSError:
        pass


def run_installer(java: str, installer: Path, log) -> None:
    ensure_launcher_profiles()
    arguments = [java]
    if platform.system() == "Windows" and "jre-legacy" in str(java).lower():
        # The bundled Java 8 runtime ships an outdated root CA list, so the
        # installer's connectivity check fails without the Windows store.
        arguments.append("-Djavax.net.ssl.trustStoreType=WINDOWS-ROOT")
    arguments += ["-Djava.awt.headless=true", "-jar", str(installer),
                  "--installClient", str(MC)]
    log("Running: " + " ".join(arguments))
    process = subprocess.Popen(
        arguments, cwd=str(MC), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    stream = process.stdout
    if stream is not None:
        for raw in stream:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                log(line)
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"installer exited with code {code}")


def install_fabric(game_version: str, loader_version: str, log) -> str:
    url = (f"{FABRIC_META}/versions/loader/"
           f"{urllib.parse.quote(game_version, safe='')}/"
           f"{urllib.parse.quote(loader_version, safe='')}/profile/json")
    log(f"Fetching Fabric {loader_version} profile for {game_version}…")
    profile = json.loads(http_get(url).decode("utf-8"))
    version_id = profile.get("id") or f"fabric-loader-{loader_version}-{game_version}"
    profile["id"] = version_id
    profile.setdefault("inheritsFrom", game_version)
    profile.setdefault("type", "release")

    folder = MC / "versions" / version_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{version_id}.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8")
    log(f"Wrote versions/{version_id}/{version_id}.json")

    for lib in profile.get("libraries") or []:
        name = lib.get("name") or ""
        base_url = lib.get("url")
        if not name or not base_url:
            continue
        relative = maven_path(name)
        target = MC / "libraries" / relative
        if target.is_file():
            continue
        log(f"Downloading {target.name}…")
        target.parent.mkdir(parents=True, exist_ok=True)
        download_file(base_url.rstrip("/") + "/" + relative.as_posix(), target)
    log(f"Fabric profile ready: {version_id}")
    return version_id


def find_loader_profile(loader_key: str, game_version: str, loader_version: str):
    wanted = loader_version.lower()
    for vid, _meta in list_versions():
        low = vid.lower()
        if loader_key == "forge" and "neoforge" in low:
            continue
        if loader_key in low and wanted in low:
            return vid
    return None


def install_loader(loader_key: str, game_version: str, loader_version: str,
                   java: str, log):
    """Install a loader and return the id of the profile it created."""
    if loader_key == "fabric":
        return install_fabric(game_version, loader_version, log)

    before = installed_version_ids()
    url = loader_installer_url(loader_key, game_version, loader_version)
    log(f"Downloading {url}")
    temp_root = Path(tempfile.mkdtemp(prefix="mc-loader-"))
    installer = temp_root / "installer.jar"
    try:
        download_file(url, installer)
        log(f"Installer saved ({installer.stat().st_size // 1024} KB)")
        run_installer(java, installer, log)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    new_ids = sorted(installed_version_ids() - before)
    for vid in new_ids:
        low = vid.lower()
        if loader_key == "neoforge":
            if "neoforge" in low:
                return vid
        elif loader_key in low and "neoforge" not in low:
            return vid
    if new_ids:
        return new_ids[0]
    return find_loader_profile(loader_key, game_version, loader_version)


def console_java_for(version_id: str) -> str:
    """Console Java binary for an installed version id, best effort."""
    meta = version_meta(version_id)
    if not meta.is_file():
        return "java"
    try:
        return console_java(load_version(meta))
    except (OSError, json.JSONDecodeError):
        return "java"


# ---------------------------------------------------------------------------
# Mojang version installer
# ---------------------------------------------------------------------------

VERSION_MANIFEST_URLS = (
    "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
    "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
)
ASSET_OBJECTS_BASE = "https://resources.download.minecraft.net"
MOJANG_LIBRARIES = "https://libraries.minecraft.net"


class InstallCancelled(Exception):
    pass


_manifest_cache = None
_manifest_lock = threading.Lock()


def fetch_version_manifest(force=False):
    """List of {id, type, url, releaseTime} from Mojang's version manifest."""
    global _manifest_cache
    with _manifest_lock:
        if _manifest_cache is not None and not force:
            return _manifest_cache
    last_error = None
    for url in VERSION_MANIFEST_URLS:
        try:
            data = json.loads(http_get(url).decode("utf-8"))
            versions = data.get("versions") or []
            if versions:
                with _manifest_lock:
                    _manifest_cache = versions
                return versions
        except Exception as error:  # network/JSON errors fall through to the next URL
            last_error = error
    if last_error is not None:
        raise last_error
    return []


def manifest_entry(versions, version_id: str):
    for entry in versions or []:
        if entry.get("id") == version_id:
            return entry
    return None


def _library_downloads(data: dict, with_hash: bool = False):
    """(url, path, size[, sha1]) jobs for every library this machine needs."""
    jobs = []
    for lib in data.get("libraries") or []:
        if not rule_allows(lib.get("rules")) or not _for_this_machine(lib):
            continue
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact")
        name = lib.get("name") or ""
        if artifact and artifact.get("url"):
            relative = artifact.get("path")
            if not relative and name:
                relative = maven_path(name).as_posix()
            if relative:
                job = (artifact["url"], MC / "libraries" / relative,
                       artifact.get("size"))
                if with_hash:
                    job += (artifact.get("sha1", ""),)
                jobs.append(job)
        elif name and not lib.get("natives") and not downloads.get("classifiers"):
            # Very old manifests list no downloads at all; plain jars there
            # live on libraries.minecraft.net. A library that only publishes
            # native classifiers has no plain jar — asking for one is a 404.
            base = str(lib.get("url") or MOJANG_LIBRARIES).rstrip("/")
            relative = maven_path(name)
            job = (base + "/" + relative.as_posix(),
                   MC / "libraries" / relative, None)
            if with_hash:
                job += ("",)
            jobs.append(job)

        natives = lib.get("natives") or {}
        native_key = natives.get(OS_NAME) if OS_NAME in natives else None
        if native_key and name:
            native_key = native_key.replace(
                "${arch}", "64" if ARCH == "x64" else "32")
            info = (downloads.get("classifiers") or {}).get(native_key)
            if info and info.get("url"):
                relative = info.get("path") or maven_path(
                    f"{name}:{native_key}").as_posix()
                job = (info["url"], MC / "libraries" / relative,
                       info.get("size"))
                if with_hash:
                    job += (info.get("sha1", ""),)
                jobs.append(job)
    return jobs


def _download_with_retry(url, target, size, cancel):
    """Retry transient network failures; a real 404 is reported at once."""
    for attempt in range(3):
        try:
            download_file(url, target, size, cancel)
            return
        except InstallCancelled:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or attempt == 2:
                raise
        except (urllib.error.URLError, OSError):
            if attempt == 2:
                raise
        time.sleep(0.5 * (attempt + 1))


def _download_many(jobs, log, progress, cancel):
    total = len(jobs)
    if not total:
        return
    log(f"Downloading {total} files…")
    done = 0
    pool = ThreadPoolExecutor(max_workers=min(8, max(1, total)))
    try:
        futures = []
        for url, target, size in jobs:
            if cancel is not None and cancel.is_set():
                raise InstallCancelled()
            futures.append(pool.submit(_download_with_retry, url, target,
                                       size, cancel))
        for future in as_completed(futures):
            future.result()
            done += 1
            if progress and (done == total or done % 10 == 0):
                progress(done, total)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def version_installed(version_id: str) -> bool:
    return version_meta(version_id).is_file()


def install_vanilla(version_id: str, entry, log=lambda _text: None,
                    progress=None, cancel=None) -> dict:
    """Download the client jar, libraries and assets for a Mojang version."""
    if not entry or not entry.get("url"):
        raise RuntimeError(f"No Mojang manifest entry for Minecraft {version_id}.")

    log(f"Downloading version data for {version_id}…")
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    raw = http_get(entry["url"])
    data = json.loads(raw.decode("utf-8"))
    folder = MC / "versions" / version_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{version_id}.json").write_bytes(raw)
    log(f"Saved versions/{version_id}/{version_id}.json")

    jobs = []
    downloads = data.get("downloads") or {}
    client = downloads.get("client")
    if client and client.get("url"):
        jobs.append((client["url"], folder / f"{version_id}.jar",
                     client.get("size")))
    jobs += _library_downloads(data)

    # The asset index is needed before its objects can be listed, so fetch it
    # first (one small file).
    index_info = data.get("assetIndex") or {}
    index_id = index_info.get("id") or data.get("assets")
    index_path = (MC / "assets" / "indexes" / f"{index_id}.json"
                  if index_id else None)
    if index_info.get("url") and index_path is not None:
        _download_many([(index_info["url"], index_path,
                         index_info.get("size"))], log, progress, cancel)

    if index_path is not None and index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}
        objects = index.get("objects") or {}
        for obj in objects.values():
            digest = str(obj.get("hash") or "")
            if len(digest) < 2:
                continue
            target = MC / "assets" / "objects" / digest[:2] / digest
            url = f"{ASSET_OBJECTS_BASE}/{digest[:2]}/{digest}"
            jobs.append((url, target, obj.get("size")))
        if objects:
            log(f"Asset index lists {len(objects)} objects")

    _download_many(jobs, log, progress, cancel)
    log(f"Minecraft {version_id} is installed.")
    return data


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_intact(path, size=None, sha1="") -> bool:
    path = Path(path)
    try:
        if not path.is_file():
            return False
        if size is not None and path.stat().st_size != int(size):
            return False
        if sha1 and _sha1_file(path) != str(sha1).lower():
            return False
        return True
    except (OSError, ValueError):
        return False


def _asset_verify_jobs(data: dict):
    """(url, path, size, sha1) for the asset index and its objects."""
    jobs = []
    index_info = data.get("assetIndex") or {}
    index_id = index_info.get("id") or data.get("assets")
    index_path = (MC / "assets" / "indexes" / f"{index_id}.json"
                  if index_id else None)
    if index_info.get("url") and index_path is not None:
        jobs.append((index_info["url"], index_path,
                     index_info.get("size"), index_info.get("sha1", "")))
    if index_path is not None and index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}
        for obj in (index.get("objects") or {}).values():
            digest = str(obj.get("hash") or "")
            if len(digest) < 2:
                continue
            jobs.append((
                f"{ASSET_OBJECTS_BASE}/{digest[:2]}/{digest}",
                MC / "assets" / "objects" / digest[:2] / digest,
                obj.get("size"), digest))
    return jobs


def _version_verify_jobs(version_id: str):
    # Read the raw file: a merged loader profile would carry the parent's
    # client jar and assets, which belong to the parent version instead.
    data = json.loads(version_meta(version_id).read_text(encoding="utf-8"))
    folder = MC / "versions" / version_id
    jobs = []
    client = (data.get("downloads") or {}).get("client")
    if client and client.get("url"):
        jobs.append((client["url"], folder / f"{version_id}.jar",
                     client.get("size"), client.get("sha1", "")))
    jobs += _library_downloads(data, with_hash=True)
    jobs += _asset_verify_jobs(data)
    return data, jobs


def verify_version_files(version_id: str, log=lambda _text: None,
                         progress=None, cancel=None) -> dict:
    """Check a version and its parent, re-downloading missing/broken files."""
    if not version_meta(version_id).is_file():
        raise RuntimeError(f"Version {version_id} is not installed.")
    version_ids = [version_id]
    data, _jobs = _version_verify_jobs(version_id)
    parent = str(data.get("inheritsFrom") or "")
    if parent and parent != version_id and version_meta(parent).is_file():
        version_ids.append(parent)

    jobs = []
    seen = set()
    for vid in version_ids:
        _data, part = _version_verify_jobs(vid)
        for url, target, size, sha1 in part:
            key = str(target)
            if key in seen:
                continue
            seen.add(key)
            jobs.append((url, target, size, sha1))

    log(f"Checking {len(jobs)} files for {version_id}…")
    missing = []
    for index, (url, target, size, sha1) in enumerate(jobs, 1):
        if cancel is not None and cancel.is_set():
            raise InstallCancelled()
        if not _file_intact(target, size, sha1):
            try:
                Path(target).unlink()
            except OSError:
                pass
            missing.append((url, target, size))
        if progress and (index % 50 == 0 or index == len(jobs)):
            progress(index, len(jobs))

    if missing:
        log(f"{len(missing)} file(s) are missing or damaged — re-downloading.")
        _download_many(missing, log, progress, cancel)
    else:
        log("All files are intact.")
    return {"checked": len(jobs), "fixed": len(missing)}


# ---------------------------------------------------------------------------
# Modpack import (.mrpack and .zip)
# ---------------------------------------------------------------------------

MODPACK_GAME_DIRS = {"mods", "config", "saves", "resourcepacks", "shaderpacks",
                     "scripts", "kubejs", "defaultconfigs", "datapacks"}


def _zip_member_target(base: Path, name: str):
    """Resolve an archive member inside base, or None for unsafe paths."""
    name = str(name or "").replace("\\", "/")
    if not name or name.endswith("/"):
        return None
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    target = Path(base).joinpath(*parts)
    try:
        target.resolve().relative_to(Path(base).resolve())
    except (OSError, ValueError):
        return None
    return target


def _zip_entry_is_link(info) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0o170000)


def _extract_zip(archive, base: Path, prefix: str, log,
                 cancel=None, strip_top=False) -> int:
    """Extract members under prefix into base; returns the file count."""
    prefix = str(prefix or "").strip("/")
    prefix = prefix + "/" if prefix else ""
    entries = []
    for info in archive.infolist():
        if info.is_dir() or _zip_entry_is_link(info):
            continue
        name = info.filename.replace("\\", "/")
        if prefix and not name.startswith(prefix):
            continue
        entries.append((info, name[len(prefix):]))
    if not entries:
        return 0

    strip = ""
    if strip_top and not prefix:
        tops = {relative.split("/")[0] for _info, relative in entries}
        if len(tops) == 1:
            top = next(iter(tops))
            inside = [relative for _info, relative in entries
                      if "/" in relative]
            seconds = {relative.split("/", 1)[1].split("/")[0]
                       for relative in inside}
            if len(inside) == len(entries) and top.lower() not in MODPACK_GAME_DIRS \
                    and seconds & MODPACK_GAME_DIRS:
                strip = top + "/"

    count = 0
    for info, relative in entries:
        if cancel is not None and cancel.is_set():
            raise InstallCancelled()
        if strip:
            if not relative.startswith(strip):
                continue
            relative = relative[len(strip):]
        target = _zip_member_target(base, relative)
        if target is None:
            log(f"SKIP unsafe archive path: {info.filename}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as handle:
            shutil.copyfileobj(source, handle)
        count += 1
    return count


def _modpack_loader(dependencies: dict):
    """(loader_key, loader_version) named in a modpack index, if any."""
    dependencies = dependencies or {}
    for key, loader in (("fabric-loader", "fabric"), ("quilt-loader", "quilt"),
                        ("forge", "forge"), ("neoforge", "neoforge")):
        value = dependencies.get(key)
        if value:
            return loader, str(value)
    return "", ""


def _curseforge_loader(manifest: dict):
    minecraft = (manifest or {}).get("minecraft") or {}
    loaders = minecraft.get("modLoaders") or []
    ordered = sorted(loaders, key=lambda item: not item.get("primary"))
    for item in ordered:
        loader_id = str(item.get("id") or "")
        key, _, value = loader_id.partition("-")
        key = key.lower()
        if key in LOADER_LABELS and value:
            return key, value
    return "", ""


def _download_modpack_files(files, game_dir: Path, log, progress,
                            cancel) -> int:
    jobs = []
    for item in files or []:
        env = item.get("env") or {}
        if str(env.get("client", "")).lower() == "unsupported":
            continue
        urls = item.get("downloads") or []
        if not urls:
            continue
        target = _zip_member_target(game_dir, str(item.get("path") or ""))
        if target is None:
            log(f"SKIP unsafe modpack path: {item.get('path')}")
            continue
        jobs.append((urls[0], target, item.get("fileSize")))
    _download_many(jobs, log, progress, cancel)
    return len(jobs)


def java_available(version_data: dict) -> bool:
    exe = java_executable(version_data)
    if Path(exe).is_file():
        return True
    if exe in ("java", "javaw"):
        return shutil.which("java") is not None or shutil.which("javaw") is not None
    return False


# ---------------------------------------------------------------------------
# Automatic Java runtime download (Mojang's own per-version Java builds)
# ---------------------------------------------------------------------------

JAVA_RUNTIME_MANIFEST_URLS = (
    "https://launchermeta.mojang.com/v1/products/java-runtime/"
    "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json",
    "https://piston-meta.mojang.com/v1/products/java-runtime/"
    "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json",
)
FALLBACK_RUNTIME_COMPONENT = "jre-legacy"

_java_runtime_cache = None
_java_runtime_lock = threading.Lock()
_system_java_major_cache = None


def java_platform_key() -> str:
    """Key into Mojang's java-runtime/all.json for this machine."""
    machine = (platform.machine() or "").lower()
    if OS_NAME == "windows":
        if machine in ("arm64", "aarch64"):
            return "windows-arm64"
        return "windows-x86" if ARCH == "x86" else "windows-x64"
    if OS_NAME == "osx":
        return "mac-os-arm64" if machine in ("arm64", "aarch64") else "mac-os"
    return "linux-i386" if ARCH == "x86" else "linux"


def runtime_java_path(version: dict) -> str:
    """Java binary of this version's Mojang runtime, if it is already here."""
    component = (version.get("javaVersion") or {}).get("component", "")
    if not component:
        return ""
    runtime = MC / "runtime" / component
    if not runtime.is_dir():
        return ""
    names = (("javaw.exe", "java.exe") if platform.system() == "Windows"
             else ("java",))
    for name in names:
        for found in runtime.rglob(name):
            if found.is_file():
                return str(found)
    return ""


def system_java_major() -> int:
    """Major version of the Java on PATH (8 for 1.8), or 0 when there is none."""
    global _system_java_major_cache
    if _system_java_major_cache is not None:
        return _system_java_major_cache
    _system_java_major_cache = 0
    exe = shutil.which("java")
    if not exe:
        return 0
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run([exe, "-version"], capture_output=True,
                                timeout=20, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return 0
    text = (result.stderr or b"").decode("utf-8", "replace")
    match = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not match:
        return 0
    major = int(match.group(1))
    if major == 1 and match.group(2):
        major = int(match.group(2))
    _system_java_major_cache = major
    return major


def _java_runtime_manifest():
    global _java_runtime_cache
    with _java_runtime_lock:
        if _java_runtime_cache is not None:
            return _java_runtime_cache
    errors = []
    for url in JAVA_RUNTIME_MANIFEST_URLS:
        try:
            data = json.loads(http_get(url, timeout=60).decode("utf-8"))
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue
        with _java_runtime_lock:
            _java_runtime_cache = data
        return data
    raise RuntimeError("Could not read Mojang's Java runtime list ("
                       + "; ".join(errors) + ")")


def install_java_runtime(component: str, log=lambda _text: None,
                         progress=None, cancel=None) -> str:
    """Download one Mojang Java runtime (e.g. java-runtime-gamma) into MC."""
    manifest = _java_runtime_manifest()
    platform_key = java_platform_key()
    entries = (manifest.get(platform_key) or {}).get(component) or []
    if not entries:
        raise RuntimeError(f"Mojang has no {component} build for {platform_key}")
    entry = entries[-1]
    runtime_version = str((entry.get("version") or {}).get("name") or component)
    manifest_url = (entry.get("manifest") or {}).get("url")
    if not manifest_url:
        raise RuntimeError(f"Mojang's {component} entry has no download URL")
    log(f"Downloading Java {runtime_version} ({component}). "
        f"This happens once per Java version.")
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    data = json.loads(http_get(manifest_url, timeout=60).decode("utf-8"))
    root = MC / "runtime" / component
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()

    jobs = []
    executable_files = []
    links = []
    for relative, info in (data.get("files") or {}).items():
        kind = info.get("type") or "file"
        target = root / relative
        try:
            inside = target.resolve().is_relative_to(root_resolved)
        except (OSError, ValueError):
            inside = False
        if not inside:
            log(f"Skipping unexpected Java path: {relative}")
            continue
        if kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "link":
            links.append((target, str(info.get("target") or "")))
            continue
        raw_info = (info.get("downloads") or {}).get("raw") or {}
        if not raw_info.get("url"):
            continue
        jobs.append((raw_info["url"], target, raw_info.get("size")))
        if info.get("executable"):
            executable_files.append(target)

    _download_many(jobs, log, progress, cancel)

    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    for target, link in links:
        try:
            target.unlink(missing_ok=True)
            os.symlink(link, target)
        except OSError:
            pass
    for target in executable_files:
        try:
            os.chmod(target, 0o755)
        except OSError:
            pass

    result = ""
    names = (("javaw.exe", "java.exe") if os.name == "nt" else ("java",))
    for name in names:
        for found in root.rglob(name):
            if found.is_file():
                result = str(found)
                break
        if result:
            break
    if not result:
        raise RuntimeError("Java files were downloaded, but no java binary "
                           "was found in them")
    return result


def ensure_java(version: dict, log=lambda _text: None, progress=None,
                cancel=None) -> str:
    """Java for this version: an override, the system Java, or Mojang's build."""
    if JAVA_OVERRIDE:
        return JAVA_OVERRIDE
    existing = runtime_java_path(version)
    if existing:
        return existing

    info = version.get("javaVersion") or {}
    component = str(info.get("component") or FALLBACK_RUNTIME_COMPONENT)
    required = int(info.get("majorVersion") or 8)
    system_major = system_java_major()
    # Only an exact match is trusted: a newer Java often breaks old versions,
    # so anything else gets Mojang's build, exactly like the official launcher.
    if system_major == required:
        found = shutil.which("java") or shutil.which("javaw")
        if found:
            return found

    try:
        path = install_java_runtime(component, log, progress, cancel)
        log(f"Java {required} is ready: {path}")
        return path
    except InstallCancelled:
        raise
    except Exception as exc:
        found = shutil.which("java") or shutil.which("javaw")
        if found:
            log(f"WARNING: could not download Java automatically ({exc}); "
                f"using {found}")
            return found
        raise RuntimeError(
            "No Java runtime is available and the automatic download failed: "
            + str(exc))



# ---------------------------------------------------------------------------
# Interface — pywebview bridge
#
# The window itself is HTML/CSS/JS in webui/. Everything below is the headless
# controller: it keeps launcher state, runs long tasks on pywebview's worker
# threads and streams progress back to the page through a polled event queue.
# ---------------------------------------------------------------------------

LOADER_LABELS = {"fabric": "Fabric", "forge": "Forge", "neoforge": "NeoForge"}
UI_LOADER_KEYS = {"Fabric": "fabric", "Forge": "forge", "NeoForge": "neoforge"}
MAX_LOG_BACKLOG = 200_000


def _version_key(version_id):
    parts = re.split(r"[.\-+]", version_id)
    return [(0, int(part)) if part.isdigit() else (1, part) for part in parts]


def open_in_system(path) -> None:
    """Open a file or folder with the system's default handler."""
    try:
        if os.name == "nt":
            os.startfile(str(path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Microsoft account (device-code OAuth + Xbox Live + Minecraft services)
# ---------------------------------------------------------------------------

MS_SCOPE = "XboxLive.signin offline_access"
# Public Azure app registration used for everyone who runs this launcher.
# A Client ID is not a secret; users do not need to configure anything.
MS_CLIENT_ID_DEFAULT = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"
MS_DEVICE_URL = ("https://login.microsoftonline.com/consumers/"
                 "oauth2/v2.0/devicecode")
MS_TOKEN_URL = ("https://login.microsoftonline.com/consumers/"
                "oauth2/v2.0/token")
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = ("https://api.minecraftservices.com/"
                "authentication/login_with_xbox")
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

XSTS_ERRORS = {
    "2148916233": "This Microsoft account has no Xbox profile. Sign in "
                  "once at xbox.com, then try again.",
    "2148916235": "Xbox Live is not available in this account's country.",
    "2148916236": "This account needs adult verification.",
    "2148916237": "This account needs adult verification.",
    "2148916238": "This is a child account. Ask an adult in your Microsoft "
                  "family to allow it, then try again.",
}


class MSRequestError(Exception):
    """HTTP error returned by Microsoft / Xbox / Minecraft services."""

    def __init__(self, payload):
        self.payload = payload if isinstance(payload, dict) else {}
        detail = (self.payload.get("error_description")
                  or self.payload.get("error") or "Request failed")
        super().__init__(detail)


def _http_json(url, payload=None, token=None, timeout=30, form=False):
    if payload is None:
        data = None
    elif form:
        data = urllib.parse.urlencode(payload).encode("utf-8")
    else:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header(
            "Content-Type", "application/x-www-form-urlencoded" if form
            else "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        parsed.setdefault("error", f"HTTP {exc.code}")
        parsed.setdefault(
            "error_description",
            parsed.get("errorMessage") or raw or f"HTTP {exc.code}")
        parsed["http_status"] = exc.code
        raise MSRequestError(parsed) from None
    return json.loads(body) if body else {}


def xbox_authenticate(ms_access_token):
    """Exchange a Microsoft access token for an Xbox Live token + user hash."""
    data = _http_json(XBL_URL, {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": "d=" + ms_access_token,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    })
    token = data.get("Token", "")
    claims = (data.get("DisplayClaims") or {}).get("xui") or [{}]
    uhs = claims[0].get("uhs", "")
    if not token or not uhs:
        raise RuntimeError("Xbox Live did not return a token.")
    return token, uhs


def xbox_xsts(xbl_token):
    """Authorize the Xbox token for Minecraft, returning (token, xuid)."""
    try:
        data = _http_json(XSTS_URL, {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        })
    except MSRequestError as exc:
        code = str((exc.payload or {}).get("XErr", ""))
        raise RuntimeError(
            XSTS_ERRORS.get(code, "Xbox Live authorization failed "
                                  f"(error {code or 'unknown'}).")) from None
    token = data.get("Token", "")
    claims = (data.get("DisplayClaims") or {}).get("xui") or [{}]
    xuid = claims[0].get("xid", "")
    if not token:
        raise RuntimeError("Xbox Live authorization returned no token.")
    return token, xuid


def minecraft_login(xsts_token, uhs):
    """Exchange the XSTS token for a Minecraft access token."""
    data = _http_json(MC_LOGIN_URL, {
        "identityToken": f"XBL3.0 x={uhs};{xsts_token}"})
    token = data.get("access_token", "")
    if not token:
        raise RuntimeError("Minecraft did not return an access token.")
    return token, int(data.get("expires_in") or 86400)


def minecraft_profile(token):
    """Fetch the player's UUID and name. 404 means the account owns no game."""
    try:
        data = _http_json(MC_PROFILE_URL, token=token)
    except MSRequestError as exc:
        if (exc.payload or {}).get("http_status") == 404:
            raise RuntimeError(
                "This Microsoft account does not own Minecraft: Java Edition."
            ) from None
        raise
    profile_id = str(data.get("id", ""))
    name = str(data.get("name", ""))
    if not profile_id or not name:
        raise RuntimeError("Minecraft returned an empty profile.")
    return {"id": profile_id, "name": name}


# ---------------------------------------------------------------------------
# Ely.by account (Yggdrasil protocol + authlib-injector for the game client)
# ---------------------------------------------------------------------------

ELY_AUTH_URL = "https://authserver.ely.by/auth/authenticate"
ELY_REFRESH_URL = "https://authserver.ely.by/auth/refresh"
ELY_INVALIDATE_URL = "https://authserver.ely.by/auth/invalidate"
# OAuth2 ("Sign in with browser") endpoints, from docs.ely.by/ru/oauth.html.
ELY_OAUTH_AUTHORIZE_URL = "https://account.ely.by/oauth2/v1"
ELY_OAUTH_TOKEN_URL = "https://account.ely.by/api/oauth2/v1/token"
ELY_ACCOUNT_INFO_URL = "https://account.ely.by/api/account/v1/info"
ELY_OAUTH_SCOPE = "account_info offline_access minecraft_server_session"
ELY_OAUTH_REDIRECT_DEFAULT = "http://localhost:26206/ely-callback"
# Client ID of the launcher's own Ely.by "desktop application". Public clients
# (PKCE) need no secret, so this can be bundled with the launcher.
ELY_OAUTH_CLIENT_ID_DEFAULT = "why-launcher"
# Passed to authlib-injector inside the game; it also enables Ely.by skins.
ELY_JAVA_AGENT = "ely.by"
AUTHLIB_VERSION = "1.2.8"
AUTHLIB_URL = ("https://github.com/yushijinhun/authlib-injector/releases/"
               f"download/v{AUTHLIB_VERSION}/authlib-injector-"
               f"{AUTHLIB_VERSION}.jar")


class ElyAuthError(Exception):
    """Yggdrasil error returned by authserver.ely.by."""

    def __init__(self, payload):
        self.payload = payload if isinstance(payload, dict) else {}
        detail = (self.payload.get("errorMessage")
                  or self.payload.get("error_description")
                  or self.payload.get("error") or "Request failed")
        super().__init__(detail)
        self.two_factor = "two factor" in detail.lower()


def ely_authenticate(username, password, client_token):
    """Sign in with an Ely.by e-mail/username and password (or ``password:otp``)."""
    try:
        return _http_json(ELY_AUTH_URL, {
            "username": username,
            "password": password,
            "clientToken": client_token,
            "requestUser": True,
        })
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def ely_refresh(access_token, client_token):
    """Exchange a stored Ely.by access token for a fresh one."""
    try:
        return _http_json(ELY_REFRESH_URL, {
            "accessToken": access_token,
            "clientToken": client_token,
            "requestUser": True,
        })
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def pkce_pair():
    """Return (verifier, S256 challenge) for the OAuth2 PKCE flow."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def ely_oauth_exchange(code, client_id, client_secret, redirect_uri,
                       code_verifier=""):
    """Trade an OAuth2 authorization code for tokens."""
    payload = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code": code,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    if code_verifier:
        payload["code_verifier"] = code_verifier
    try:
        return _http_json(ELY_OAUTH_TOKEN_URL, payload, form=True)
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def ely_oauth_refresh(refresh_token, client_id, client_secret):
    """Get a new OAuth2 access token from the non-expiring refresh token."""
    payload = {
        "client_id": client_id,
        "scope": ELY_OAUTH_SCOPE,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        payload["client_secret"] = client_secret
    try:
        return _http_json(ELY_OAUTH_TOKEN_URL, payload, form=True)
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def ely_account_info(access_token):
    return _http_json(ELY_ACCOUNT_INFO_URL, token=access_token)


def loopback_redirect_target(redirect_uri):
    """Return ((host, port), path) for a localhost callback URI."""
    parsed = urllib.parse.urlparse(str(redirect_uri or "").strip())
    if parsed.scheme != "http":
        raise ValueError("Redirect URI must start with http:// (local TLS is "
                         "not supported).")
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Redirect URI must point to localhost.")
    try:
        port = parsed.port or 80
    except ValueError:
        raise ValueError("Redirect URI has an invalid port.") from None
    return ("127.0.0.1", port), (parsed.path or "/")


class _ElyCallbackServer(http.server.HTTPServer):
    allow_reuse_address = True

    def __init__(self, address, callback_path):
        super().__init__(address, _ElyCallbackHandler)
        self.callback_path = callback_path.rstrip("/") or "/"
        self.result = None
        self.event = threading.Event()


class _ElyCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != self.server.callback_path:
            self._reply(404, "<!doctype html><meta charset='utf-8'>"
                             "<h1>Not found</h1>")
            return
        self.server.result = urllib.parse.parse_qs(parsed.query)
        self.server.event.set()
        self._reply(200, "<!doctype html><meta charset='utf-8'>"
                         "<title>Ely.by</title>"
                         "<body style='font:16px Segoe UI,sans-serif;"
                         "background:#0a0a0a;color:#f4f4f4;display:grid;"
                         "place-items:center;height:100vh;margin:0'>"
                         "<p>Ely.by sign-in complete — you can close this "
                         "tab and return to the launcher.</p>")

    def _reply(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.debug("Ely.by callback: " + fmt, *args)


def ensure_authlib_injector() -> Path:
    """Download authlib-injector once; it authenticates and loads skins in game."""
    target = app_dir() / f"authlib-injector-{AUTHLIB_VERSION}.jar"
    if target.is_file() and target.stat().st_size > 200_000:
        return target
    log.info("downloading authlib-injector %s", AUTHLIB_VERSION)
    request = urllib.request.Request(
        AUTHLIB_URL, headers={"User-Agent": f"{APP_NAME}/1"})
    temp = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, \
                open(temp, "wb") as handle:
            shutil.copyfileobj(response, handle)
        if temp.stat().st_size < 200_000:
            raise RuntimeError("the downloaded file is too small")
        os.replace(temp, target)
    except Exception as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("Could not download authlib-injector, which is "
                           f"required for Ely.by: {exc}") from None
    log.info("authlib-injector saved to %s", target)
    return target


class LauncherApi:
    """State and commands exposed to the page as ``window.pywebview.api``."""

    RAM_MIN = 1
    RAM_MAX = 16

    def __init__(self):
        self.instances = []
        self.selected_slug = str(self._saved("instance", "") or "")
        self.player = str(self._saved("player", "Player") or "Player")
        try:
            ram = int(self._saved("ram", 2) or 2)
        except (TypeError, ValueError):
            ram = 2
        self.ram = max(self.RAM_MIN, min(self.RAM_MAX, ram))
        try:
            default_ram = int(self._saved("default_ram", 2) or 2)
        except (TypeError, ValueError):
            default_ram = 2
        self.default_ram = max(self.RAM_MIN, min(self.RAM_MAX, default_ram))
        self.java_path = str(self._saved("java", "") or "")
        global JAVA_OVERRIDE
        JAVA_OVERRIDE = self.java_path
        ms = self._saved("ms", {})
        if not isinstance(ms, dict):
            ms = {}
        self._ms_client_id = str(ms.get("client_id", "") or "").strip()
        self._accounts = self._load_accounts(ms)
        ids = {account["id"] for account in self._accounts}
        saved_active = str(self._saved("active_account", "") or "")
        self._active_account_id = saved_active if saved_active in ids \
            else (self._accounts[0]["id"] if self._accounts else "")
        active_account = self._active_account()
        if active_account is not None and active_account["type"] == "offline":
            self.player = active_account["name"]
        self._ms_device_stop = threading.Event()
        self._ms_device_thread = None
        ely = self._saved("ely", {})
        if not isinstance(ely, dict):
            ely = {}
        oauth = ely.get("oauth")
        if not isinstance(oauth, dict):
            oauth = {}
        self._ely_oauth_client_id = str(oauth.get("client_id", "") or "")
        self._ely_oauth_secret = str(oauth.get("client_secret", "") or "")
        self._ely_oauth_redirect = str(
            oauth.get("redirect_uri", "") or ELY_OAUTH_REDIRECT_DEFAULT)
        self._ely_oauth_stop = threading.Event()
        self._ely_oauth_thread = None
        # Attributes starting with "_" are skipped by pywebview when it builds
        # the JS bridge, so internal queues/events never get exposed.
        self._events = queue.Queue()
        self._log_queue = queue.Queue()
        self.busy = ""
        self._cancel_event = None
        self._lock = threading.RLock()
        self._launching = False
        self._game_process = None
        self._game_slug = ""
        self._game_lock = threading.Lock()
        self._log_path = None
        self._log_pos = 0
        self.refresh_instances(select=self.selected_slug)
        self._install_trace()
        log.info("api ready: player=%r ram=%s default_ram=%s java=%r "
                 "instance=%r profiles=%d accounts=%d active=%r",
                 self.player, self.ram, self.default_ram,
                 self.java_path or "(auto)", self.selected_slug,
                 len(self.instances), len(self._accounts),
                 self._account_label())

    # -- diagnostics --------------------------------------------------------

    def _install_trace(self):
        """Log every bridged call: if the UI hangs, the log shows the culprit."""
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if name.startswith("_") or name in {
                    "poll", "log_js", "ely_login", "set_ely_oauth"}:
                # ely_login receives a password and set_ely_oauth a secret;
                # never write either to the log.
                continue
            setattr(self, name, self._make_traced(name, func))

    def _make_traced(self, name, func):
        def wrapper(*args, **kwargs):
            shown = ", ".join(repr(arg) for arg in args)
            if len(shown) > 200:
                shown = shown[:200] + "…"
            started = time.monotonic()
            log.debug("call %s(%s)", name, shown)
            try:
                result = func(self, *args, **kwargs)
            except Exception:
                log.exception("call %s failed after %.2fs", name,
                              time.monotonic() - started)
                raise
            log.debug("done %s in %.2fs", name, time.monotonic() - started)
            return result
        return wrapper

    def log_js(self, message):
        """Diagnostics and uncaught JS errors forwarded by the page."""
        log.warning("page: %s", str(message)[:4000])
        return {"ok": True}

    # -- events -------------------------------------------------------------

    def _event(self, kind, **payload):
        payload["t"] = kind
        # The page drains a few hundred events every 160 ms; a small cap keeps
        # a stalled page from ballooning memory with queued game log lines.
        if self._events.qsize() < 4000:
            self._events.put(payload)

    def _status(self, screen, text, error=False):
        self._event("status", screen=screen, text=str(text), error=bool(error))

    def _log(self, channel, line):
        self._event("log", channel=channel, line=str(line))

    def _progress(self, done, total):
        self._event("progress", value=int(done), total=int(total))

    def _stream_log(self, channel):
        def log(text):
            self._log(channel, text)
        return log

    # -- settings -----------------------------------------------------------

    def _saved(self, key, default):
        path = Path(self._settings_path())
        if path.is_file():
            try:
                return json.loads(
                    path.read_text(encoding="utf-8")).get(key, default)
            except (OSError, json.JSONDecodeError):
                return default
        return default

    @staticmethod
    def _settings_path():
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
            else Path(__file__).parent
        return base / "settings.json"

    @staticmethod
    def _normalize_account(item):
        if not isinstance(item, dict):
            return None
        kind = str(item.get("type", "") or "")
        if kind not in ("microsoft", "ely", "offline"):
            return None
        name = str(item.get("name", "") or "").strip()[:16]
        account = {
            "id": str(item.get("id", "") or uuid.uuid4().hex),
            "type": kind,
            "name": name or "Player",
            "uuid": str(item.get("uuid", "") or ""),
        }
        if kind == "microsoft":
            account["refresh_token"] = str(
                item.get("refresh_token", "") or "")
            account["xuid"] = str(item.get("xuid", "") or "")
        elif kind == "ely":
            account["access_token"] = str(
                item.get("access_token", "") or "")
            account["client_token"] = str(
                item.get("client_token", "") or "")
            account["refresh_token"] = str(
                item.get("refresh_token", "") or "")
            account["kind"] = str(item.get("kind", "") or "")
        return account

    def _load_accounts(self, legacy_ms):
        """Load the account list, migrating the old single-session settings."""
        raw = self._saved("accounts", None)
        if isinstance(raw, list):
            accounts = []
            for item in raw:
                account = self._normalize_account(item)
                if account is not None:
                    accounts.append(account)
            return accounts
        accounts = []
        profile = legacy_ms.get("profile")
        profile = profile if isinstance(profile, dict) else {}
        if profile.get("id") and legacy_ms.get("refresh_token"):
            accounts.append({
                "id": uuid.uuid4().hex, "type": "microsoft",
                "name": str(profile.get("name", "") or ""),
                "uuid": str(profile.get("id", "") or ""),
                "refresh_token": str(legacy_ms.get("refresh_token", "") or ""),
                "xuid": str(legacy_ms.get("xuid", "") or "")})
        ely = self._saved("ely", {})
        if not isinstance(ely, dict):
            ely = {}
        ely_profile = ely.get("profile")
        ely_profile = ely_profile if isinstance(ely_profile, dict) else {}
        if ely_profile.get("id") and ely.get("access_token"):
            accounts.append({
                "id": uuid.uuid4().hex, "type": "ely",
                "name": str(ely_profile.get("name", "") or ""),
                "uuid": str(ely_profile.get("id", "") or ""),
                "access_token": str(ely.get("access_token", "") or ""),
                "client_token": str(ely.get("client_token", "") or ""),
                "refresh_token": str(ely.get("refresh_token", "") or ""),
                "kind": str(ely.get("kind", "") or "")})
        if not accounts:
            accounts.append({"id": uuid.uuid4().hex, "type": "offline",
                             "name": self.player, "uuid": ""})
        return accounts

    def _account_by_id(self, account_id):
        account_id = str(account_id or "")
        for account in self._accounts:
            if account["id"] == account_id:
                return account
        return None

    def _active_account(self):
        return self._account_by_id(self._active_account_id)

    def _account_for_profile(self, kind, profile_id):
        profile_id = str(profile_id or "")
        for account in self._accounts:
            if account["type"] == kind and account["uuid"] == profile_id:
                return account
        return None

    def _account_public(self, account):
        return {
            "id": account["id"],
            "type": account["type"],
            "name": account["name"],
            "uuid": account.get("uuid", ""),
            "active": account["id"] == self._active_account_id,
            "signed_in": account["type"] == "offline" or bool(
                account.get("uuid")
                and (account.get("refresh_token")
                     or account.get("access_token"))),
        }

    def _account_label(self):
        account = self._active_account()
        if account is None:
            return "offline"
        return f'{account["name"]} ({account["type"]})'

    def _upsert_account(self, account):
        """Store an account and make it active; returns the stored entry."""
        existing = self._account_for_profile(
            account["type"], account.get("uuid", ""))
        if existing is not None:
            existing.update(account)
            stored = existing
        else:
            if not account.get("id"):
                account["id"] = uuid.uuid4().hex
            self._accounts.append(account)
            stored = account
        self._active_account_id = stored["id"]
        return stored

    def _save(self):
        data = {"player": self.player, "ram": int(self.ram),
                "default_ram": int(self.default_ram),
                "java": self.java_path,
                "instance": self.selected_slug,
                "accounts": [
                    {key: value for key, value in account.items()
                     if not key.startswith("_")}
                    for account in self._accounts],
                "active_account": self._active_account_id,
                "ms": {"client_id": self._ms_client_id},
                "ely": {"oauth": {
                    "client_id": self._ely_oauth_client_id,
                    "client_secret": self._ely_oauth_secret,
                    "redirect_uri": self._ely_oauth_redirect}}}
        try:
            Path(self._settings_path()).write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def on_close(self):
        self._save()

    # -- profiles -----------------------------------------------------------

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
        return {
            "slug": instance.get("_slug", ""),
            "name": instance.get("name", ""),
            "version": version,
            "base": base,
            "loader": loader,
            "loader_version": profile_loader_version(version, loader, base),
            "loader_label": {"fabric": "Fabric", "forge": "Forge",
                             "neoforge": "NeoForge", "quilt": "Quilt"}
            .get(loader, "Fabric"),
            "ram": ram,
            "path": str(instance_game_dir(instance["_root"])),
            "icon": profile_icon_data_url(
                instance["_root"], instance.get("icon")),
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
            return {
                "instances": items,
                "selected": self.selected_slug if instance is not None else "",
                "instance": active,
                "player": self.player,
                "ram": int(self.ram),
                "default_ram": int(self.default_ram),
                "java": self.java_path,
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
                "account": (active_account["type"]
                            if active_account is not None else "offline"),
                "paths": {"shared": str(MC),
                          "instances": str(INSTANCES_DIR)},
                "busy": self.busy,
                "launching": self._launching,
                "game_running": self._game_running(),
                "game_instance": self._game_slug,
            }

    def refresh_instances(self, select=None):
        with self._lock:
            previous = self.selected_slug if select is None else select
            self.instances = list_instances()
            slugs = {instance["_slug"] for instance in self.instances}
            if previous not in slugs:
                previous = self.instances[0]["_slug"] if self.instances else ""
            self.selected_slug = previous

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

    def account_select(self, account_id):
        with self._lock:
            account = self._account_by_id(account_id)
            if account is None:
                return {"ok": False,
                        "error": "That account no longer exists.",
                        "state": self.state()}
            self._active_account_id = str(account_id)
            if account["type"] == "offline":
                self.player = account["name"]
            self._save()
        return {"ok": True, "state": self.state()}

    def account_add_offline(self, name=""):
        name = str(name or "").strip()[:16] or "Player"
        with self._lock:
            account = next(
                (item for item in self._accounts
                 if item["type"] == "offline"
                 and item["name"].lower() == name.lower()), None)
            if account is None:
                account = {"id": uuid.uuid4().hex, "type": "offline",
                           "name": name, "uuid": ""}
                self._accounts.append(account)
            self._active_account_id = account["id"]
            self.player = account["name"]
            self._save()
        log.info("Offline account added/selected: %s", name)
        return {"ok": True, "name": name, "state": self.state()}

    def account_remove(self, account_id):
        with self._lock:
            account = self._account_by_id(account_id)
            if account is None:
                return {"ok": False,
                        "error": "That account no longer exists.",
                        "state": self.state()}
            self._accounts = [item for item in self._accounts
                              if item["id"] != account["id"]]
            if self._active_account_id == account["id"]:
                self._active_account_id = self._accounts[0]["id"] \
                    if self._accounts else ""
                active = self._active_account()
                if active is not None and active["type"] == "offline":
                    self.player = active["name"]
            self._save()
        if account["type"] == "ely" and account.get("kind") != "oauth" \
                and account.get("access_token"):
            try:
                _http_json(ELY_INVALIDATE_URL, {
                    "accessToken": account["access_token"],
                    "clientToken": account.get("client_token", "")})
            except Exception as exc:
                log.warning("Ely.by token invalidation failed: %s", exc)
        log.info("Account removed: %s (%s)", account["name"], account["type"])
        self._event("refresh")
        return {"ok": True, "state": self.state()}

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

    def set_default_ram(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.default_ram
        self.default_ram = max(self.RAM_MIN, min(self.RAM_MAX, value))
        self._save()
        return {"state": self.state()}

    def set_java(self, path):
        path = str(path or "").strip()
        if path:
            target = Path(path)
            if target.is_dir():
                names = ("javaw.exe", "java.exe") if os.name == "nt" \
                    else ("java",)
                found = next((target / "bin" / name for name in names
                              if (target / "bin" / name).is_file()), None)
                if found is not None:
                    target = found
                else:
                    return {"ok": False,
                            "error": f"No Java found inside {path}",
                            "state": self.state()}
            if not target.is_file():
                return {"ok": False, "error": f"Java not found at {path}",
                        "state": self.state()}
            path = str(target)
        global JAVA_OVERRIDE
        self.java_path = path
        JAVA_OVERRIDE = path
        self._save()
        return {"ok": True, "state": self.state()}

    def pick_java(self):
        """Native Windows file picker in its own STA process.

        pywebview dialogs must run on the GUI thread, while JS API calls run
        on worker threads, so the picker is opened through PowerShell instead.
        """
        if os.name != "nt":
            return {"ok": False,
                    "error": "Type the path to the Java executable."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = 'Select javaw.exe'; "
            "$d.Filter = 'Java executables (javaw.exe;java.exe)|"
            "javaw.exe;java.exe|All files (*.*)|*.*'; "
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
        return self.set_java(picked)

    def open_shared(self):
        try:
            MC.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False, "path": str(MC)}
        open_in_system(MC)
        return {"ok": True, "path": str(MC)}

    # -- Microsoft account --------------------------------------------------

    def set_ms_client_id(self, value):
        value = str(value or "").strip()
        if value and not re.fullmatch(r"[0-9a-fA-F][0-9a-fA-F-]{15,60}", value):
            return {"ok": False,
                    "error": "That does not look like an Application (client) "
                             "ID — copy the value from Azure.",
                    "state": self.state()}
        self._ms_client_id = value
        self._save()
        return {"ok": True, "state": self.state()}

    def ms_login(self):
        client_id = self._ms_client_id or MS_CLIENT_ID_DEFAULT
        if not client_id:
            return {"ok": False,
                    "error": "Add your Azure Application (client) ID first."}
        if self._ms_device_thread is not None \
                and self._ms_device_thread.is_alive():
            return {"ok": False, "error": "Sign-in is already in progress."}
        self._ely_oauth_stop.set()
        try:
            data = _http_json(MS_DEVICE_URL,
                              {"client_id": client_id, "scope": MS_SCOPE},
                              form=True)
        except MSRequestError as exc:
            log.warning("MS device code request failed: %s", exc)
            message = str(exc)
            if "client" in message.lower() or \
                    (exc.payload or {}).get("error") in ("invalid_client",
                                                         "unauthorized_client"):
                message = ("Microsoft rejected this Client ID. Check that the "
                           "app is registered for personal Microsoft accounts "
                           "and that public client flows are enabled.")
            return {"ok": False, "error": message}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ok": False,
                    "error": f"Could not reach Microsoft: {exc}"}
        device_code = str(data.get("device_code", ""))
        user_code = str(data.get("user_code", ""))
        verification = str(data.get("verification_uri")
                           or "https://microsoft.com/link")
        try:
            interval = max(1, int(data.get("interval") or 5))
        except (TypeError, ValueError):
            interval = 5
        try:
            expires = int(data.get("expires_in") or 900)
        except (TypeError, ValueError):
            expires = 900
        if not device_code or not user_code:
            return {"ok": False,
                    "error": "Microsoft returned an incomplete sign-in code."}
        self._ms_device_stop = threading.Event()
        self._ms_device_thread = threading.Thread(
            target=self._ms_login_worker,
            args=(client_id, device_code, interval, expires),
            name="ms-login", daemon=True)
        self._ms_device_thread.start()
        log.info("Microsoft device code issued: %s", user_code)
        self._event("msauth", status="code", user_code=user_code,
                    verification_uri=verification, expires_in=expires)
        browser_url = verification
        if "microsoft.com/link" in browser_url:
            browser_url += ("&" if "?" in browser_url else "?") \
                + "otc=" + urllib.parse.quote(user_code)
        open_in_system(browser_url)
        return {"ok": True, "user_code": user_code,
                "verification_uri": verification, "expires_in": expires}

    def ms_cancel_login(self):
        self._ms_device_stop.set()
        return {"ok": True}

    def ms_logout(self):
        self._ms_device_stop.set()
        account = self._active_account()
        if account is None or account["type"] != "microsoft":
            account = next((item for item in self._accounts
                            if item["type"] == "microsoft"), None)
        if account is not None:
            self.account_remove(account["id"])
        self._event("msauth", status="signed_out")
        log.info("Microsoft account removed")
        return {"ok": True, "state": self.state()}

    def _ms_login_worker(self, client_id, device_code, interval, expires):
        deadline = time.monotonic() + expires
        while time.monotonic() < deadline:
            if self._ms_device_stop.wait(interval):
                self._event("msauth", status="cancelled")
                return
            try:
                token = _http_json(MS_TOKEN_URL, {
                    "client_id": client_id,
                    "grant_type":
                        "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                }, form=True)
            except MSRequestError as exc:
                error = (exc.payload or {}).get("error", "")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                if error == "authorization_declined":
                    self._event("msauth", status="error",
                                message="Sign-in was declined.")
                    return
                if error in ("expired_token", "bad_verification_code"):
                    self._event("msauth", status="error",
                                message="The sign-in code expired. "
                                        "Start again.")
                    return
                log.warning("MS token poll failed: %s", exc)
                self._event("msauth", status="error", message=str(exc))
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                log.warning("MS token poll network error: %s", exc)
                continue
            self._finish_ms_login(token)
            return
        self._event("msauth", status="error",
                    message="The sign-in code expired. Start again.")

    def _finish_ms_login(self, token):
        try:
            ms_access = str(token.get("access_token", ""))
            if not ms_access:
                raise RuntimeError("Microsoft returned no access token.")
            xbl, uhs = xbox_authenticate(ms_access)
            xsts, xuid = xbox_xsts(xbl)
            mc_token, expires = minecraft_login(xsts, uhs)
            profile = minecraft_profile(mc_token)
        except MSRequestError as exc:
            log.warning("MS sign-in failed: %s", exc)
            self._event("msauth", status="error", message=str(exc))
            return
        except Exception as exc:
            log.exception("MS sign-in failed")
            self._event("msauth", status="error", message=str(exc))
            return
        with self._lock:
            account = {
                "type": "microsoft",
                "name": str(profile.get("name", "") or "")[:16],
                "uuid": str(profile.get("id", "") or ""),
                "refresh_token": str(token.get("refresh_token", "") or ""),
                "xuid": xuid,
                "_access": mc_token,
                "_exp": time.time() + max(60, expires - 60),
            }
            existing = self._account_for_profile(
                "microsoft", account["uuid"])
            if existing is not None and not account["refresh_token"]:
                account["refresh_token"] = existing.get("refresh_token", "")
            stored = self._upsert_account(account)
            self._save()
        log.info("Microsoft sign-in complete: %s (%s)", stored["name"],
                 stored["uuid"])
        self._event("msauth", status="ok", name=stored["name"],
                    uuid=stored["uuid"])
        self._event("refresh")

    def _ms_refresh(self, account):
        """Return a fresh Minecraft access token, or "" if refresh failed."""
        with self._lock:
            cached = account.get("_access", "")
            if cached and time.time() < account.get("_exp", 0.0):
                return cached
            refresh_token = account.get("refresh_token", "")
            client_id = self._ms_client_id or MS_CLIENT_ID_DEFAULT
        if not refresh_token or not client_id:
            return ""
        try:
            data = _http_json(MS_TOKEN_URL, {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": MS_SCOPE,
            }, form=True)
            xbl, uhs = xbox_authenticate(str(data.get("access_token", "")))
            xsts, xuid = xbox_xsts(xbl)
            mc_token, expires = minecraft_login(xsts, uhs)
            profile = minecraft_profile(mc_token)
        except Exception as exc:
            log.warning("Microsoft token refresh failed: %s", exc)
            return ""
        with self._lock:
            account["_access"] = mc_token
            account["_exp"] = time.time() + max(60, expires - 60)
            if data.get("refresh_token"):
                account["refresh_token"] = str(data["refresh_token"])
            account["name"] = str(profile.get("name", "") or "")[:16]
            account["uuid"] = str(profile.get("id", "") or "")
            account["xuid"] = xuid
            self._save()
        return mc_token

    # -- Ely.by account -----------------------------------------------------

    def ely_login(self, username, password, totp=""):
        """Sign in to Ely.by. The password is used once and never stored."""
        username = str(username or "").strip()
        password = str(password or "")
        totp = str(totp or "").strip()
        if not username or not password:
            return {"ok": False,
                    "error": "Enter your Ely.by e-mail/username and password."}
        self._ely_oauth_stop.set()
        self._ms_device_stop.set()
        with self._lock:
            client_token = str(uuid.uuid4())
        secret = password + (":" + totp if totp else "")
        try:
            data = ely_authenticate(username, secret, client_token)
        except ElyAuthError as exc:
            log.warning("Ely.by sign-in failed: %s", exc)
            if exc.two_factor:
                return {"ok": False, "two_factor": True,
                        "error": "This account uses two-factor "
                                 "authentication. Enter the current 6-digit "
                                 "code from your authenticator app."}
            message = str(exc)
            if "invalid credentials" in message.lower():
                message = ("Invalid Ely.by e-mail/username or password."
                           if not totp else
                           "Invalid password or two-factor code.")
            return {"ok": False, "error": message}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ok": False,
                    "error": f"Could not reach Ely.by: {exc}"}
        access = str(data.get("accessToken", ""))
        profile = data.get("selectedProfile") or {}
        name = str(profile.get("name", "") or "")
        profile_id = str(profile.get("id", "") or "")
        if not access or not profile_id or not name:
            return {"ok": False,
                    "error": "Ely.by returned an incomplete profile."}
        with self._lock:
            account = {
                "type": "ely",
                "name": name[:16],
                "uuid": profile_id,
                "access_token": access,
                "client_token": str(data.get("clientToken")
                                    or client_token),
                "refresh_token": "",
                "kind": "yggdrasil",
            }
            stored = self._upsert_account(account)
            self._save()
        log.info("Ely.by sign-in complete: %s (%s)", stored["name"],
                 stored["uuid"])
        self._event("refresh")
        return {"ok": True, "name": stored["name"], "state": self.state()}

    def ely_logout(self):
        self._ely_oauth_stop.set()
        account = self._active_account()
        if account is None or account["type"] != "ely":
            account = next((item for item in self._accounts
                            if item["type"] == "ely"), None)
        if account is not None:
            self.account_remove(account["id"])
        log.info("Ely.by account removed")
        return {"ok": True, "state": self.state()}

    def _ely_refresh(self, account):
        """Return a fresh Ely.by access token, or "" if it cannot be renewed."""
        with self._lock:
            kind = account.get("kind", "")
            token = account.get("access_token", "")
            client_token = account.get("client_token", "")
            refresh_token = account.get("refresh_token", "")
            client_id = self._ely_oauth_client_id \
                or ELY_OAUTH_CLIENT_ID_DEFAULT
            client_secret = self._ely_oauth_secret
        if not token:
            return ""
        if kind == "oauth":
            if not refresh_token or not client_id:
                return ""
            try:
                data = ely_oauth_refresh(refresh_token, client_id,
                                         client_secret)
            except Exception as exc:
                log.warning("Ely.by OAuth refresh failed: %s", exc)
                return ""
            new_token = str(data.get("access_token", ""))
            if not new_token:
                return ""
            with self._lock:
                account["access_token"] = new_token
                if data.get("refresh_token"):
                    account["refresh_token"] = str(data["refresh_token"])
                self._save()
            return new_token
        try:
            data = ely_refresh(token, client_token)
        except Exception as exc:
            log.warning("Ely.by token refresh failed: %s", exc)
            return ""
        new_token = str(data.get("accessToken", ""))
        if not new_token:
            return ""
        profile = data.get("selectedProfile") or {}
        with self._lock:
            account["access_token"] = new_token
            if profile.get("id") and profile.get("name"):
                account["name"] = str(profile["name"])[:16]
                account["uuid"] = str(profile["id"])
            self._save()
        return new_token

    def set_ely_oauth(self, client_id, client_secret="", redirect_uri=""):
        """Store the Ely.by OAuth2 application used for browser sign-in."""
        client_id = str(client_id or "").strip()
        client_secret = str(client_secret or "").strip()
        redirect_uri = str(redirect_uri or "").strip() \
            or ELY_OAUTH_REDIRECT_DEFAULT
        with self._lock:
            saved_id = self._ely_oauth_client_id
            saved_secret = self._ely_oauth_secret
        if client_id and not client_secret and client_id == saved_id:
            client_secret = saved_secret
        try:
            loopback_redirect_target(redirect_uri)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "state": self.state()}
        with self._lock:
            self._ely_oauth_client_id = client_id
            self._ely_oauth_secret = client_secret
            self._ely_oauth_redirect = redirect_uri
            self._save()
        log.info("Ely.by OAuth settings saved: client_id=%r redirect=%r "
                 "secret=%s", client_id, redirect_uri,
                 "set" if client_secret else "empty")
        return {"ok": True, "state": self.state()}

    def ely_browser_login(self):
        if self._ely_oauth_thread is not None \
                and self._ely_oauth_thread.is_alive():
            return {"ok": False,
                    "error": "Browser sign-in is already in progress."}
        self._ms_device_stop.set()
        with self._lock:
            client_id = self._ely_oauth_client_id \
                or ELY_OAUTH_CLIENT_ID_DEFAULT
            client_secret = self._ely_oauth_secret
            redirect_uri = self._ely_oauth_redirect \
                or ELY_OAUTH_REDIRECT_DEFAULT
        if not client_id:
            return {"ok": False, "setup": True,
                    "error": "Browser sign-in is not configured yet. Open "
                             "“Advanced: browser sign-in (OAuth) setup” and "
                             "add the Ely.by Client ID (the Client Secret is "
                             "only needed for “Website” apps)."}
        try:
            address, path = loopback_redirect_target(redirect_uri)
        except ValueError as exc:
            return {"ok": False, "setup": True, "error": str(exc)}
        self._ely_oauth_stop = threading.Event()
        self._ely_oauth_thread = threading.Thread(
            target=self._ely_oauth_worker,
            args=(client_id, client_secret, redirect_uri, address, path),
            name="ely-oauth", daemon=True)
        self._ely_oauth_thread.start()
        return {"ok": True}

    def ely_cancel_login(self):
        self._ely_oauth_stop.set()
        return {"ok": True}

    def _ely_oauth_worker(self, client_id, client_secret, redirect_uri,
                          address, path):
        state = secrets.token_urlsafe(24)
        verifier, challenge = pkce_pair()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ELY_OAUTH_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        query = urllib.parse.urlencode(params)
        try:
            server = _ElyCallbackServer(address, path)
        except OSError as exc:
            log.warning("Ely.by OAuth callback server failed: %s", exc)
            self._event("elyauth", status="error",
                        message=f"Could not listen on {address[0]}:"
                                f"{address[1]} for the browser redirect: "
                                f"{exc}")
            return
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self._event("elyauth", status="waiting")
            open_in_system(ELY_OAUTH_AUTHORIZE_URL + "?" + query)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self._ely_oauth_stop.is_set():
                    self._event("elyauth", status="cancelled")
                    return
                if server.event.wait(0.5):
                    break
            else:
                self._event("elyauth", status="error",
                            message="Browser sign-in timed out. Try again.")
                return
            params = server.result or {}
            if params.get("error"):
                message = (params.get("error_message")
                           or params.get("error") or ["Sign-in failed."])[0]
                self._event("elyauth", status="error",
                            message=urllib.parse.unquote_plus(str(message)))
                return
            code = (params.get("code") or [""])[0]
            returned = (params.get("state") or [""])[0]
            if returned != state:
                self._event("elyauth", status="error",
                            message="Sign-in state mismatch. Try again.")
                return
            if not code:
                self._event("elyauth", status="error",
                            message="Ely.by returned no authorization code.")
                return
            try:
                data = ely_oauth_exchange(code, client_id, client_secret,
                                          redirect_uri,
                                          "" if client_secret else verifier)
                access = str(data.get("access_token", ""))
                if not access:
                    raise RuntimeError("Ely.by returned no access token.")
                info = ely_account_info(access)
            except ElyAuthError as exc:
                log.warning("Ely.by browser sign-in failed: %s", exc)
                self._event("elyauth", status="error", message=str(exc))
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                self._event("elyauth", status="error",
                            message=f"Could not reach Ely.by: {exc}")
                return
            except Exception as exc:
                log.exception("Ely.by browser sign-in failed")
                self._event("elyauth", status="error", message=str(exc))
                return
            name = str(info.get("username", "") or "")
            profile_id = str(info.get("uuid", "") or "").replace("-", "")
            if not name or not profile_id:
                self._event("elyauth", status="error",
                            message="Ely.by returned an incomplete profile.")
                return
            with self._lock:
                account = {
                    "type": "ely",
                    "name": name[:16],
                    "uuid": profile_id,
                    "access_token": access,
                    "client_token": "",
                    "refresh_token": str(
                        data.get("refresh_token", "") or ""),
                    "kind": "oauth",
                }
                stored = self._upsert_account(account)
                self._save()
            log.info("Ely.by browser sign-in complete: %s (%s)",
                     stored["name"], stored["uuid"])
            self._event("elyauth", status="ok", name=stored["name"],
                        uuid=stored["uuid"])
            self._event("refresh")
        finally:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass

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
        data["ok"] = True
        return data

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
        deadline = time.time() + 8
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
                        f"/version_file/{sha1}", timeout=6)
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
                    project = modrinth_get(f"/project/{pid}", timeout=6)
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
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = 'Select a profile icon'; "
            "$d.Filter = 'Images (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)|"
            "*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp|All files (*.*)|*.*'; "
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

    # -- versions -----------------------------------------------------------

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
        try:
            pairs = loader_builds(str(loader_key), str(game_version))
        except Exception as exc:
            return {"builds": [], "error": str(exc)}
        return {"builds": [{"version": value, "label": label}
                           for value, label in pairs], "error": ""}

    # -- creating -----------------------------------------------------------

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
                                         loader_version, java, log)
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
        if self._game_running():
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
                                             loader_version, java, log)
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
        if self._game_running():
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
        if self._game_running():
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
                       loader_version=None):
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
                                                 pack_loader_version, java, log)
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

    # -- mods ---------------------------------------------------------------

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

    def mods_install(self, project_id, loader, slug=None):
        instance, game, detected = self._instance_game()
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

    def mods_update(self, project_id, loader, slug=None):
        instance, game, detected = self._instance_game()
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

    # -- Modrinth browser: packs and modpacks --------------------------------

    @staticmethod
    def _content_kind(kind):
        kind = str(kind or "mod")
        return kind if kind in ("mod", "resourcepack", "shader",
                                "modpack") else "mod"

    def content_search(self, kind, query="", loader="any", offset=0):
        kind = self._content_kind(kind)
        try:
            offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            offset = 0
        game = ""
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

    def content_install(self, kind, project_id, loader="any", slug=None):
        kind = self._content_kind(kind)
        if kind == "mod":
            return self.mods_install(project_id, loader, slug)
        if kind == "modpack":
            return self.modpack_install(project_id, slug)
        return self.pack_install(kind, project_id, loader, slug)

    def content_uninstall(self, kind, project_id, filename=None):
        kind = self._content_kind(kind)
        if kind == "mod":
            return self.mods_uninstall(project_id, filename)
        if kind in PACK_DIRS:
            return self.pack_uninstall(kind, project_id, filename)
        return {"ok": False,
                "error": "Modpacks are profiles — remove the profile instead."}

    def content_update(self, kind, project_id, loader="any", slug=None):
        kind = self._content_kind(kind)
        if kind == "mod":
            return self.mods_update(project_id, loader, slug)
        if kind in PACK_DIRS:
            return self.pack_update(kind, project_id, loader, slug)
        return {"ok": False, "error": "Modpacks are installed as profiles."}

    def pack_install(self, kind, project_id, loader="any", slug=None):
        instance, game, _detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if kind not in PACK_DIRS:
            return {"ok": False, "error": "Unknown pack type."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "packs"
        self._event("busy", task="packs", on=True)
        loader = str(loader or "any")
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

    def pack_update(self, kind, project_id, loader="any", slug=None):
        instance, game, _detected = self._instance_game()
        if instance is None:
            return {"ok": False, "error": "No profile selected."}
        if kind not in PACK_DIRS:
            return {"ok": False, "error": "Unknown pack type."}
        if self.busy:
            return {"ok": False, "error": "Another task is already running."}
        self.busy = "packs"
        self._event("busy", task="packs", on=True)
        loader = str(loader or "any")
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
            self._status("mods", f"Downloading {name}…")
            self._event("busy", task="modpack", on=True,
                        label=f"Downloading {name}")
            with tempfile.TemporaryDirectory(prefix="launcher-pack-") as tmp:
                target = Path(tmp) / name
                download_file(file["url"], target)
                self.busy = ""
                self._event("busy", task="modpack", on=False)
                return self.import_modpack(str(target))
        except Exception as exc:
            message = f"Could not install the modpack: {exc}"
            self._status("mods", message, error=True)
            return {"ok": False, "error": message}
        finally:
            self.busy = ""
            self._event("busy", task="modpack", on=False)

    # -- loaders ------------------------------------------------------------

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
            profile = install_loader(loader_key, base, loader_version, java, log)
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

    # -- logs ---------------------------------------------------------------

    def logs_open(self):
        instance = self.active_instance()
        if instance is None:
            return {"path": "", "text": "", "exists": False}
        path = instance_log_file(instance["_root"])
        self._log_path = path
        self._log_pos = 0
        try:
            size = path.stat().st_size
        except OSError:
            return {"path": str(path), "text": "", "exists": False}
        start = max(0, size - MAX_LOG_BACKLOG)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return {"path": str(path), "text": "", "exists": False}
        self._log_pos = size
        text = data.decode("utf-8", "replace")
        if start:
            text = text.partition("\n")[2]
        return {"path": str(path), "text": text, "exists": True}

    def logs_read(self):
        if self._log_path is None:
            return {"text": ""}
        try:
            size = self._log_path.stat().st_size
        except OSError:
            return {"text": ""}
        reset = size < self._log_pos
        if reset:
            self._log_pos = 0
        if size == self._log_pos:
            return {"text": "", "reset": False}
        try:
            with self._log_path.open("rb") as handle:
                handle.seek(self._log_pos)
                data = handle.read()
        except OSError:
            return {"text": ""}
        self._log_pos = size
        return {"text": data.decode("utf-8", "replace"), "reset": reset}

    # -- launching ----------------------------------------------------------

    def _game_line(self, line):
        if self._log_queue.qsize() < 5000:
            self._log_queue.put(line)

    def _game_running(self):
        process = self._game_process
        try:
            return bool(process is not None and process.poll() is None)
        except (OSError, ValueError):
            return False

    def _kill_game(self, process):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            else:
                process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _watch_game(self, process):
        """Announce the game's exit so the Play button comes back."""
        try:
            process.wait()
        except Exception:
            pass
        with self._game_lock:
            if self._game_process is not process:
                return
            self._game_process = None
            self._game_slug = ""
        self._event("gameproc", running=False,
                    message="The game has closed.")

    def game_stop(self):
        with self._game_lock:
            process = self._game_process
        if process is None or process.poll() is not None:
            with self._game_lock:
                if self._game_process is process:
                    self._game_process = None
                    self._game_slug = ""
            self._event("gameproc", running=False, message="Game stopped.")
            return {"ok": True, "message": "Game stopped."}
        self._kill_game(process)
        with self._game_lock:
            stopped = self._game_process is process
            if stopped:
                self._game_process = None
                self._game_slug = ""
        if stopped:
            self._event("gameproc", running=False, message="Game stopped.")
        return {"ok": True, "message": "Game stopped."}

    def game_restart(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Create or select a profile first."}
        if self._launching:
            return {"ok": False, "error": "The game is already starting."}
        with self._game_lock:
            running_slug = self._game_slug
        if running_slug and instance.get("_slug") != running_slug:
            return {"ok": False,
                    "error": "Switch back to the running profile to restart."}
        self.game_stop()
        return self.play()

    def play(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Create or select a profile first."}
        if self._launching:
            return {"ok": False, "error": "The game is already starting."}
        if self._game_running():
            return {"ok": False, "error": "The game is already running."}
        account = self._active_account()
        auth = None
        if account is not None and account["type"] == "microsoft":
            token = self._ms_refresh(account)
            if not token:
                message = ("This Microsoft account needs to sign in again. "
                           "Remove it and add it from Settings.")
                self._event("play", ok=False, message=message)
                return {"ok": False, "error": message}
            auth = {"name": account["name"],
                    "uuid": account["uuid"],
                    "token": token, "xuid": account.get("xuid", ""),
                    "kind": "microsoft"}
            player = auth["name"]
        elif account is not None and account["type"] == "ely":
            token = self._ely_refresh(account)
            if not token:
                message = ("This Ely.by account needs to sign in again. "
                           "Remove it and add it from Settings.")
                self._event("play", ok=False, message=message)
                return {"ok": False, "error": message}
            auth = {"name": account["name"],
                    "uuid": account["uuid"],
                    "token": token, "xuid": "", "kind": "ely"}
            player = auth["name"]
        else:
            player = (account["name"] if account is not None
                      else self.player).strip() or "Player"
            if account is None:
                self.player = player
                self._save()
        self._launching = True
        self._event("play", ok=True, starting=True, message="Starting…")
        try:
            version_id = str(instance.get("version", ""))
            meta = version_meta(version_id)
            if not Path(meta).is_file():
                raise RuntimeError(f'Version "{version_id}" is not installed')
            version = load_version(meta)
            progress_shown = [0]

            def java_progress(done, total):
                if not total:
                    return
                percent = int(done * 100 / total)
                if percent >= progress_shown[0] + 10 or done == total:
                    progress_shown[0] = percent
                    self._game_line(f"Java download: {percent}%")

            try:
                java = ensure_java(version, self._game_line, java_progress,
                                   None)
                self._game_line(f"Java: {java}")
            except Exception as exc:
                raise RuntimeError(f"Java is not available: {exc}") from exc
            game_dir = instance_game_dir(instance["_root"])
            game_dir.mkdir(parents=True, exist_ok=True)
            if auth and auth.get("kind") == "ely":
                auth["authlib"] = str(ensure_authlib_injector())
            command, missing = build_command(
                version, meta, player, int(self.ram), game_dir, auth=auth)
            if missing:
                shown = ", ".join(missing[:3])
                extra = "" if len(missing) <= 3 \
                    else f" and {len(missing) - 3} more"
                raise RuntimeError(f"Missing files: {shown}{extra}")
            mode = ("Ely.by account"
                    if auth and auth.get("kind") == "ely"
                    else "Microsoft account" if auth else "offline mode")
            self._game_line(
                f"--- launching {instance_label(instance)} as {player} "
                f"({int(self.ram)} GB, {mode}) ---")
            process = subprocess.Popen(
                command, cwd=str(game_dir), close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == "nt" else 0,
            )
        except Exception as exc:
            self._game_line(f"ERROR: {exc}")
            self._launching = False
            self._event("play", ok=False, message=str(exc))
            return {"ok": False, "error": str(exc)}
        threading.Thread(target=self._read_stderr, args=(process,),
                         daemon=True).start()
        with self._game_lock:
            self._game_process = process
            self._game_slug = str(instance.get("_slug", ""))
        threading.Thread(target=self._watch_game, args=(process,),
                         daemon=True).start()
        self._launching = False
        message = f'{instance.get("name", "Minecraft")} is running.'
        self._event("play", ok=True, starting=False, running=True,
                    message=message)
        return {"ok": True, "message": message}

    def _read_stderr(self, process):
        stream = process.stderr
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._game_line(line)
        except (OSError, ValueError):
            pass

    # -- polling ------------------------------------------------------------

    def poll(self):
        events = []
        while len(events) < 400:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        while len(events) < 400:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            events.append({"t": "game", "line": line})
        return {"events": events, "busy": self.busy,
                "launching": self._launching}


def webui_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "webui" / "index.html"


def main():
    setup_logging()
    log.info("main: starting")
    try:
        import webview
    except Exception:
        log.exception("main: could not import webview")
        raise

    api = LauncherApi()
    page = webui_path()
    log.info("main: webui=%s exists=%s", page, page.is_file())
    window = webview.create_window(
        "Nexi Launcher", str(page), js_api=api,
        width=1180, height=780, min_size=(1000, 690),
        background_color="#0a0a0a",
    )
    window.events.closing += api.on_close

    def on_loaded():
        log.info("main: page loaded, bridge ready")

    window.events.loaded += on_loaded
    log.info("main: starting webview (gui=edgechromium, debug=%s)",
             bool(os.environ.get("MC_LAUNCHER_DEBUG")))
    webview.start(debug=bool(os.environ.get("MC_LAUNCHER_DEBUG")),
                  gui="edgechromium")
    log.info("main: webview stopped")


if __name__ == "__main__":
    main()
