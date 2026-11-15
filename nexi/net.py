"""HTTP download helpers with the Mojang CDN mirror fallback."""

import collections
import logging
import shutil
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .config import MODRINTH_API, USER_AGENT
from .util import InstallCancelled


MIRROR_BASE = "https://bmclapi2.bangbang93.com"


MIRROR_PREFIXES = {
    "launchermeta.mojang.com": "",
    "piston-meta.mojang.com": "",
    "piston-data.mojang.com": "",
    "libraries.minecraft.net": "maven",
    "resources.download.minecraft.net": "assets",
}


_unreachable_hosts = set()


_unreachable_lock = threading.Lock()


NETWORK_LOG = collections.deque(maxlen=400)


_network_log_lock = threading.Lock()


_network_seq = [0]


def network_event(level: str, message: str) -> None:
    """Record one network event for the Settings → Network panel."""
    try:
        with _network_log_lock:
            _network_seq[0] += 1
            entry = {"seq": _network_seq[0],
                     "time": datetime.now().strftime("%H:%M:%S"),
                     "level": level, "message": str(message)}
            NETWORK_LOG.append(entry)
    except Exception:  # diagnostics must never break a download
        return
    logging.debug("network [%s] %s", level, message)


def _url_host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def mirror_url(url: str) -> str:
    """The BMCLAPI equivalent of a Mojang CDN URL, or "" for other hosts."""
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        return ""
    prefix = MIRROR_PREFIXES.get((parts.hostname or "").lower())
    if prefix is None:
        return ""
    path = parts.path.lstrip("/")
    return f"{MIRROR_BASE}/{prefix + '/' if prefix else ''}{path}"


def _host_unreachable(url: str) -> bool:
    with _unreachable_lock:
        return _url_host(url) in _unreachable_hosts


def _mark_host(url: str, unreachable: bool) -> None:
    """Remember which Mojang host timed out, so later files skip it."""
    host = _url_host(url)
    if not host:
        return
    with _unreachable_lock:
        if unreachable:
            was_known = host in _unreachable_hosts
            _unreachable_hosts.add(host)
        else:
            was_known = host not in _unreachable_hosts
            _unreachable_hosts.discard(host)
    if not was_known:
        if unreachable:
            network_event("warn", f"{host} is unreachable — "
                                  f"switched to the BMCLAPI mirror")
        else:
            network_event("ok", f"{host} is reachable again")


