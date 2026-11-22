"""Third-party modpack archives (.zip / .mrpack)."""

import re
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import curseforge
from .config import LOADER_LABELS
from .java_runtime import java_executable
from .net import _download_many
from .util import InstallCancelled


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


def _download_curseforge_manifest(files, game_dir: Path, log, progress,
                                  cancel) -> int:
    """Resolve manifest projectID/fileID pairs and download the files."""
    entries = []
    seen = set()
    for item in files or []:
        if not isinstance(item, dict) or item.get("required") is False:
            continue
        project = str(item.get("projectID") or "").strip()
        file_id = str(item.get("fileID") or "").strip()
        if not project or not file_id or (project, file_id) in seen:
            continue
        seen.add((project, file_id))
        entries.append((project, file_id))
    if not entries:
        return 0
    log(f"Resolving {len(entries)} CurseForge files…")
    mods_dir = Path(game_dir) / "mods"
    workers = 8 if curseforge.has_api_key() else 3
    jobs = []
    with ThreadPoolExecutor(
            max_workers=min(workers, len(entries))) as pool:
        futures = {
            pool.submit(curseforge.resolve_manifest_file, project, file_id):
            (project, file_id)
            for project, file_id in entries
        }
        for done, future in enumerate(as_completed(futures), 1):
            if cancel is not None and cancel.is_set():
                raise InstallCancelled()
            project, file_id = futures[future]
            try:
                info = future.result()
            except Exception as exc:
                info = None
                log(f"SKIP CurseForge file {project}/{file_id}: {exc}")
            if not info:
                log(f"WARNING: CurseForge file {project}/{file_id} "
                    "could not be resolved.")
            else:
                target = _zip_member_target(
                    mods_dir, str(info.get("filename") or ""))
                if target is None:
                    log(f"SKIP unsafe CurseForge file name: "
                        f"{info.get('filename')}")
                else:
                    jobs.append((info["url"], target, info.get("filesize")))
            if progress and (done == len(entries) or done % 10 == 0):
                progress(done, len(entries))
    _download_many(jobs, log, progress, cancel)
    return len(jobs)


def java_available(version_data: dict) -> bool:
    exe = java_executable(version_data)
    if Path(exe).is_file():
        return True
    if exe in ("java", "javaw"):
        return shutil.which("java") is not None or shutil.which("javaw") is not None
    return False
