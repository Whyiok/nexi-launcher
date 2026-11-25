"""Loopback file server used for screenshot previews and backgrounds.

The interface is served by pywebview's own HTTP server, and a page loaded
from ``http://`` cannot display ``file://`` images or videos. The launcher
therefore publishes the local files it wants to show on a tiny HTTP server
bound to 127.0.0.1. Only the files registered here are reachable: the URL
token is a hash of the file identity, so a repeated poll reuses the same URL
(and the browser cache) and an unknown token gets a 404.

Video backgrounds need byte ranges (the media element seeks and loops), so
the server answers ``Range`` requests and streams the file in chunks instead
of loading it into memory.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_ENTRIES = 1024

CHUNK = 256 * 1024

CONTENT_TYPES = {
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")

_registry: "OrderedDict[str, Path]" = OrderedDict()
_lock = threading.Lock()
_server = None
_base = ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NexiMedia/1.0"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        token = self.path.split("?", 1)[0].strip("/").split(".", 1)[0]
        path = None
        if token:
            with _lock:
                path = _registry.get(token)
                if path is not None:
                    _registry.move_to_end(token)
        if path is None:
            self.send_error(404)
            return
        try:
            size = path.stat().st_size
        except OSError:
            self.send_error(404)
            return
        start, end, partial = 0, size - 1, False
        header = self.headers.get("Range", "")
        match = _RANGE.match(header.strip()) if header else None
        if match and (match.group(1) or match.group(2)):
            partial = True
            if match.group(1):
                start = int(match.group(1))
                if match.group(2):
                    end = min(int(match.group(2)), size - 1)
            else:
                # "bytes=-N": the last N bytes.
                start = max(0, size - int(match.group(2)))
                end = size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = max(0, end - start + 1)
        ctype = (CONTENT_TYPES.get(path.suffix.lower())
                 or mimetypes.guess_type(path.name)[0]
                 or "application/octet-stream")
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range",
                             f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "max-age=86400, immutable")
        self.end_headers()
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except OSError:
            pass

    def log_message(self, *args):
        """Keep the server out of the launcher log."""


def _ensure_server() -> str:
    global _server, _base
    with _lock:
        if _server is None:
            server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever,
                             name="nexi-media", daemon=True).start()
            _server = server
            _base = f"http://127.0.0.1:{server.server_address[1]}"
        return _base


def url_for(path) -> str:
    """Publish *path* on the loopback server and return a URL for it."""
    path = Path(path)
    try:
        stat = path.stat()
        stamp = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        return ""
    token = hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:24]
    base = _ensure_server()
    with _lock:
        _registry[token] = path
        _registry.move_to_end(token)
        while len(_registry) > MAX_ENTRIES:
            _registry.popitem(last=False)
    return f"{base}/{token}{path.suffix.lower()}"