def http_get(url: str, timeout: float = 30) -> bytes:
    mirrored = mirror_url(url)
    if mirrored and _host_unreachable(url):
        request = urllib.request.Request(
            mirrored, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # A blocked CDN should not stall startup for the full timeout.
        official_timeout = 25 if mirrored else timeout
        with urllib.request.urlopen(request, timeout=official_timeout) as response:
            data = response.read()
        _mark_host(url, False)
        return data
    except urllib.error.HTTPError as exc:
        network_event("error", f"{_url_host(url)}: HTTP {exc.code} for {url}")
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if not mirrored:
            network_event("error", f"{_url_host(url)}: {exc}")
            raise
        _mark_host(url, True)
        logging.info("Mojang CDN unavailable for %s (%s); using the mirror",
                     _url_host(url), exc)
        request = urllib.request.Request(
            mirrored, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()


NETWORK_TARGETS = [
    ("launchermeta", "Mojang launcher metadata",
     "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"),
    ("piston-meta", "Mojang version metadata",
     "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"),
    ("piston-data", "Mojang game files",
     "https://piston-data.mojang.com/"),
    ("libraries", "Mojang libraries",
     "https://libraries.minecraft.net/org/ow2/asm/asm/9.6/asm-9.6.jar"),
    ("resources", "Mojang assets",
     "https://resources.download.minecraft.net/00/"
     "000b09dd0ac7ce50943baa154ca37fe22fadf602"),
    ("bmclapi", "BMCLAPI mirror",
     f"{MIRROR_BASE}/mc/game/version_manifest_v2.json"),
    ("modrinth-api", "Modrinth API",
     f"{MODRINTH_API}/tag/game_version"),
    ("modrinth-cdn", "Modrinth files",
     "https://cdn.modrinth.com/data/AANobbMI/icon.png"),
    ("fabric", "Fabric maven",
     "https://maven.fabricmc.net/net/fabricmc/fabric-loader/"
     "maven-metadata.xml"),
    ("forge", "Forge maven",
     "https://maven.minecraftforge.net/net/minecraftforge/forge/"
     "maven-metadata.xml"),
    ("neoforge", "NeoForge maven",
     "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
     "maven-metadata.xml"),
]


def probe_url(url: str, timeout: float = 8.0) -> dict:
    """Reach a host and report how long it took.

    Any HTTP answer counts as reachable: a 404 for a root path still means DNS
    and TLS worked and the CDN replied.
    """
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(2048)
            status = int(getattr(response, "status", 200) or 200)
        note = ""
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        note = f"HTTP {status}"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        reason = getattr(exc, "reason", exc)
        return {"ok": False, "status": 0, "ms": elapsed,
                "error": str(reason) or exc.__class__.__name__}
    return {"ok": True, "status": status, "note": note,
            "ms": int((time.perf_counter() - started) * 1000)}


def network_check() -> dict:
    """Probe every host in parallel; results stay in NETWORK_TARGETS order."""
    started = time.strftime("%H:%M:%S")
    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(NETWORK_TARGETS))) as pool:
        futures = {key: pool.submit(probe_url, url)
                   for key, _label, url in NETWORK_TARGETS}
        for key, label, url in NETWORK_TARGETS:
            outcome = futures[key].result()
            outcome.update({"key": key, "label": label, "url": url})
            results.append(outcome)
    with _unreachable_lock:
        blocked = sorted(_unreachable_hosts)
    for item in results:
        if not item["ok"]:
            network_event("error",
                          f"check: {item['label']} is unreachable "
                          f"({item.get('error', '')})")
        else:
            network_event("ok", f"check: {item['label']} is reachable "
                              f"({item['ms']} ms)")
    return {"results": results, "blocked": blocked, "time": started}


def download_file(url: str, target: Path, size=None, cancel=None, timeout=90):
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
        with urllib.request.urlopen(request, timeout=timeout) as response, \
                part.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _download_with_retry(url, target, size, cancel):
    """Retry transient network failures; fall back to the Mojang CDN mirror.

    A real 404 on every candidate is reported at once. When a Mojang host is
    known to be unreachable it is skipped for the rest of the session, so a
    blocked network costs one timeout instead of one per file.
    """
    mirrored = mirror_url(url)
    if not mirrored:
        candidates = [(url, 90)]
    elif _host_unreachable(url):
        candidates = [(mirrored, 90)]
    else:
        # The official try is short: a blocked CDN should not add 90 s per file.
        candidates = [(url, 20), (mirrored, 90)]
    last_error = None
    for attempt in range(3):
        all_404 = True
        for candidate, timeout in candidates:
            try:
                download_file(candidate, target, size, cancel,
                              timeout=timeout)
                _mark_host(candidate, False)
                if candidate != url:
                    logging.info("Mojang CDN unavailable; downloaded %s "
                                 "from the mirror", Path(target).name)
                return
            except InstallCancelled:
                raise
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code != 404:
                    all_404 = False
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                all_404 = False
                _mark_host(candidate, True)
        if all_404:
            network_event("error", f"{Path(target).name}: not found (404) "
                                  f"at {_url_host(candidates[-1][0])}")
            break
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        network_event("error", f"Could not download {Path(target).name} "
                              f"from {_url_host(url)}: {last_error}")
        raise last_error
    raise RuntimeError(f"Could not download {url}")


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
