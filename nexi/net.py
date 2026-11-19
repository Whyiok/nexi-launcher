"""HTTP download helpers with the Mojang CDN / NeoForge maven mirror fallback."""

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


NEOFORGE_MAVEN_HOST = "maven.neoforged.net"


NEOFORGE_MIRROR_BASE = MIRROR_BASE + "/maven"


# A blocked official host should not freeze the interface. This is a hard
# wall-clock budget for the official attempt before the BMCLAPI copy is tried;
# a host that fails once is remembered for the rest of the session.
OFFICIAL_TIMEOUT = 15


# Large files (jars, assets) over a bypassed connection can be slow.
MIRROR_TIMEOUT = 180


MIRROR_PREFIXES = {
    "launchermeta.mojang.com": "",
    "piston-meta.mojang.com": "",
    "piston-data.mojang.com": "",
    "libraries.minecraft.net": "maven",
    "maven.minecraftforge.net": "maven",
    "resources.download.minecraft.net": "assets",
    # BMCLAPI serves Fabric's metadata tree under /fabric-meta and Fabric's
    # artifacts under /maven (its maven-metadata.xml is not mirrored, but the
    # launcher only downloads jars from there).
    "meta.fabricmc.net": "fabric-meta",
    "maven.fabricmc.net": "maven",
}


# The user's standing choice for the BMCLAPI mirror: "auto" keeps the official
# host first and falls back when it is blocked, "always" uses the mirror right
# away, and "never" keeps the official host so the DPI bypass can handle it.
MIRROR_MODES = ("auto", "always", "never")


_mirror_mode = "auto"


_mirror_mode_lock = threading.Lock()


def set_mirror_mode(mode: str) -> str:
    global _mirror_mode
    mode = str(mode or "").strip().lower()
    with _mirror_mode_lock:
        _mirror_mode = mode if mode in MIRROR_MODES else "auto"
        return _mirror_mode


def mirror_mode() -> str:
    with _mirror_mode_lock:
        return _mirror_mode


# The first automatic fallback asks the page to offer a permanent choice
# between the mirror and the bypass. One prompt per session is enough; after
# it is dismissed the user decides in Settings.
_mirror_notice = {"seq": 0, "host": "", "mirror": ""}


_mirror_notice_lock = threading.Lock()


_mirror_prompted = [False]


_mirror_notifier = [None]


def set_mirror_notifier(callback) -> None:
    """Register ``callback(host, mirror_host)`` for the one-time prompt."""
    _mirror_notifier[0] = callback


def _note_mirror_fallback(url: str) -> None:
    """Tell the page that a host fell back to the mirror (once per session)."""
    if mirror_mode() != "auto":
        return
    host = _url_host(url)
    if not host:
        return
    with _mirror_notice_lock:
        if _mirror_prompted[0]:
            return
        _mirror_prompted[0] = True
        _mirror_notice["seq"] += 1
        _mirror_notice["host"] = host
        _mirror_notice["mirror"] = _url_host(mirror_url(url))
        payload = dict(_mirror_notice)
    notifier = _mirror_notifier[0]
    if notifier is None:
        return
    try:
        notifier(payload["host"], payload["mirror"])
    except Exception:  # the prompt must never break a download
        logging.debug("mirror notifier failed", exc_info=True)


def mirror_notice() -> dict:
    with _mirror_notice_lock:
        return dict(_mirror_notice)


_unreachable_hosts = set()


_unreachable_lock = threading.Lock()


# Hosts that failed during this session; the zapret card suggests adding
# them to the bypass list.
_failed_hosts = set()


_failed_lock = threading.Lock()


def note_failed_host(host: str) -> None:
    """Remember a host that could not be loaded, for the zapret suggestion."""
    host = str(host or "").strip().lower()
    if not host or "." not in host:
        return
    try:
        with _failed_lock:
            _failed_hosts.add(host)
    except Exception:  # diagnostics must never break a download
        pass


