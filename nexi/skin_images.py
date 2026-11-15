"""Skin PNG handling and skin uploads to Mojang."""

import json
import urllib.request
import uuid
import zlib
from pathlib import Path

from .config import ELY_SKIN_TEXTURE_URL, USER_AGENT


def _skin_dimensions(data: bytes):
    """Width/height of a PNG file, or None when it is not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" \
            or data[12:16] != b"IHDR":
        return None
    return (int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"))


_DEFAULT_SKIN = None


def _default_skin_png() -> bytes:
    """A built-in 64×64 skin (mint hoodie, jeans) generated once, in memory."""
    global _DEFAULT_SKIN
    if _DEFAULT_SKIN is not None:
        return _DEFAULT_SKIN
    size = 64
    pixels = bytearray(size * size * 4)  # RGBA, transparent

    def fill(x, y, w, h, color):
        r, g, b = color
        for row in range(y, y + h):
            start = (row * size + x) * 4
            for col in range(start, start + w * 4, 4):
                pixels[col:col + 4] = bytes((r, g, b, 255))

    skin = (242, 201, 160)
    hair = (43, 43, 51)
    shirt = (110, 231, 183)
    shade = (88, 199, 158)
    pants = (47, 59, 82)
    shoes = (29, 36, 51)
    eye = (31, 41, 55)

    # Head: six faces; the hat overlay stays transparent.
    fill(8, 0, 8, 8, hair)
    fill(16, 0, 8, 8, skin)
    for hx in (0, 16):
        fill(hx, 8, 8, 8, skin)
        fill(hx, 8, 8, 2, hair)
    fill(24, 8, 8, 8, hair)
    fill(24, 14, 8, 2, skin)
    fill(8, 8, 8, 8, skin)
    fill(8, 8, 8, 2, hair)
    fill(8, 8, 1, 4, hair)
    fill(15, 8, 1, 4, hair)
    fill(9, 12, 2, 1, eye)
    fill(13, 12, 2, 1, eye)

    # Torso.
    fill(20, 16, 8, 4, shirt)
    fill(28, 16, 8, 4, shade)
    fill(16, 20, 4, 12, shirt)
    fill(28, 20, 4, 12, shirt)
    fill(32, 20, 8, 12, shirt)
    fill(20, 20, 8, 12, shirt)
    fill(20, 20, 8, 1, shade)
    fill(24, 21, 1, 11, shade)
    fill(20, 28, 8, 2, shade)

    # Arms: sleeve on top, bare hands below.
    for top, bottom, sides in (
            ((44, 16), (48, 16), ((40, 20), (44, 20), (48, 20), (52, 20))),
            ((36, 48), (40, 48), ((32, 52), (36, 52), (40, 52), (44, 52)))):
        fill(*top, 4, 4, shirt)
        fill(*bottom, 4, 4, skin)
        for sx, sy in sides:
            fill(sx, sy, 4, 4, shirt)
            fill(sx, sy + 4, 4, 8, skin)

    # Legs: jeans with dark shoes.
    for top, bottom, sides in (
            ((4, 16), (8, 16), ((0, 20), (4, 20), (8, 20), (12, 20))),
            ((20, 48), (24, 48), ((16, 52), (20, 52), (24, 52), (28, 52)))):
        fill(*top, 4, 4, pants)
        fill(*bottom, 4, 4, shoes)
        for sx, sy in sides:
            fill(sx, sy, 4, 12, pants)
            fill(sx, sy + 10, 4, 2, shoes)

    raw = b"".join(
        b"\x00" + bytes(pixels[row * size * 4:(row + 1) * size * 4])
        for row in range(size))

    def chunk(tag, payload):
        return (len(payload).to_bytes(4, "big") + tag + payload
                + zlib.crc32(tag + payload).to_bytes(4, "big"))

    ihdr = (size.to_bytes(4, "big") + size.to_bytes(4, "big")
            + bytes((8, 6, 0, 0, 0)))
    _DEFAULT_SKIN = (b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw, 9))
                     + chunk(b"IEND", b""))
    return _DEFAULT_SKIN


def _multipart_body(fields, files):
    """Build a multipart/form-data body; returns (boundary, bytes)."""
    boundary = "----NexiLauncher" + uuid.uuid4().hex
    chunks = []
    for name, value in fields:
        chunks.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
             f"{value}\r\n").encode("utf-8"))
    for name, filename, content in files:
        chunks.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{name}"; '
             f'filename="{filename}"\r\n'
             f"Content-Type: image/png\r\n\r\n").encode("utf-8"))
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(chunks)


def _upload_skin(url, token, fields, skin, method="POST"):
    """Send a PNG skin (bytes or a path) to an account service."""
    try:
        content = bytes(skin) if isinstance(skin, (bytes, bytearray)) \
            else Path(skin).read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Could not read the skin file: {exc}") from None
    boundary, body = _multipart_body(fields, [("file", "skin.png", content)])
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header(
        "Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            message = (parsed.get("errorMessage") or parsed.get("message")
                       or parsed.get("error_description")
                       or parsed.get("error") or raw)
        else:
            message = raw
        raise RuntimeError(str(message or f"HTTP {exc.code}")) from None


def _ely_skin_png(account):
    """Return (png_bytes, variant) of an Ely.by account's current skin.

    Ely.by serves skins through its public skins system; the texture endpoint
    returns the skin URL and model, so the launcher can show the real skin.
    ``(None, "")`` when the account has none or the network is unavailable.
    """
    name = str(account.get("name", "") or "").strip()
    if not name:
        return None, ""

    def fetch(url, limit):
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=6) as response:
            return response.read(limit)

    try:
        raw = fetch(ELY_SKIN_TEXTURE_URL.format(
            name=urllib.parse.quote(name, safe="")), 1_000_000)
        meta = json.loads(raw.decode("utf-8", "replace"))
        skin = meta.get("SKIN") if isinstance(meta, dict) else None
        if not isinstance(skin, dict):
            return None, ""
        url = str(skin.get("url") or "")
        metadata = skin.get("metadata")
        model = str(metadata.get("model") or "") \
            if isinstance(metadata, dict) else ""
        if not url.startswith(("http://", "https://")):
            return None, ""
        data = fetch(url, 4_000_000)
    except (OSError, ValueError):
        return None, ""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None, ""
    return data, ("slim" if model.lower() == "slim" else "classic")
