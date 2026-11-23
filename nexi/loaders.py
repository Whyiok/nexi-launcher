"""Fabric / Forge / NeoForge build lists and installers."""

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .config import MC
from .java_runtime import java_executable
from .net import (download_file, download_with_retry, host_unreachable,
                  http_get, mirror_mode)
from .util import InstallCancelled
from .versions import (list_versions, load_version, neoforge_loader_version,
                       neoforge_runtime_paths, version_meta)


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


# Prism Launcher publishes the same loader builds through its own meta host.
# Pulling the list from there keeps NeoForge usable when the NeoForge maven is
# blocked and the BMCLAPI mirror is turned off in Settings → Network.
PRISM_META = "https://meta.prismlauncher.org/v1"


PRISM_NEOFORGE_INDEX = PRISM_META + "/net.neoforged/index.json"


PRISM_CACHE_SECONDS = 600


_prism_cache = {"at": 0.0, "entries": None}


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


def prism_neoforge_builds(game_version: str):
    """NeoForge builds from Prism Launcher's meta server, newest first.

    The index lists every build with the Minecraft version it targets, so no
    prefix guessing is needed. It is about 800 KB, hence the short cache: the
    page asks for the list again on every Refresh.
    """
    now = time.time()
    entries = _prism_cache["entries"]
    if entries is None or now - _prism_cache["at"] > PRISM_CACHE_SECONDS:
        data = json.loads(
            http_get(PRISM_NEOFORGE_INDEX, timeout=30).decode("utf-8"))
        entries = list(data.get("versions") or [])
        if not entries:
            raise ValueError("the Prism NeoForge index is empty")
        _prism_cache["entries"] = entries
        _prism_cache["at"] = now
    found = []
    for entry in entries:
        requires = entry.get("requires") or []
        if not any(item.get("uid") == "net.minecraft"
                   and str(item.get("equals") or "") == game_version
                   for item in requires):
            continue
        version = str(entry.get("version") or "").strip()
        if version:
            found.append((version, version))
    stable = [pair for pair in found if "-beta" not in pair[0].lower()]
    return (stable or found)[:MAX_BUILDS]


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
    # With the mirror turned off there is no BMCLAPI list to match the
    # installers against, so Prism's meta index supplies the versions even
    # when maven.neoforged.net is blocked. With the mirror on, the list comes
    # from the same place the installer will come from, so every version shown
    # can actually be downloaded.
    prism = []
    prism_tried = False
    if mirror_mode() == "never":
        prism_tried = True
        try:
            prism = prism_neoforge_builds(game_version)
        except (OSError, ValueError, ET.ParseError):
            prism = []
        if prism:
            return prism

    legacy = _is_legacy_neoforge(game_version)
    error = None
    pairs = []
    try:
        if legacy:
            versions = _versions_of_game(
                _maven_versions(NEOFORGE_LEGACY_METADATA, notify), game_version)
            pairs = [(value, value) for value in versions[:MAX_BUILDS]]
        else:
            all_versions = _maven_versions(NEOFORGE_METADATA, notify)
            for prefix in neoforge_prefixes(game_version):
                matching = [v for v in all_versions if v.startswith(prefix)]
                if not matching:
                    continue
                stable = [v for v in matching if "-beta" not in v.lower()]
                pairs = [(value, value) for value in
                         list(reversed(stable or matching))[:MAX_BUILDS]]
                break
    except (OSError, ValueError, ET.ParseError) as exc:
        error = exc
    if pairs:
        return pairs
    if error is not None and not prism_tried:
        try:
            prism = prism_neoforge_builds(game_version)
        except (OSError, ValueError, ET.ParseError):
            prism = []
    if prism:
        return prism
    if isinstance(error, OSError):
        raise RuntimeError(
            "maven.neoforged.net is unreachable; set Settings → Network → "
            "Mirror to Auto, or add the host to the bypass in the Bypass tab.")
    if error is not None:
        raise RuntimeError(f"The NeoForge build list could not be read: {error}")
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


class InstallerError(RuntimeError):
    """Non-zero installer exit; ``transient`` marks network download failures."""

    def __init__(self, code: int, transient: bool = False):
        super().__init__(f"installer exited with code {code}")
        self.transient = transient


_TRANSIENT_MARKERS = (
    "sockettimeoutexception", "connect timed out", "connection timed out",
    "read timed out", "unknownhostexception", "connection reset",
    "sslhandshakeexception", "failed to download",
)


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
    transient = False
    stream = process.stdout
    if stream is not None:
        for raw in stream:
            if cancel is not None and cancel.is_set():
                process.terminate()
                raise InstallCancelled()
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                if not transient:
                    low = line.lower()
                    transient = any(m in low for m in _TRANSIENT_MARKERS)
                log(line)
    code = process.wait()
    if code != 0:
        raise InstallerError(code, transient)