def _note_failed_url(url: str) -> None:
    note_failed_host(_url_host(url))


def failed_hosts() -> list:
    """Hosts that failed to load in this session, most recent last."""
    with _failed_lock:
        return sorted(_failed_hosts)


def clear_failed_hosts() -> None:
    with _failed_lock:
        _failed_hosts.clear()


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
    """The BMCLAPI equivalent of a Mojang CDN or NeoForge maven URL."""
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if host == NEOFORGE_MAVEN_HOST:
        path = parts.path.lstrip("/")
        for folder in ("releases/", "snapshots/"):
            if path.startswith(folder):
                path = path[len(folder):]
                break
        else:
            return ""
        return f"{NEOFORGE_MIRROR_BASE}/{path}"
    prefix = MIRROR_PREFIXES.get(host)
    if prefix is None:
        return ""
    path = parts.path.lstrip("/")
    return f"{MIRROR_BASE}/{prefix + '/' if prefix else ''}{path}"


def _host_unreachable(url: str) -> bool:
    with _unreachable_lock:
        return _url_host(url) in _unreachable_hosts


def host_unreachable(url: str) -> bool:
    """Whether this session already failed to reach the host of ``url``."""
    return _host_unreachable(url)


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
            with _failed_lock:
                _failed_hosts.discard(host)
    if unreachable:
        note_failed_host(host)
    if not was_known:
        if unreachable:
            network_event("warn", f"{host} is unreachable — "
                                  f"switched to the BMCLAPI mirror")
        else:
            network_event("ok", f"{host} is reachable again")


