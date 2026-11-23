"""HTTP download helpers with the Mojang CDN / NeoForge maven mirror fallback."""

import collections
import ipaddress
import logging
import random
import re
import shutil
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import zipfile
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


# --- proxy and DNS ----------------------------------------------------------
#
# Both settings affect only the launcher's own connections. Requests to
# localhost and LAN addresses skip the proxy, and the game itself keeps using
# the system network.

_network_lock = threading.Lock()

_proxy_url = ""

_proxy_opener = None


def normalize_proxy(value) -> str:
    """Return a proxy URL urllib understands, or "" for a direct connection.

    Raises ``ValueError`` for anything that is not an http(s) host:port.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urllib.parse.urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid proxy") from exc
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or port is None or parts.path not in ("", "/")
            or parts.query or parts.fragment
            or parts.username is not None or parts.password is not None):
        raise ValueError("invalid proxy")
    return text.rstrip("/")


def set_proxy(value) -> str:
    """Use ``value`` as the HTTP/HTTPS proxy; "" connects directly."""
    global _proxy_url, _proxy_opener
    value = str(value or "").strip()
    with _network_lock:
        _proxy_url = value
        _proxy_opener = None
    return _proxy_url


def proxy_url() -> str:
    with _network_lock:
        return _proxy_url


def _host_is_private(host: str) -> bool:
    """Localhost, LAN, link-local and bare hostnames never use the proxy."""
    host = (host or "").strip().strip("[]").rstrip(".").lower()
    if not host or host == "localhost" \
            or host.endswith((".local", ".lan", ".home", ".internal",
                              ".localhost")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host
    return (address.is_loopback or address.is_private
            or address.is_link_local or address.is_unspecified)


def _url_is_private(url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(str(url)).hostname or ""
    except ValueError:
        return True
    return _host_is_private(host)


def _opener_for(url: str):
    with _network_lock:
        configured = _proxy_url
        if not configured or _url_is_private(url):
            return None
        if _proxy_opener is None:
            _proxy_opener = urllib.request.build_opener(
                urllib.request.ProxyHandler(
                    {"http": configured, "https": configured}))
        return _proxy_opener


def open_url(request, timeout=None):
    """``urlopen`` that honours the proxy and custom DNS settings."""
    url = getattr(request, "full_url", request)
    opener = _opener_for(str(url))
    if opener is None:
        if timeout is None:
            return urllib.request.urlopen(request)
        return urllib.request.urlopen(request, timeout=timeout)
    if timeout is None:
        return opener.open(request)
    return opener.open(request, timeout=timeout)


_dns_servers = ()

_dns_lock = threading.Lock()

_dns_cache = {}

_dns_cache_lock = threading.Lock()

_dns_warned = [False]

_system_getaddrinfo = socket.getaddrinfo


def parse_dns_servers(value):
    """Normalize a comma/space separated list of resolver IP addresses."""
    servers = []
    for part in re.split(r"[,;\s]+", str(value or "").strip()):
        if not part:
            continue
        address = str(ipaddress.ip_address(part))
        if address not in servers:
            servers.append(address)
    return tuple(servers)


def set_dns(value) -> str:
    """Route the launcher's name lookups through ``value``; "" is the OS DNS."""
    global _dns_servers
    try:
        servers = parse_dns_servers(value)
    except ValueError:
        servers = ()
    with _dns_lock:
        _dns_servers = servers
        with _dns_cache_lock:
            _dns_cache.clear()
        _dns_warned[0] = False
        if servers:
            if socket.getaddrinfo is not _dns_getaddrinfo:
                socket.getaddrinfo = _dns_getaddrinfo
        elif socket.getaddrinfo is _dns_getaddrinfo:
            socket.getaddrinfo = _system_getaddrinfo
        return ", ".join(servers)


def dns_servers():
    with _dns_lock:
        return _dns_servers


def _dns_skip_name(data, offset):
    while offset < len(data):
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1 + length
    return offset


