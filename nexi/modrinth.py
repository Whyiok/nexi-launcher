"""Modrinth search and dependency helpers."""

import json
import urllib.request

from .config import MODRINTH_API, USER_AGENT
from .net import network_event


def modrinth_get(path: str, params=None, timeout: float = 20):
    url = MODRINTH_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        network_event("error", f"api.modrinth.com: HTTP {exc.code} for {path}")
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        network_event("error", f"api.modrinth.com is unreachable ({reason})")
        raise RuntimeError(
            "Modrinth is unreachable from this network — check the "
            f"connection or a VPN ({reason})") from exc


def search_modrinth(query: str, game_version: str, loader: str,
                    project_type: str = "mod", offset: int = 0,
                    limit: int = 30):
    """(hits, total_hits) — Modrinth search is paginated by offset."""
    facets = [[f"project_type:{project_type}"]]
    if game_version:
        facets.append([f"versions:{game_version}"])
    if project_type in ("mod", "modpack") and loader and loader != "any":
        facets.append([f"categories:{loader}"])
    params = {
        "query": query,
        "limit": max(1, min(int(limit), 100)),
        "index": "relevance",
        "facets": json.dumps(facets),
    }
    if offset:
        params["offset"] = max(0, int(offset))
    data = modrinth_get("/search", params)
    return data.get("hits", []), int(data.get("total_hits") or 0)


def mod_versions(project_id: str, game_version: str, loader: str,
                 project_type: str = "mod"):
    params = {}
    if game_version and project_type != "modpack":
        params["game_versions"] = json.dumps([game_version])
    if project_type == "mod" and loader and loader != "any":
        params["loaders"] = json.dumps([loader])
    versions = modrinth_get(f"/project/{project_id}/version", params)
    versions.sort(
        key=lambda v: (v.get("version_type") == "release", v.get("date_published", "")),
        reverse=True,
    )
    return versions


def primary_file(version: dict):
    files = version.get("files") or []
    for file in files:
        if file.get("primary"):
            return file
    for file in files:
        if str(file.get("filename", "")).lower().endswith(".jar"):
            return file
    return files[0] if files else None


def required_dependencies(version: dict):
    return [dep for dep in version.get("dependencies") or []
            if dep.get("dependency_type") == "required"]


def resolve_dependency(dep: dict, game_version: str, loader: str):
    """Look up the version to install for a required dependency, if possible."""
    version_id = dep.get("version_id")
    if version_id:
        try:
            return modrinth_get(f"/version/{version_id}")
        except (OSError, ValueError, urllib.error.HTTPError):
            return None
    project_id = dep.get("project_id")
    if not project_id:
        return None
    try:
        versions = mod_versions(project_id, game_version, loader)
    except (OSError, ValueError, urllib.error.HTTPError):
        return None
    return versions[0] if versions else None
