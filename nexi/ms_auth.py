"""Microsoft device-code OAuth and Minecraft services login."""

import json
import urllib.request

from .net import open_url


MS_SCOPE = "XboxLive.signin offline_access"


MS_CLIENT_ID_DEFAULT = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"


MS_DEVICE_URL = ("https://login.microsoftonline.com/consumers/"
                 "oauth2/v2.0/devicecode")


MS_TOKEN_URL = ("https://login.microsoftonline.com/consumers/"
                "oauth2/v2.0/token")


XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"


XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"


MC_LOGIN_URL = ("https://api.minecraftservices.com/"
                "authentication/login_with_xbox")


MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"


MC_SKIN_URL = ("https://api.minecraftservices.com/minecraft/profile/skins")


XSTS_ERRORS = {
    "2148916233": "This Microsoft account has no Xbox profile. Sign in "
                  "once at xbox.com, then try again.",
    "2148916235": "Xbox Live is not available in this account's country.",
    "2148916236": "This account needs adult verification.",
    "2148916237": "This account needs adult verification.",
    "2148916238": "This is a child account. Ask an adult in your Microsoft "
                  "family to allow it, then try again.",
}


class MSRequestError(Exception):
    """HTTP error returned by Microsoft / Xbox / Minecraft services."""

    def __init__(self, payload):
        self.payload = payload if isinstance(payload, dict) else {}
        detail = (self.payload.get("error_description")
                  or self.payload.get("error") or "Request failed")
        super().__init__(detail)


def _http_json(url, payload=None, token=None, timeout=60, form=False):
    if payload is None:
        data = None
    elif form:
        data = urllib.parse.urlencode(payload).encode("utf-8")
    else:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header(
            "Content-Type", "application/x-www-form-urlencoded" if form
            else "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with open_url(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        parsed.setdefault("error", f"HTTP {exc.code}")
        parsed.setdefault(
            "error_description",
            parsed.get("errorMessage") or raw or f"HTTP {exc.code}")
        parsed["http_status"] = exc.code
        raise MSRequestError(parsed) from None
    return json.loads(body) if body else {}


def xbox_authenticate(ms_access_token):
    """Exchange a Microsoft access token for an Xbox Live token + user hash."""
    data = _http_json(XBL_URL, {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": "d=" + ms_access_token,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    })
    token = data.get("Token", "")
    claims = (data.get("DisplayClaims") or {}).get("xui") or [{}]
    uhs = claims[0].get("uhs", "")
    if not token or not uhs:
        raise RuntimeError("Xbox Live did not return a token.")
    return token, uhs


def xbox_xsts(xbl_token):
    """Authorize the Xbox token for Minecraft, returning (token, xuid)."""
    try:
        data = _http_json(XSTS_URL, {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        })
    except MSRequestError as exc:
        code = str((exc.payload or {}).get("XErr", ""))
        raise RuntimeError(
            XSTS_ERRORS.get(code, "Xbox Live authorization failed "
                                  f"(error {code or 'unknown'}).")) from None
    token = data.get("Token", "")
    claims = (data.get("DisplayClaims") or {}).get("xui") or [{}]
    xuid = claims[0].get("xid", "")
    if not token:
        raise RuntimeError("Xbox Live authorization returned no token.")
    return token, xuid


def minecraft_login(xsts_token, uhs):
    """Exchange the XSTS token for a Minecraft access token."""
    data = _http_json(MC_LOGIN_URL, {
        "identityToken": f"XBL3.0 x={uhs};{xsts_token}"})
    token = data.get("access_token", "")
    if not token:
        raise RuntimeError("Minecraft did not return an access token.")
    return token, int(data.get("expires_in") or 86400)


def minecraft_profile(token):
    """Fetch the player's UUID and name. 404 means the account owns no game."""
    try:
        data = _http_json(MC_PROFILE_URL, token=token)
    except MSRequestError as exc:
        if (exc.payload or {}).get("http_status") == 404:
            raise RuntimeError(
                "This Microsoft account does not own Minecraft: Java Edition."
            ) from None
        raise
    profile_id = str(data.get("id", ""))
    name = str(data.get("name", ""))
    if not profile_id or not name:
        raise RuntimeError("Minecraft returned an empty profile.")
    return {"id": profile_id, "name": name}