def _dns_answers(data, query_id):
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != query_id:
        return []
    questions, answers = struct.unpack(">HH", data[4:8])
    offset = 12
    for _ in range(questions):
        offset = _dns_skip_name(data, offset) + 4
    found = []
    for _ in range(answers):
        offset = _dns_skip_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, ttl, length = struct.unpack(
            ">HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + length]
        offset += length
        if rtype == 1 and length == 4:
            found.append((socket.inet_ntoa(rdata), ttl))
    return found


def _dns_query(server, host, timeout=2.0):
    """Ask one resolver for the A records of ``host`` (plain UDP)."""
    try:
        name = host.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return []
    labels = [label for label in name.split(".") if label]
    if not labels:
        return []
    query_id = random.getrandbits(16)
    question = b"".join(
        bytes([len(label)]) + label.encode("ascii") for label in labels)
    packet = (struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
              + question + b"\x00" + struct.pack(">HH", 1, 1))
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (server, 53))
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline:
                return []
            data, _addr = sock.recvfrom(4096)
            if len(data) >= 12 \
                    and struct.unpack(">H", data[:2])[0] == query_id:
                return _dns_answers(data, query_id)


def _resolve_ipv4(host):
    host = host.strip("[]").rstrip(".").lower()
    now = time.monotonic()
    with _dns_cache_lock:
        cached = _dns_cache.get(host)
        if cached is not None and cached[0] > now:
            return cached[1]
    servers = dns_servers()
    for server in servers:
        try:
            answers = _dns_query(server, host)
        except OSError:
            continue
        addresses = []
        ttl = 300
        for address, answer_ttl in answers:
            if address not in addresses:
                addresses.append(address)
            ttl = min(ttl, max(30, int(answer_ttl)))
        if addresses:
            with _dns_cache_lock:
                _dns_cache[host] = (now + ttl, addresses)
            return addresses
    with _dns_cache_lock:
        _dns_cache[host] = (now + 30, [])
    if servers and not _dns_warned[0]:
        _dns_warned[0] = True
        network_event("warn", "Custom DNS did not answer; "
                              "using the system resolver")
    return []


def _dns_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if (not isinstance(host, str) or not dns_servers()
            or family == socket.AF_INET6 or flags & socket.AI_NUMERICHOST
            or _host_is_private(host)):
        return _system_getaddrinfo(host, port, family, type, proto, flags)
    try:
        ipaddress.ip_address(host.strip("[]"))
        return _system_getaddrinfo(host, port, family, type, proto, flags)
    except ValueError:
        pass
    addresses = _resolve_ipv4(host)
    if not addresses:
        return _system_getaddrinfo(host, port, family, type, proto, flags)
    results = []
    for address in addresses:
        try:
            results.extend(_system_getaddrinfo(
                address, port, family, type, proto, flags))
        except OSError:
            continue
    if not results:
        return _system_getaddrinfo(host, port, family, type, proto, flags)
    return results


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


def reset_host_state() -> None:
    """Forget failed hosts after the network settings changed."""
    with _unreachable_lock:
        _unreachable_hosts.clear()
    clear_failed_hosts()


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
    with open_url(request, timeout=timeout) as response:
        return response.read()


def _official_get(request, timeout: float) -> bytes:
    with open_url(request, timeout=timeout) as response:
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


NETWORK_GROUPS = [
    ("game", "Game files"),
    ("auth", "Accounts & skins"),
    ("mods", "Mods"),
    ("loaders", "Loaders"),
    ("updates", "Updates"),
]