def _mirrored_get(mirrored: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        mirrored, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _official_get(request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _official_get_bounded(request, budget: float) -> bytes:
    """Fetch with a hard wall-clock limit, then let the mirror take over.

    urllib's timeout is per socket operation: a blackholed host can spend it
    on DNS/connect and again on the TLS handshake, so the real wait can be
    twice the configured value. The worker thread caps the total at
    ``budget`` seconds; if it is still stuck it finishes in the background
    and its answer is simply not used.
    """
    box = {}

    def run():
        try:
            box["data"] = _official_get(request, budget)
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=run, name="net-official", daemon=True)
    worker.start()
    worker.join(budget)
    if "data" in box:
        return box["data"]
    if "error" in box:
        raise box["error"]
    raise TimeoutError(f"no answer within {budget:g} s")


def http_get(url: str, timeout: float = 45, on_fallback=None) -> bytes:
    mode = mirror_mode()
    mirrored = mirror_url(url) if mode != "never" else ""
    if mirrored and (mode == "always" or _host_unreachable(url)):
        if on_fallback is not None:
            on_fallback(_url_host(url))
        if mode == "auto":
            _note_mirror_fallback(url)
        return _mirrored_get(mirrored, timeout)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # A blocked CDN should not stall startup for the full timeout.
        if mirrored:
            data = _official_get_bounded(
                request, min(timeout, OFFICIAL_TIMEOUT))
        else:
            data = _official_get(request, timeout)
        _mark_host(url, False)
        return data
    except urllib.error.HTTPError as exc:
        network_event("error", f"{_url_host(url)}: HTTP {exc.code} for {url}")
        # A 403/451 from a blocked host still means the mirror can help.
        if not mirrored or exc.code == 404:
            _note_failed_url(url)
            raise
        _mark_host(url, True)
        logging.info("%s answered HTTP %s; using the mirror",
                     _url_host(url), exc.code)
        if on_fallback is not None:
            on_fallback(_url_host(url))
        _note_mirror_fallback(url)
        return _mirrored_get(mirrored, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if not mirrored:
            network_event("error", f"{_url_host(url)}: {exc}")
            _note_failed_url(url)
            raise
        _mark_host(url, True)
        logging.info("%s unavailable (%s); using the mirror",
                     _url_host(url), exc)
        if on_fallback is not None:
            on_fallback(_url_host(url))
        _note_mirror_fallback(url)
        return _mirrored_get(mirrored, timeout)


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
    ("neoforge", "NeoForge maven (official)",
     "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
     "maven-metadata.xml"),
    ("neoforge-mirror", "NeoForge maven (BMCLAPI)",
     "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/"
     "maven-metadata.xml"),
]


def probe_url(url: str, timeout: float = 15.0) -> dict:
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
            note_failed_host(_url_host(item.get("url", "")))
            network_event("error",
                          f"check: {item['label']} is unreachable "
                          f"({item.get('error', '')})")
        else:
            network_event("ok", f"check: {item['label']} is reachable "
                              f"({item['ms']} ms)")
    return {"results": results, "blocked": blocked, "time": started}


def download_file(url: str, target: Path, size=None, cancel=None, timeout=180,
                  on_progress=None):
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
            if on_progress is None:
                shutil.copyfileobj(response, handle)
            else:
                total = 0
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                total = total or int(size or 0)
                done = 0
                last_report = 0.0
                while True:
                    if cancel is not None and cancel.is_set():
                        raise InstallCancelled()
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    # Unknown sizes keep the caller's indeterminate feedback.
                    if total and now - last_report >= 0.2:
                        last_report = now
                        on_progress(done, total)
                if total:
                    on_progress(done, total)
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _download_with_retry(url, target, size, cancel, on_progress=None,
                         on_fallback=None):
    """Retry transient network failures; fall back to the BMCLAPI mirror.

    A real 404 on every candidate is reported at once. When a CDN or maven
    host is known to be unreachable it is skipped for the rest of the session,
    so a blocked network costs one short timeout instead of one per file.
    ``on_fallback(host)`` fires once, right before the mirror is used.
    """
    mirrored = mirror_url(url) if mirror_mode() != "never" else ""
    mirror_announced = False

    def announce_mirror():
        nonlocal mirror_announced
        if mirror_announced or not mirrored:
            return
        mirror_announced = True
        _note_mirror_fallback(url)
        if on_fallback is None:
            return
        try:
            on_fallback(_url_host(url))
        except Exception:  # feedback must never break a download
            return

    last_error = None
    for attempt in range(3):
        # Recompute per attempt: a host that just failed is skipped next time.
        if not mirrored:
            candidates = [(url, MIRROR_TIMEOUT)]
        elif mirror_mode() == "always" or _host_unreachable(url):
            candidates = [(mirrored, MIRROR_TIMEOUT)]
            announce_mirror()
        else:
            # The official try is short: a blocked host should not add
            # minutes of waiting before the mirror takes over.
            candidates = [(url, OFFICIAL_TIMEOUT), (mirrored, MIRROR_TIMEOUT)]
        all_404 = True
        for candidate, timeout in candidates:
            if candidate != url:
                announce_mirror()
            try:
                download_file(candidate, target, size, cancel,
                              timeout=timeout, on_progress=on_progress)
                _mark_host(candidate, False)
                from_mirror = candidate != url
                if from_mirror:
                    logging.info("CDN unavailable; downloaded %s "
                                 "from the mirror", Path(target).name)
                return from_mirror
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
            _note_failed_url(url)
            network_event("error", f"{Path(target).name}: not found (404) "
                                  f"at {_url_host(candidates[-1][0])}")
            break
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        _note_failed_url(url)
        network_event("error", f"Could not download {Path(target).name} "
                              f"from {_url_host(url)}: {last_error}")
        raise last_error
    raise RuntimeError(f"Could not download {url}")


def download_with_retry(url, target, size=None, cancel=None, on_progress=None,
                        on_fallback=None):
    """Download one file with retries and the BMCLAPI mirror fallback.

    ``on_progress(done, total)`` is called while the body arrives when the
    server reports a size. ``on_fallback(host)`` is called once when the
    official host fails and the mirror takes over, so the page can explain the
    switch. Returns True when the file came from the mirror, not the original
    URL.
    """
    return _download_with_retry(url, Path(target), size, cancel, on_progress,
                                on_fallback)


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
