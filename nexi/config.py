"""Paths, directories and constants shared by every module."""

import os
import platform
import shutil
import sys
from pathlib import Path


APP_NAME = "Nexi Launcher"


def app_dir() -> Path:
    """Folder that holds the exe (frozen) or this script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Folder for everything the launcher itself writes.

    ``%APPDATA%\\NexiLauncher`` keeps the folder with the exe clean and still
    works when the exe is stored in a read-only location.
    """
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "NexiLauncher"
    return Path.home() / ".nexi-launcher"


DATA_DIR = data_dir()


LOG_DIR = DATA_DIR / "logs"


LOG_FILE = LOG_DIR / "launcher.log"


SKINS_DIR = DATA_DIR / "skins"


BACKGROUNDS_DIR = DATA_DIR / "backgrounds"


INSTANCES_DIR = DATA_DIR / "instances"


def migrate_legacy_files():
    """Move data older versions kept next to the exe into ``DATA_DIR``."""
    legacy = app_dir()
    try:
        if legacy.resolve() == DATA_DIR.resolve():
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        names = ["settings.json", "skins"]
        names += [path.name for path in legacy.glob("authlib-injector-*.jar")]
    except OSError:
        return
    for name in names:
        source = legacy / name
        target = DATA_DIR / name
        if not source.exists() or target.exists():
            continue
        try:
            shutil.move(str(source), str(target))
        except OSError:
            try:
                shutil.copy2(source, target)
            except OSError:
                pass
    old_logs = legacy / "logs"
    if old_logs.is_dir():
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            for path in list(old_logs.iterdir()):
                if not path.is_file():
                    continue
                target = LOG_DIR / path.name
                if target.exists():
                    target = LOG_DIR / f"{path.name}.old"
                    counter = 1
                    while target.exists():
                        target = LOG_DIR / f"{path.name}.old{counter}"
                        counter += 1
                try:
                    shutil.move(str(path), str(target))
                except OSError:
                    pass
            old_logs.rmdir()
        except OSError:
            pass


def migrate_legacy_instances():
    """Move profiles that used to live inside the shared Minecraft folder."""
    legacy = MC / "instances"
    if not legacy.is_dir() or INSTANCES_DIR.exists():
        return
    try:
        INSTANCES_DIR.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(INSTANCES_DIR)
        return
    except OSError:
        pass
    # Same-volume rename can fail while the game still holds a file open; fall
    # back to a copy into a temporary folder so a partial copy is never used.
    tmp = INSTANCES_DIR.with_name(INSTANCES_DIR.name + ".tmp")
    try:
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(legacy, tmp)
        tmp.rename(INSTANCES_DIR)
    except OSError:
        try:
            shutil.rmtree(tmp)
        except OSError:
            pass


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


MODRINTH_API = "https://api.modrinth.com/v2"


USER_AGENT = "NexiLauncher/1.1 (local launcher, no account)"


LOADERS = ("any", "fabric", "forge", "neoforge", "quilt")


LOADER_LABELS = {"fabric": "Fabric", "forge": "Forge", "neoforge": "NeoForge"}


UI_LOADER_KEYS = {"Fabric": "fabric", "Forge": "forge", "NeoForge": "neoforge"}


MAX_LOG_BACKLOG = 200_000


ELY_OAUTH_REDIRECT_DEFAULT = "http://localhost:26206/ely-callback"


# Nexi site used for account sign-in. The default is the LAN address of the
# site, so every launcher in the local network can sign in, not only the
# machine that hosts it. Kept editable in Settings → Accounts for a public
# domain.
NEXI_BASE_URL_DEFAULT = "http://192.168.0.32:5000"


# Addresses older builds saved as the default. They only work on the machine
# hosting the site, so they are treated as "not chosen" and replaced with
# ``NEXI_BASE_URL_DEFAULT``.
NEXI_BASE_URL_LEGACY = ("http://127.0.0.1:5000", "http://localhost:5000")


ELY_JAVA_AGENT = "ely.by"


ELY_SKIN_SITE = "https://ely.by/skins"


ELY_SKIN_TEXTURE_URL = "https://skinsystem.ely.by/textures/{name}"
