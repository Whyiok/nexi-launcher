"""CurseForge search, files and download links.

Search needs a personal API key (api.curseforge.com). Without a key the
launcher can still resolve one project by its page link, exact slug or numeric
ID through the keyless CFWidget mirror, so a specific mod or pack can be
installed. CFWidget only returns the selected file, never the dependency list.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import USER_AGENT
from .net import network_event, note_failed_host, open_url

CF_API = "https://api.curseforge.com/v1"
CF_WIDGET = "https://api.cfwidget.com"
CF_KEY_PAGE = "https://console.curseforge.com/?#/api-keys"
CF_GAME_ID = 432

CF_CLASS_IDS = {
    "mod": 6,
    "modpack": 4471,
    "resourcepack": 12,
    "shader": 6552,
}

CF_LOADER_IDS = {
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}

CF_KIND_LABELS = {
    "mod": "a mod",
    "modpack": "a modpack",
    "resourcepack": "a resource pack",
    "shader": "a shader pack",
}

CF_WIDGET_KINDS = {
    "mods": "mod",
    "modpacks": "modpack",
    "resource packs": "resourcepack",
    "texture packs": "resourcepack",
    "shaders": "shader",
    "shader packs": "shader",
}

CF_WIDGET_CATEGORIES = {
    "mod": "mc-mods",
    "resourcepack": "texture-packs",
    "shader": "shaders",
    "modpack": "modpacks",
}

CF_RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}

_cdn_host = "https://mediafilez.forgecdn.net/files/{major}/{minor}/{name}"


class CurseForgeError(RuntimeError):
    pass


_api_key = ""
_key_lock = threading.Lock()
_widget_cache = {}
_widget_lock = threading.Lock()


def set_api_key(value):
    global _api_key
    text = str(value or "").strip()
    with _key_lock:
        _api_key = text
    return _api_key


def has_api_key():
    with _key_lock:
        return bool(_api_key)


def _current_key():
    with _key_lock:
        return _api_key


def _read_json(url, headers=None, timeout=45):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                      **(headers or {})})
    with open_url(request, timeout=timeout) as response:
        body = response.read()
    if not body.strip():
        return None
    return json.loads(body.decode("utf-8"))


def _api_get(path, params=None, timeout=45):
    key = _current_key()
    if not key:
        raise CurseForgeError(
            "Add a CurseForge API key in Settings → Network, or paste a "
            "CurseForge project link in the search box.")
    url = CF_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        payload = _read_json(url, {"x-api-key": key}, timeout)
    except urllib.error.HTTPError as exc:
        note_failed_host("api.curseforge.com")
        network_event("error",
                      f"api.curseforge.com: HTTP {exc.code} for {path}")
        if exc.code in (401, 403):
            raise CurseForgeError(
                "CurseForge rejected the API key. Open Settings → Network "
                "and check it.") from exc
        if exc.code == 404:
            raise CurseForgeError("CurseForge project or file not found.") from exc
        if exc.code == 429:
            raise CurseForgeError(
                "CurseForge is limiting requests — wait a minute and try "
                "again.") from exc
        raise CurseForgeError(
            f"CurseForge returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError,
            ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        note_failed_host("api.curseforge.com")
        network_event("error",
                      f"api.curseforge.com is unreachable ({reason})")
        raise CurseForgeError(
            "CurseForge is unreachable from this network — check the "
            f"connection or a VPN ({reason})") from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise CurseForgeError("CurseForge returned an unexpected answer.")
    return payload


def _official_hit(item):
    authors = item.get("authors") or []
    author = ""
    if authors and isinstance(authors[0], dict):
        author = str(authors[0].get("name") or "")
    logo = item.get("logo") if isinstance(item.get("logo"), dict) else {}
    return {
        "project_id": str(item.get("id") or ""),
        "slug": str(item.get("slug") or ""),
        "title": str(item.get("name") or "CurseForge project"),
        "downloads": int(item.get("downloadCount") or 0),
        "author": author,
        "description": str(item.get("summary") or ""),
        "icon_url": str(logo.get("thumbnailUrl")
                        or logo.get("url") or ""),
        "source": "curseforge",
    }


def _official_version(item, project_id):
    project = str(item.get("modId") or project_id)
    name = str(item.get("fileName") or "")
    url = str(item.get("downloadUrl") or "")
    files = []
    if name and url:
        files.append({
            "url": url, "filename": name, "primary": True,
            "size": int(item.get("fileLength") or 0),
        })
    dependencies = []
    for dep in item.get("dependencies") or []:
        if not isinstance(dep, dict) or not dep.get("modId"):
            continue
        dependencies.append({
            "project_id": str(dep.get("modId")),
            "dependency_type": ("required"
                                if dep.get("relationType") == 3
                                else "optional"),
        })
    display = str(item.get("displayName") or name)
    return {
        "id": str(item.get("id") or ""),
        "project_id": project,
        "version_number": display,
        "name": display,
        "date_published": str(item.get("fileDate") or ""),
        "version_type": CF_RELEASE_TYPES.get(item.get("releaseType"),
                                             "release"),
        "files": files,
        "dependencies": dependencies,
        "source": "curseforge",
    }


def _sort_versions(versions):
    versions.sort(
        key=lambda version: (version.get("version_type") == "release",
                             version.get("date_published", "")),
        reverse=True,
    )
    return versions


def _widget_url(path, version="", loader=""):
    params = {}
    if version:
        params["version"] = version
    if loader and loader != "any":
        params["loader"] = loader
    url = f"{CF_WIDGET}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def _widget_fetch(path, version="", loader=""):
    key = (path, str(version or ""), str(loader or ""))
    with _widget_lock:
        cached = _widget_cache.get(key)
    if cached is not None:
        return cached
    url = _widget_url(path, version, loader)
    payload = None
    for attempt in range(3):
        try:
            payload = _read_json(url, timeout=75)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CurseForgeError(
                    "No CurseForge project matches that link or ID.") from exc
            if exc.code == 429:
                raise CurseForgeError(
                    "The keyless CurseForge lookup is rate-limited — wait a "
                    "minute, or add an API key in Settings → Network.") from exc
            note_failed_host("api.cfwidget.com")
            network_event("error",
                          f"api.cfwidget.com: HTTP {exc.code} for {path}")
            raise CurseForgeError(
                f"CurseForge lookup returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError,
                ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            note_failed_host("api.cfwidget.com")
            network_event("error",
                          f"api.cfwidget.com is unreachable ({reason})")
            raise CurseForgeError(
                "The keyless CurseForge lookup is unreachable — check the "
                f"connection or a VPN ({reason})") from exc
        if isinstance(payload, dict) and payload.get("id"):
            break
        if isinstance(payload, dict) and payload.get("error"):
            raise CurseForgeError(str(payload["error"]))
        payload = None
        if attempt < 2:
            time.sleep(3)
    if not isinstance(payload, dict) or not payload.get("id"):
        raise CurseForgeError(
            "The keyless CurseForge lookup did not answer — try again, or "
            "add an API key in Settings → Network.")
    with _widget_lock:
        _widget_cache[key] = payload
    return payload


def _widget_paths(query, kind):
    text = str(query or "").strip()
    if not text:
        return []
    if text.isdigit():
        return [text]
    if "curseforge.com" in text.lower():
        parts = urllib.parse.urlsplit(
            text if "://" in text else "https://" + text)
        segments = [part for part in parts.path.split("/") if part]
        if segments and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?",
                                     segments[0], re.IGNORECASE):
            segments = segments[1:]
        if "files" in segments:
            segments = segments[:segments.index("files")]
        path = "/".join(segments)
        if path:
            return [path]
        raise CurseForgeError("That CurseForge link has no project path.")
    slug = text.strip("/").lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug):
        ordered = [kind] + [other for other in CF_WIDGET_CATEGORIES
                            if other != kind]
        return [f"minecraft/{CF_WIDGET_CATEGORIES[other]}/{slug}"
                for other in ordered]
    if re.fullmatch(r"minecraft/[a-z0-9/_-]+", slug):
        return [slug]
    raise CurseForgeError(
        "Paste a CurseForge project link, its numeric ID, or its exact slug.")


def _widget_project(identifier, game_version="", loader="", kind="",
                    version_id=None):
    paths = _widget_paths(identifier, kind or "mod")
    version = str(version_id or "")
    if not version and game_version:
        version = str(game_version)
    filter_loader = loader if kind == "mod" else ""
    last_error = None
    for path in paths:
        try:
            project = _widget_fetch(path, version, filter_loader)
        except CurseForgeError as exc:
            last_error = exc
            if "No CurseForge project matches" in str(exc):
                continue
            raise
        detected = CF_WIDGET_KINDS.get(
            str(project.get("type") or "").strip().lower())
        if kind and detected and detected != kind:
            raise CurseForgeError(
                f"That CurseForge link is {CF_KIND_LABELS[detected]}, not "
                f"{CF_KIND_LABELS[kind]}. Open the matching tab.")
        return project
    if last_error is not None:
        raise last_error
    raise CurseForgeError(
        "No CurseForge project matches that link or ID.")


def _widget_matches(project, game_version, loader, kind):
    download = project.get("download") or {}
    versions = [str(item).strip().lower()
                for item in download.get("versions") or []]
    if game_version and str(game_version).strip().lower() not in versions:
        return False
    if kind == "mod" and loader and loader != "any":
        if str(loader).strip().lower() not in versions:
            return False
    return True


def _widget_version(download, project_id):
    file_id = download.get("id")
    name = str(download.get("name") or "").strip()
    if not file_id or not name:
        return None
    display = str(download.get("display") or name)
    return {
        "id": str(file_id),
        "project_id": str(project_id),
        "version_number": display,
        "name": display,
        "date_published": str(download.get("uploaded_at") or ""),
        "version_type": str(download.get("type") or "release").lower(),
        "files": [{
            "url": cdn_url(file_id, name), "filename": name,
            "primary": True,
            "size": int(download.get("filesize") or 0),
        }],
        "dependencies": [],
        "source": "curseforge",
    }


def _keyless_hit(project):
    downloads = project.get("downloads")
    if isinstance(downloads, dict):
        total = downloads.get("total") or 0
    else:
        total = downloads or 0
    urls = project.get("urls") if isinstance(project.get("urls"), dict) else {}
    page = str(urls.get("curseforge") or urls.get("project") or "")
    slug = ""
    if page:
        slug = page.rstrip("/").split("/")[-1]
    return {
        "project_id": str(project.get("id") or ""),
        "slug": slug,
        "title": str(project.get("title") or "CurseForge project"),
        "downloads": int(total or 0),
        "author": "",
        "description": str(project.get("summary") or ""),
        "icon_url": str(project.get("thumbnail") or ""),
        "source": "curseforge",
    }


def _project_reference(text):
    """True for a pasted project page, a numeric project ID or a site path."""
    value = str(text or "").strip()
    if not value:
        return False
    return ("curseforge.com" in value.lower() or value.isdigit()
            or value.lower().startswith("minecraft/"))


def search_curseforge(query, game_version, loader, kind, offset=0, limit=30):
    """(hits, total) — official search, or one keyless link/slug lookup."""
    kind = kind if kind in CF_CLASS_IDS else "mod"
    query = str(query or "").strip()
    # A pasted link or ID identifies one project, so resolve it directly even
    # when a key is available; it must not be sent as a search phrase.
    if _project_reference(query):
        project = _widget_project(query, game_version, loader, kind)
        return [_keyless_hit(project)], 1
    if not has_api_key():
        if not query:
            raise CurseForgeError(
                "CurseForge search needs an API key. Add one in Settings → "
                "Network, or paste a CurseForge project link in the search "
                "box.")
        project = _widget_project(query, game_version, loader, kind)
        return [_keyless_hit(project)], 1
    params = {
        "gameId": CF_GAME_ID,
        "classId": CF_CLASS_IDS[kind],
        "index": max(0, int(offset or 0)),
        "pageSize": max(1, min(int(limit or 30), 50)),
        "sortField": 2,
        "sortOrder": "desc",
    }
    if query:
        params["searchFilter"] = query
    if game_version:
        params["gameVersion"] = str(game_version)
    if kind == "mod" and loader in CF_LOADER_IDS:
        params["modLoaderType"] = CF_LOADER_IDS[loader]
    payload = _api_get("/mods/search", params)
    items = payload.get("data") or []
    hits = [_official_hit(item) for item in items
            if isinstance(item, dict) and item.get("id")]
    pagination = payload.get("pagination") or {}
    try:
        total = int(pagination.get("totalCount") or len(hits))
    except (TypeError, ValueError):
        total = len(hits)
    return hits, total


def curseforge_versions(project_id, game_version, loader, kind="mod"):
    """Versions with a downloadable file, newest release first."""
    kind = kind if kind in CF_CLASS_IDS else "mod"
    project = str(project_id or "")
    if not project:
        return []
    if not has_api_key():
        widget = _widget_project(project, game_version, loader, kind)
        if not _widget_matches(widget, game_version, loader, kind):
            return []
        version = _widget_version(widget.get("download") or {}, project)
        return [version] if version is not None else []
    params = {"index": 0, "pageSize": 50}
    if game_version:
        params["gameVersion"] = str(game_version)
    if kind == "mod" and loader in CF_LOADER_IDS:
        params["modLoaderType"] = CF_LOADER_IDS[loader]
    payload = _api_get(f"/mods/{project}/files", params)
    items = payload.get("data") or []
    versions = [_official_version(item, project) for item in items
                if isinstance(item, dict)]
    versions = [version for version in versions if version["files"]]
    if items and not versions:
        raise CurseForgeError(
            "CurseForge did not provide download links for these files. The "
            "author may have disabled third-party downloads.")
    return _sort_versions(versions)


def resolve_curseforge_dependency(dep, game_version, loader):
    project = str((dep or {}).get("project_id") or "")
    if not project:
        return None
    try:
        versions = curseforge_versions(project, game_version, loader, "mod")
    except (CurseForgeError, OSError, ValueError):
        return None
    return versions[0] if versions else None


def resolve_manifest_file(project_id, file_id):
    """Filename and download URL for a CurseForge modpack manifest entry."""
    project = str(project_id or "")
    file_id = str(file_id or "")
    if not project or not file_id:
        return None
    if has_api_key():
        payload = _api_get(f"/mods/{project}/files/{file_id}")
        item = payload.get("data") or {}
        url = str(item.get("downloadUrl") or "")
        name = str(item.get("fileName") or "")
        if not url or not name:
            raise CurseForgeError(
                f"CurseForge has no download link for file {file_id} "
                "(third-party downloads may be disabled by the author).")
        return {"url": url, "filename": name,
                "filesize": int(item.get("fileLength") or 0)}
    widget = _widget_project(project, kind="", version_id=file_id)
    download = widget.get("download") or {}
    if str(download.get("id") or "") != file_id:
        download = next(
            (item for item in widget.get("files") or []
             if str(item.get("id") or "") == file_id), {})
    name = str(download.get("name") or "")
    if not download.get("id") or not name:
        return None
    return {"url": cdn_url(download["id"], name), "filename": name,
            "filesize": int(download.get("filesize") or 0)}


def curseforge_icon(project_id):
    """Project icon URL, or "" when it cannot be read."""
    project = str(project_id or "")
    if not project:
        return ""
    try:
        if has_api_key():
            item = _api_get(f"/mods/{project}", timeout=30).get("data") or {}
            logo = item.get("logo") if isinstance(item.get("logo"),
                                                  dict) else {}
            return str(logo.get("thumbnailUrl") or logo.get("url") or "")
        widget = _widget_project(project, kind="")
        return str(widget.get("thumbnail") or "")
    except Exception:
        return ""


def cdn_url(file_id, filename):
    try:
        number = int(file_id)
    except (TypeError, ValueError):
        return ""
    name = urllib.parse.quote(str(filename or ""), safe="")
    return _cdn_host.format(major=number // 1000, minor=number % 1000,
                            name=name)