def run_installer_with_retries(java: str, installer: Path, log, cancel=None,
                               loader_key: str = "",
                               patched: bool = False) -> None:
    """Run the installer, retrying when its library downloads time out.

    The installer keeps every library it saves, so a retry only fetches the
    files that failed. For NeoForge a second failure switches the embedded
    installer URLs to the BMCLAPI mirror before the last attempt.
    """
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            run_installer(java, installer, log, cancel)
            return
        except InstallerError as exc:
            # A mirrored installer is retried even for an unknown failure:
            # BMCLAPI redirects can end the run after most files were saved.
            if attempt == attempts or not (exc.transient or patched):
                raise
            if (loader_key == "neoforge" and not patched and attempt >= 2
                    and mirror_mode() != "never"):
                patched = mirror_neoforge_installer(installer, log)
            log("Some downloads timed out — retrying the installer; "
                "libraries already saved are reused…")
            time.sleep(1)


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


def neoforge_runtime_missing(version_id: str) -> list:
    """NeoForge runtime jars that are absent, as paths.

    These are the universal jar (the "neoforge" system mod), the
    installer-generated client overlay and the NeoForm srg/extra game jars.
    None of them is listed in the version JSON, so the regular file check
    never sees them.
    """
    if not neoforge_loader_version(version_id):
        return []
    try:
        version = load_version(version_meta(version_id))
    except (OSError, ValueError):
        return []
    return [path for path in neoforge_runtime_paths(version)
            if not path.is_file()]


def neoforge_runtime_installed(version_id: str) -> bool:
    """True when the jars the version JSON does not mention are on disk.

    A profile whose JSON exists but whose runtime jars were never downloaded
    (an interrupted installer, a reused stale profile) starts and then aborts
    with "Missing mandatory dependency: minecraft/neoforge".
    """
    return not neoforge_runtime_missing(version_id)


def repair_neoforge_runtime(version_id: str, java: str, log,
                            cancel=None) -> bool:
    """Rebuild a NeoForge profile whose runtime jars are missing."""
    if not neoforge_loader_version(version_id):
        return True
    if neoforge_runtime_installed(version_id):
        return True
    url = loader_installer_url("neoforge", "", neoforge_loader_version(version_id))
    temp_root = Path(tempfile.mkdtemp(prefix="mc-neoforge-repair-"))
    installer = temp_root / "installer.jar"
    try:
        def mirror_notice(host):
            log(f"{host} is unreachable — switching to the BMCLAPI mirror…")

        log(f"NeoForge {neoforge_loader_version(version_id)} is missing its "
            f"runtime jars — running the installer again…")
        from_mirror = download_with_retry(
            url, installer, cancel=cancel, on_fallback=mirror_notice)
        patched = False
        if (mirror_mode() != "never"
                and (from_mirror or host_unreachable(url))):
            patched = mirror_neoforge_installer(installer, log)
        run_installer_with_retries(java, installer, log, cancel,
                                   "neoforge", patched)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return neoforge_runtime_installed(version_id)


def find_loader_profile(loader_key: str, game_version: str, loader_version: str):
    wanted = loader_version.lower()
    for vid, _meta in list_versions():
        low = vid.lower()
        if loader_key == "forge" and "neoforge" in low:
            continue
        if loader_key in low and wanted in low:
            if loader_key == "neoforge" and not neoforge_runtime_installed(vid):
                continue
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

        try:
            from_mirror = download_with_retry(url, installer, cancel=cancel,
                                              on_progress=progress,
                                              on_fallback=mirror_notice)
        except InstallCancelled:
            raise
        except Exception as exc:
            if loader_key == "neoforge" and host_unreachable(url):
                raise RuntimeError(
                    "maven.neoforged.net is unreachable; set Settings → "
                    "Network → Mirror to Auto, or add the host to the bypass "
                    "in the Bypass tab.") from exc
            raise
        if progress:
            progress(0, 0)
        log(f"Installer saved ({installer.stat().st_size // 1024} KB)")
        if from_mirror:
            log("The installer came from the BMCLAPI mirror.")
        patched = False
        if (loader_key == "neoforge" and mirror_mode() != "never"
                and (from_mirror or host_unreachable(url))):
            patched = mirror_neoforge_installer(installer, log)
        log("Running the installer — it fetches libraries itself, so this "
            "can take a few minutes…")
        run_installer_with_retries(java, installer, log, cancel,
                                   loader_key, patched)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    new_ids = sorted(installed_version_ids() - before)
    profile = ""
    for vid in new_ids:
        low = vid.lower()
        if loader_key == "neoforge":
            if "neoforge" in low:
                profile = vid
                break
        elif loader_key in low and "neoforge" not in low:
            profile = vid
            break
    if not profile and new_ids:
        profile = new_ids[0]
    if not profile:
        profile = find_loader_profile(loader_key, game_version, loader_version)
    if (profile and loader_key == "neoforge"
            and not neoforge_runtime_installed(profile)):
        # The installer writes the profile before it saves the universal and
        # client jars; if those downloads failed, run it once more.
        if not repair_neoforge_runtime(profile, java, log, cancel):
            raise RuntimeError(
                "NeoForge installed its profile but the universal/client jars "
                "are missing. Check the network or the bypass and try again.")
    return profile


def console_java_for(version_id: str) -> str:
    """Console Java binary for an installed version id, best effort."""
    meta = version_meta(version_id)
    if not meta.is_file():
        return "java"
    try:
        return console_java(load_version(meta))
    except (OSError, json.JSONDecodeError):
        return "java"
