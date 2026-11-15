"""Ely.by Yggdrasil, OAuth2 PKCE and authlib-injector."""

import base64
import hashlib
import http.server
import os
import secrets
import shutil
import threading
import urllib.request
from pathlib import Path

from .config import APP_NAME, DATA_DIR
from .logging_setup import log
from .ms_auth import MSRequestError, _http_json


ELY_AUTH_URL = "https://authserver.ely.by/auth/authenticate"


ELY_REFRESH_URL = "https://authserver.ely.by/auth/refresh"


ELY_INVALIDATE_URL = "https://authserver.ely.by/auth/invalidate"


ELY_OAUTH_AUTHORIZE_URL = "https://account.ely.by/oauth2/v1"


ELY_OAUTH_TOKEN_URL = "https://account.ely.by/api/oauth2/v1/token"


ELY_ACCOUNT_INFO_URL = "https://account.ely.by/api/account/v1/info"


ELY_OAUTH_SCOPE = "account_info offline_access minecraft_server_session"


ELY_OAUTH_CLIENT_ID_DEFAULT = "why-launcher"


AUTHLIB_VERSION = "1.2.8"


AUTHLIB_URL = ("https://github.com/yushijinhun/authlib-injector/releases/"
               f"download/v{AUTHLIB_VERSION}/authlib-injector-"
               f"{AUTHLIB_VERSION}.jar")


class ElyAuthError(Exception):
    """Yggdrasil error returned by authserver.ely.by."""

    def __init__(self, payload):
        self.payload = payload if isinstance(payload, dict) else {}
        detail = (self.payload.get("errorMessage")
                  or self.payload.get("error_description")
                  or self.payload.get("error") or "Request failed")
        super().__init__(detail)
        self.two_factor = "two factor" in detail.lower()


def ely_authenticate(username, password, client_token):
    """Sign in with an Ely.by e-mail/username and password (or ``password:otp``)."""
    try:
        return _http_json(ELY_AUTH_URL, {
            "username": username,
            "password": password,
            "clientToken": client_token,
            "requestUser": True,
        })
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def ely_refresh(access_token, client_token):
    """Exchange a stored Ely.by access token for a fresh one."""
    try:
        return _http_json(ELY_REFRESH_URL, {
            "accessToken": access_token,
            "clientToken": client_token,
            "requestUser": True,
        })
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def pkce_pair():
    """Return (verifier, S256 challenge) for the OAuth2 PKCE flow."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def ely_oauth_exchange(code, client_id, client_secret, redirect_uri,
                       code_verifier=""):
    """Trade an OAuth2 authorization code for tokens."""
    payload = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code": code,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    if code_verifier:
        payload["code_verifier"] = code_verifier
    try:
        return _http_json(ELY_OAUTH_TOKEN_URL, payload, form=True)
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def ely_oauth_refresh(refresh_token, client_id, client_secret):
    """Get a new OAuth2 access token from the non-expiring refresh token."""
    payload = {
        "client_id": client_id,
        "scope": ELY_OAUTH_SCOPE,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        payload["client_secret"] = client_secret
    try:
        return _http_json(ELY_OAUTH_TOKEN_URL, payload, form=True)
    except MSRequestError as exc:
        raise ElyAuthError(exc.payload) from None


def ely_account_info(access_token):
    return _http_json(ELY_ACCOUNT_INFO_URL, token=access_token)


def loopback_redirect_target(redirect_uri):
    """Return ((host, port), path) for a localhost callback URI."""
    parsed = urllib.parse.urlparse(str(redirect_uri or "").strip())
    if parsed.scheme != "http":
        raise ValueError("Redirect URI must start with http:// (local TLS is "
                         "not supported).")
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Redirect URI must point to localhost.")
    try:
        port = parsed.port or 80
    except ValueError:
        raise ValueError("Redirect URI has an invalid port.") from None
    return ("127.0.0.1", port), (parsed.path or "/")


class _ElyCallbackServer(http.server.HTTPServer):
    allow_reuse_address = True

    def __init__(self, address, callback_path):
        super().__init__(address, _ElyCallbackHandler)
        self.callback_path = callback_path.rstrip("/") or "/"
        self.result = None
        self.event = threading.Event()


class _ElyCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != self.server.callback_path:
            self._reply(404, "<!doctype html><meta charset='utf-8'>"
                             "<h1>Not found</h1>")
            return
        self.server.result = urllib.parse.parse_qs(parsed.query)
        self.server.event.set()
        self._reply(200, "<!doctype html><meta charset='utf-8'>"
                         "<title>Ely.by</title>"
                         "<body style='font:16px Segoe UI,sans-serif;"
                         "background:#0a0a0a;color:#f4f4f4;display:grid;"
                         "place-items:center;height:100vh;margin:0'>"
                         "<p>Ely.by sign-in complete — you can close this "
                         "tab and return to the launcher.</p>")

    def _reply(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.debug("Ely.by callback: " + fmt, *args)


def ensure_authlib_injector() -> Path:
    """Download authlib-injector once; it authenticates and loads skins in game."""
    target = DATA_DIR / f"authlib-injector-{AUTHLIB_VERSION}.jar"
    if target.is_file() and target.stat().st_size > 200_000:
        return target
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.info("downloading authlib-injector %s", AUTHLIB_VERSION)
    request = urllib.request.Request(
        AUTHLIB_URL, headers={"User-Agent": f"{APP_NAME}/1"})
    temp = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, \
                open(temp, "wb") as handle:
            shutil.copyfileobj(response, handle)
        if temp.stat().st_size < 200_000:
            raise RuntimeError("the downloaded file is too small")
        os.replace(temp, target)
    except Exception as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("Could not download authlib-injector, which is "
                           f"required for Ely.by: {exc}") from None
    log.info("authlib-injector saved to %s", target)
    return target
