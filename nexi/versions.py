"""Minecraft version metadata, classpath and launch arguments."""

import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path

from .config import APP_NAME, ARCH, ELY_JAVA_AGENT, MC, OS_NAME
from .java_runtime import java_executable


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
