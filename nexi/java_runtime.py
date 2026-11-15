"""Bundled Java runtime download and Java discovery."""

import json
import os
import platform
import re
import shutil
import subprocess
import threading
from pathlib import Path

from . import config
from .config import ARCH, MC, OS_NAME
from .net import _download_many, http_get
from .util import InstallCancelled


def _java_runtime_intact(javaw: Path) -> bool:
    """A Mojang runtime is only usable once its lib folder arrived too.

    ``bin\\javaw.exe`` can be on disk while the download or extraction was cut
    short; Java then dies with "could not open ...\\lib\\jvm.cfg".
    """
    javaw = Path(javaw)
    if not javaw.is_file():
        return False
    if platform.system() == "Windows":
        return (javaw.parent.parent / "lib" / "jvm.cfg").is_file()
    return True


def java_executable(version: dict) -> str:
    if config.JAVA_OVERRIDE:
        return config.JAVA_OVERRIDE
    component = (version.get("javaVersion") or {}).get("component", "")
    runtime = MC / "runtime" / component
    if component and runtime.is_dir():
        for javaw in runtime.rglob("javaw.exe" if platform.system() == "Windows" else "java"):
            if javaw.is_file() and _java_runtime_intact(javaw):
                return str(javaw)
    found = shutil.which("javaw") or shutil.which("java")
    if found:
        return found
    return "javaw" if platform.system() == "Windows" else "java"


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
            if found.is_file() and _java_runtime_intact(found):
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
            if found.is_file() and _java_runtime_intact(found):
                result = str(found)
                break
        if result:
            break
    if not result:
        raise RuntimeError("Java files were downloaded, but the runtime is "
                           "incomplete (lib/jvm.cfg is missing)")
    return result


def ensure_java(version: dict, log=lambda _text: None, progress=None,
                cancel=None) -> str:
    """Java for this version: an override, the system Java, or Mojang's build."""
    if config.JAVA_OVERRIDE:
        return config.JAVA_OVERRIDE
    existing = runtime_java_path(version)
    if existing:
        return existing
    component = str((version.get("javaVersion") or {}).get("component") or "")
    if component and (MC / "runtime" / component).is_dir():
        log("The Mojang Java runtime is incomplete — downloading it again.")

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
            + str(exc)
            + ". Check the connection or a VPN, then try again; you can also "
              "drop a Mojang runtime into .minecraft\\runtime or pick a Java "
              "in Settings.")
