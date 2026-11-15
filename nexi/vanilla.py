"""Vanilla version install and file verification."""

import hashlib
import json
import threading
from pathlib import Path

from .config import ARCH, MC, OS_NAME
from .loaders import maven_path
from .net import _download_many, _download_with_retry, http_get
from .util import InstallCancelled
from .versions import _for_this_machine, client_jar, rule_allows, version_meta


VERSION_MANIFEST_URLS = (
    "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
    "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
)


ASSET_OBJECTS_BASE = "https://resources.download.minecraft.net"


MOJANG_LIBRARIES = "https://libraries.minecraft.net"


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


def fetch_missing_libraries(version: dict, meta: Path, log) -> int:
    """Download the jars a version needs but that are not on disk yet.

    Used by Play as a self-repair step: a loader profile can list libraries
    that never arrived (an interrupted installer, a shared .minecraft, a
    modpack built on another machine). Best effort — one failed file must not
    abort the rest; the caller re-checks the classpath afterwards and reports
    whatever is still missing.
    """
    jobs = []
    seen = set()
    for url, target, size, _sha1 in _library_downloads(version, with_hash=True):
        key = str(target)
        if key in seen or Path(target).is_file():
            continue
        seen.add(key)
        jobs.append((url, target, size))
    client = client_jar(version, meta)
    client_info = (version.get("downloads") or {}).get("client") or {}
    if not client.is_file() and client_info.get("url"):
        jobs.append((client_info["url"], client, client_info.get("size")))
    if not jobs:
        return 0
    log(f"Downloading {len(jobs)} missing file(s)…")
    failed = 0
    for url, target, size in jobs:
        try:
            _download_with_retry(url, target, size, None)
        except Exception as exc:  # keep going: the caller re-checks the classpath
            failed += 1
            log(f"Could not download {Path(target).name}: {exc}")
    fetched = len(jobs) - failed
    log(f"Missing files: {fetched}/{len(jobs)} downloaded.")
    return fetched


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