NETWORK_TARGETS = [
    ("launchermeta", "Mojang launcher metadata", "game",
     "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"),
    ("piston-meta", "Mojang version metadata", "game",
     "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"),
    ("piston-data", "Mojang game files", "game",
     "https://piston-data.mojang.com/"),
    ("libraries", "Mojang libraries", "game",
     "https://libraries.minecraft.net/org/ow2/asm/asm/9.6/asm-9.6.jar"),
    ("resources", "Mojang assets", "game",
     "https://resources.download.minecraft.net/00/"
     "000b09dd0ac7ce50943baa154ca37fe22fadf602"),
    ("bmclapi", "BMCLAPI mirror", "game",
     f"{MIRROR_BASE}/mc/game/version_manifest_v2.json"),
    ("mojang-auth", "Mojang auth", "auth",
     "https://authserver.mojang.com/"),
    ("mojang-session", "Mojang session server", "auth",
     "https://sessionserver.mojang.com/session/minecraft/profile/"
     "069a79f444e94726a5befca90e38aaf5"),
    ("mojang-services", "Mojang login services", "auth",
     "https://api.minecraftservices.com/minecraft/profile"),
    ("mojang-skins", "Mojang skin textures", "auth",
     "https://textures.minecraft.net/"),
    ("microsoft-login", "Microsoft sign-in", "auth",
     "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"),
    ("xbox-user", "Xbox Live auth", "auth",
     "https://user.auth.xboxlive.com/"),
    ("xbox-xsts", "Xbox security token", "auth",
     "https://xsts.auth.xboxlive.com/"),
    ("ely-auth", "Ely.by auth", "auth",
     "https://authserver.ely.by/auth/authenticate"),
    ("ely-account", "Ely.by account", "auth",
     "https://account.ely.by/"),
    ("ely-skins", "Ely.by skins", "auth",
     "https://skinsystem.ely.by/textures/Notch"),
    ("modrinth-api", "Modrinth API", "mods",
     f"{MODRINTH_API}/tag/game_version"),
    ("modrinth-cdn", "Modrinth files", "mods",
     "https://cdn.modrinth.com/data/AANobbMI/icon.png"),
    ("curseforge-api", "CurseForge API", "mods",
     "https://api.curseforge.com/v1/mods/search?gameId=432&classId=6"
     "&searchFilter=jei&pageSize=1"),
    ("curseforge-site", "CurseForge site", "mods",
     "https://www.curseforge.com/"),
    ("curseforge-files", "CurseForge files", "mods",
     "https://mediafilez.forgecdn.net/"),
    ("cfwidget", "CFWidget lookup", "mods",
     "https://api.cfwidget.com/"),
    ("fabric", "Fabric maven", "loaders",
     "https://maven.fabricmc.net/net/fabricmc/fabric-loader/"
     "maven-metadata.xml"),
    ("fabric-meta", "Fabric meta", "loaders",
     "https://meta.fabricmc.net/v2/versions/loader"),
    ("forge", "Forge maven", "loaders",
     "https://maven.minecraftforge.net/net/minecraftforge/forge/"
     "maven-metadata.xml"),
    ("forge-promotions", "Forge promotions", "loaders",
     "https://files.minecraftforge.net/net/minecraftforge/forge/"
     "promotions_slim.json"),
    ("neoforge", "NeoForge maven (official)", "loaders",
     "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
     "maven-metadata.xml"),
    ("neoforge-mirror", "NeoForge maven (BMCLAPI)", "loaders",
     "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/"
     "maven-metadata.xml"),
    ("prism-meta", "Prism meta (NeoForge fallback)", "loaders",
     "https://meta.prismlauncher.org/v1/net.neoforged/index.json"),
    ("github-api", "GitHub API (updates)", "updates",
     "https://api.github.com/"),
    ("github-files", "GitHub release files", "updates",
     "https://objects.githubusercontent.com/"),
]


def probe_url(url: str, timeout: float = 15.0) -> dict:
    """Reach a host and report how long it took.

    Any HTTP answer counts as reachable: a 404 for a root path still means DNS
    and TLS worked and the CDN replied.
    """
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with open_url(request, timeout=timeout) as response:
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
    with ThreadPoolExecutor(max_workers=min(24, len(NETWORK_TARGETS))) as pool:
        futures = {key: pool.submit(probe_url, url)
                   for key, _label, _group, url in NETWORK_TARGETS}
        for key, label, group, url in NETWORK_TARGETS:
            outcome = futures[key].result()
            outcome.update({"key": key, "label": label, "url": url,
                            "group": group})
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
    used = {group for _key, _label, group, _url in NETWORK_TARGETS}
    groups = [{"id": gid, "title": title}
              for gid, title in NETWORK_GROUPS if gid in used]
    return {"results": results, "blocked": blocked, "time": started,
            "groups": groups}


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
        with open_url(request, timeout=timeout) as response, \
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
        # A blocked mirror can answer 200 with an HTML error page. Saving that
        # as a jar makes the game and the installers fail with a cryptic
        # "not a zip file", so reject it here and let the retry move on.
        if target.suffix.lower() in (".jar", ".zip"):
            try:
                with zipfile.ZipFile(part) as archive:
                    archive.infolist()
            except zipfile.BadZipFile as exc:
                raise OSError(
                    f"{target.name} is not a valid archive") from exc
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
