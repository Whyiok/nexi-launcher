"""Fabric / Forge / NeoForge build lists and installers."""

import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .config import MC
from .java_runtime import java_executable
from .net import (download_file, download_with_retry, host_unreachable,
                  http_get)
from .util import InstallCancelled
from .versions import list_versions, load_version, version_meta


FABRIC_META = "https://meta.fabricmc.net/v2"


FORGE_PROMOTIONS = ("https://files.minecraftforge.net/net/minecraftforge/"
                    "forge/promotions_slim.json")


FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"


FORGE_METADATA = FORGE_MAVEN + "/maven-metadata.xml"


NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"


NEOFORGE_METADATA = NEOFORGE_MAVEN + "/maven-metadata.xml"


NEOFORGE_LEGACY_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/forge"


NEOFORGE_LEGACY_METADATA = NEOFORGE_LEGACY_MAVEN + "/maven-metadata.xml"


NEOFORGE_OFFICIAL_BASE = "https://maven.neoforged.net/releases/"


NEOFORGE_MIRROR_BASE = "https://bmclapi2.bangbang93.com/maven/"


LOADER_KEYS = {"Fabric": "fabric", "Forge": "forge", "NeoForge": "neoforge"}


MAX_BUILDS = 20


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


def _maven_versions(url: str, notify=None):
    # NeoForge/Forge maven answers slowly through a DPI bypass.
    root = ET.fromstring(http_get(url, timeout=60, on_fallback=notify))
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
    data = json.loads(http_get(url, timeout=60).decode("utf-8"))
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
        promotions = json.loads(http_get(FORGE_PROMOTIONS, timeout=60).decode("utf-8"))
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


def neoforge_builds(game_version: str, notify=None):
    if _is_legacy_neoforge(game_version):
        try:
            versions = _versions_of_game(
                _maven_versions(NEOFORGE_LEGACY_METADATA, notify), game_version)
        except (OSError, ValueError, ET.ParseError):
            return []
        return [(value, value) for value in versions[:MAX_BUILDS]]
    try:
        all_versions = _maven_versions(NEOFORGE_METADATA, notify)
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


def loader_builds(loader_key: str, game_version: str, notify=None):
    if loader_key == "fabric":
        return fabric_builds(game_version)
    if loader_key == "forge":
        return forge_builds(game_version)

    def mirror_note(host):
        if notify is not None:
            notify(f"{host} is unreachable — the build list came from the "
                   f"BMCLAPI mirror.")

    return neoforge_builds(game_version, mirror_note)


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


def mirror_neoforge_installer(installer: Path, log) -> bool:
    """Point the installer's own downloads at BMCLAPI when NeoForge is blocked.

    The installer resolves its libraries from URLs embedded in
    install_profile.json and version.json. If maven.neoforged.net is blocked,
    those downloads fail before it can write the profile, so rewrite the two
    JSON entries to the BMCLAPI mirror. The installer archive is not signed.
    Returns True when the archive was changed.
    """
    temp = installer.with_name(installer.name + ".mirrored")
    changed = 0
    try:
        with zipfile.ZipFile(installer) as source, \
                zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename in ("install_profile.json", "version.json"):
                    text = data.decode("utf-8")
                    if NEOFORGE_OFFICIAL_BASE in text:
                        changed += text.count(NEOFORGE_OFFICIAL_BASE)
                        data = text.replace(NEOFORGE_OFFICIAL_BASE,
                                            NEOFORGE_MIRROR_BASE).encode("utf-8")
                target.writestr(item, data)
    except (OSError, zipfile.BadZipFile):
        temp.unlink(missing_ok=True)
        raise
    if not changed:
        temp.unlink(missing_ok=True)
        return False
    temp.replace(installer)
    log(f"NeoForge maven is blocked — {changed} installer URLs switched "
        f"to the BMCLAPI mirror.")
    return True


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


def run_installer(java: str, installer: Path, log, cancel=None) -> None:
    ensure_launcher_profiles()
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
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
            if cancel is not None and cancel.is_set():
                process.terminate()
                raise InstallCancelled()
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                log(line)
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"installer exited with code {code}")


def install_fabric(game_version: str, loader_version: str, log,
                   progress=None, cancel=None) -> str:
    url = (f"{FABRIC_META}/versions/loader/"
           f"{urllib.parse.quote(game_version, safe='')}/"
           f"{urllib.parse.quote(loader_version, safe='')}/profile/json")
    log(f"Fetching Fabric {loader_version} profile for {game_version}…")
    profile = json.loads(http_get(url, timeout=60).decode("utf-8"))
    version_id = profile.get("id") or f"fabric-loader-{loader_version}-{game_version}"
    profile["id"] = version_id
    profile.setdefault("inheritsFrom", game_version)
    profile.setdefault("type", "release")

    folder = MC / "versions" / version_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{version_id}.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8")
    log(f"Wrote versions/{version_id}/{version_id}.json")

    libraries = profile.get("libraries") or []
    total = len(libraries)
    done = 0
    for lib in libraries:
        if cancel is not None and cancel.is_set():
            raise InstallCancelled()
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
        download_file(base_url.rstrip("/") + "/" + relative.as_posix(), target,
                      cancel=cancel)
        done += 1
        if progress and total:
            progress(done, total)
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
                   java: str, log, progress=None, cancel=None):
    """Install a loader and return the id of the profile it created.

    ``progress(done, total)`` reports determinate downloads; a reset to
    ``(0, 0)`` tells the page to show its indeterminate "working" animation.
    """
    if loader_key == "fabric":
        return install_fabric(game_version, loader_version, log, progress,
                              cancel)

    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    before = installed_version_ids()
    url = loader_installer_url(loader_key, game_version, loader_version)
    log(f"Downloading {url}")
    temp_root = Path(tempfile.mkdtemp(prefix="mc-loader-"))
    installer = temp_root / "installer.jar"
    try:
        # Retries and the BMCLAPI fallback cover a blocked maven host.
        def mirror_notice(host):
            log(f"{host} is unreachable — switching to the BMCLAPI mirror…")

        from_mirror = download_with_retry(url, installer, cancel=cancel,
                                          on_progress=progress,
                                          on_fallback=mirror_notice)
        if progress:
            progress(0, 0)
        log(f"Installer saved ({installer.stat().st_size // 1024} KB)")
        if from_mirror:
            log("The installer came from the BMCLAPI mirror.")
        patched = False
        if loader_key == "neoforge" and (from_mirror or host_unreachable(url)):
            patched = mirror_neoforge_installer(installer, log)
        log("Running the installer — it fetches libraries itself, so this "
            "can take a few minutes…")
        try:
            run_installer(java, installer, log, cancel)
        except RuntimeError:
            if not patched:
                raise
            # BMCLAPI serves some files through flaky redirects; the first
            # pass can save everything and still report a download failure.
            log("The installer stopped early; retrying with the files it "
                "already downloaded…")
            run_installer(java, installer, log, cancel)
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
