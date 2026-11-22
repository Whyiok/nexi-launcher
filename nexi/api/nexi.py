"""Sign-in with a Nexi site account (Nexi ID) and profile sync."""

import http.server
import ipaddress
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import USER_AGENT
from ..logging_setup import log
from ..net import open_url
from ..util import open_in_system


NEXI_TIMEOUT = 20
NEXI_BROWSER_TIMEOUT = 180


class _NexiLoginServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address, callback_path):
        super().__init__(address, _NexiLoginHandler)
        self.callback_path = callback_path.rstrip("/") or "/"
        self.result = None
        self.event = threading.Event()


class _NexiLoginHandler(http.server.BaseHTTPRequestHandler):
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
                         "<title>Nexi</title>"
                         "<body style='font:16px Segoe UI,sans-serif;"
                         "background:#0a0a0a;color:#f4f4f4;display:grid;"
                         "place-items:center;height:100vh;margin:0'>"
                         "<p>Nexi sign-in complete — you can close this "
                         "tab and return to the launcher.</p>")

    def _reply(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.debug("Nexi browser sign-in callback: " + fmt, *args)


# A refused connection usually means Flask is still starting or the debug
# reloader is restarting. Retrying briefly turns that into a normal response.
NEXI_RETRY_DELAYS = (0.5, 1.5)


MC_TYPES = ("offline", "microsoft", "ely")


def _refused(exc) -> bool:
    reason = getattr(exc, "reason", exc)
    text = (str(reason) or str(exc)).lower()
    return ("10061" in text or "connection refused" in text
            or "actively refused" in text or "отверг" in text)


def _unreachable_message(exc) -> str:
    """Readable text for connection failures instead of a raw urlopen error."""
    reason = getattr(exc, "reason", exc)
    text = str(reason) or str(exc)
    if _refused(exc):
        return "The Nexi site is not running — start it and try again."
    low = text.lower()
    if ("10060" in text or "10051" in text or "timed out" in low
            or "timeout" in low):
        return ("The Nexi site did not respond — check its address in "
                "Settings → Accounts.")
    return f"Could not reach the Nexi site: {text}"


class NexiApi:
    """The site account is only used to sign in and to know the linked
    Minecraft identity; game credentials still come from the normal account
    list."""

    def _nexi_call(self, path, payload=None, token="", method=""):
        """Call the Nexi site; returns ``(ok, data)`` with parsed JSON."""
        base = str(getattr(self, "nexi_base_url", "") or "").strip().rstrip("/")
        if not base:
            return False, {"error": "Set the Nexi site address first."}
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        if not method:
            method = "POST" if payload is not None else "GET"
        request_obj = urllib.request.Request(
            base + path, data=body, headers=headers, method=method)
        for attempt in range(len(NEXI_RETRY_DELAYS) + 1):
            try:
                with open_url(
                        request_obj, timeout=NEXI_TIMEOUT) as response:
                    raw = response.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                try:
                    data = json.loads(raw or "{}")
                except ValueError:
                    data = {}
                message = str((data or {}).get("error") or "").strip()
                if not message:
                    message = f"The Nexi site returned HTTP {exc.code}."
                return False, {"error": message, "status": exc.code}
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if attempt < len(NEXI_RETRY_DELAYS) and _refused(exc):
                    time.sleep(NEXI_RETRY_DELAYS[attempt])
                    continue
                return False, {"error": _unreachable_message(exc)}
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return False, {
                "error": "The Nexi site returned an unexpected response."}
        if not isinstance(data, dict):
            return False, {
                "error": "The Nexi site returned an unexpected response."}
        if data.get("ok") is False:
            return False, {
                "error": str(data.get("error") or "Nexi sign-in failed.")}
        return True, data

    @staticmethod
    def _nexi_mc(mc):
        mc = mc if isinstance(mc, dict) else {}
        return {
            "type": str(mc.get("type") or "offline").strip().lower(),
            "label": str(mc.get("label") or ""),
            "name": str(mc.get("name") or "")[:16],
            "uuid": str(mc.get("uuid") or "").lower(),
            "custom": bool(mc.get("custom")),
            "head": str(mc.get("head") or ""),
            "linked_at": mc.get("linked_at") or None,
        }

    def _nexi_account(self, user, token):
        """Turn the site's public user JSON into a stored account entry."""
        user = user if isinstance(user, dict) else {}
        mc = self._nexi_mc(user.get("mc"))
        nick = (user.get("account_name") or user.get("nick")
                or user.get("username") or user.get("nexi_id") or "Player")
        return {
            "type": "nexi",
            "name": str(nick).strip()[:16] or "Player",
            "uuid": mc.get("uuid", ""),
            "token": str(token or ""),
            "site_id": str(user.get("id") or ""),
            "nexi_id": str(user.get("nexi_id") or ""),
            "account_name": str(user.get("account_name") or ""),
            "username": str(user.get("username") or ""),
            "email": str(user.get("email") or ""),
            "mc": mc,
        }

    def _nexi_token_account(self):
        """The Nexi account to talk to: active one, else the first one."""
        with self._lock:
            account = self._active_account()
            if account is None or account.get("type") != "nexi":
                account = next((item for item in self._accounts
                                if item.get("type") == "nexi"), None)
            token = str((account or {}).get("token") or "")
        if account is None:
            return None, "", "Sign in with your Nexi account first."
        if not token:
            return account, "", ("This Nexi account has no saved token — "
                                 "sign in again.")
        return account, token, ""

    def _nexi_apply_user(self, account, user):
        """Merge a fresh site profile into the stored account."""
        with self._lock:
            target = self._account_by_id(account.get("id"))
            if target is None:
                return None
            fresh = self._nexi_account(user, account.get("token", ""))
            target.update(fresh)
            self._save()
            return target

    def nexi_login(self, login, password):
        """Send the e-mail code for a Nexi ID, e-mail or @username."""
        login = str(login or "").strip()
        password = str(password or "")
        if not login or not password:
            return {"ok": False,
                    "error": "Enter your Nexi ID and password."}
        ok, data = self._nexi_call(
            "/api/nexi/login", {"login": login, "password": password})
        if not ok:
            return {"ok": False, "error": data.get("error")
                    or "Nexi sign-in failed."}
        email = str(data.get("email") or "")
        with self._lock:
            self._nexi_pending = {"login": login, "email": email}
        log.info("Nexi sign-in code requested for %s", email or "(no e-mail)")
        return {"ok": True, "email": email,
                "expires_in": data.get("expires_in") or 900}

    def nexi_verify(self, code, login=""):
        """Confirm the e-mail code and keep the returned account token."""
        code = str(code or "").strip()
        if not code:
            return {"ok": False,
                    "error": "Enter the 6-digit code from the e-mail."}
        with self._lock:
            pending = dict(self._nexi_pending or {})
        login = str(login or pending.get("login") or "").strip()
        if not login:
            return {"ok": False,
                    "error": "Request a new code first."}
        ok, data = self._nexi_call(
            "/api/nexi/verify", {"login": login, "code": code})
        if not ok:
            return {"ok": False, "error": data.get("error")
                    or "Could not confirm the code."}
        token = str(data.get("token") or "")
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if not token:
            return {"ok": False,
                    "error": "The Nexi site returned no account token."}
        account = self._nexi_account(user, token)
        with self._lock:
            stored = self._upsert_account(account)
            self._nexi_pending = None
            self._save()
        log.info("Nexi sign-in complete: %s (ID %s)", stored["name"],
                 stored.get("nexi_id") or "?")
        self._event("refresh")
        return {"ok": True, "name": stored["name"], "state": self.state()}

    def nexi_cancel_login(self):
        with self._lock:
            self._nexi_pending = None
        return {"ok": True}

    def nexi_logout(self):
        with self._lock:
            self._nexi_pending = None
            account = self._active_account()
            if account is None or account.get("type") != "nexi":
                account = next((item for item in self._accounts
                                if item.get("type") == "nexi"), None)
        if account is not None:
            self.account_remove(account["id"])
        log.info("Nexi account signed out")
        return {"ok": True, "state": self.state()}

    def nexi_profile(self, account_id=""):
        """Refresh the profile and the linked Minecraft identity from the site."""
        account_id = str(account_id or "")
        if account_id:
            with self._lock:
                account = self._account_by_id(account_id)
            if account is None or account.get("type") != "nexi":
                return {"ok": False, "error": "That Nexi account is gone.",
                        "state": self.state()}
            token = str(account.get("token") or "")
            if not token:
                return {"ok": False,
                        "error": "Sign in to Nexi again.",
                        "state": self.state()}
        else:
            account, token, error = self._nexi_token_account()
            if account is None:
                return {"ok": False, "error": error, "state": self.state()}
        ok, data = self._nexi_call("/api/nexi/me", token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not refresh the "
                                                  "Nexi profile.",
                    "state": self.state()}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        self._nexi_apply_user(account, user)
        log.info("Nexi profile refreshed: %s", account.get("name"))
        return {"ok": True, "state": self.state()}

    def nexi_browser_login(self):
        """Sign in on the Nexi site in the browser and return here."""
        thread = getattr(self, "_nexi_login_thread", None)
        if thread is not None and thread.is_alive():
            return {"ok": False,
                    "error": "Browser sign-in is already waiting."}
        base = str(getattr(self, "nexi_base_url", "") or "").strip().rstrip("/")
        if not base:
            return {"ok": False, "error": "Set the Nexi site address first."}
        try:
            server = _NexiLoginServer(("127.0.0.1", 0), "/nexi-login")
        except OSError as exc:
            log.warning("Nexi browser sign-in listener failed: %s", exc)
            return {"ok": False,
                    "error": f"Could not listen for the browser redirect: "
                             f"{exc}"}
        state = secrets.token_urlsafe(24)
        stop = threading.Event()
        self._nexi_login_stop = stop
        self._nexi_login_thread = threading.Thread(
            target=self._nexi_browser_login_worker,
            args=(server, base, state, stop),
            name="nexi-browser-login", daemon=True)
        self._nexi_login_thread.start()
        return {"ok": True}

    def nexi_browser_login_cancel(self):
        stop = getattr(self, "_nexi_login_stop", None)
        if stop is not None:
            stop.set()
        return {"ok": True}

    def _nexi_browser_login_worker(self, server, base, state, stop):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            callback = f"http://127.0.0.1:{port}/nexi-login"
            query = urllib.parse.urlencode(
                {"state": state, "redirect": callback})
            self._event("nexi_login", status="waiting")
            open_in_system(f"{base}/launcher/login?{query}")
            deadline = time.monotonic() + NEXI_BROWSER_TIMEOUT
            while time.monotonic() < deadline:
                if stop.is_set():
                    self._event("nexi_login", status="cancelled")
                    return
                if server.event.wait(0.5):
                    break
            else:
                self._event("nexi_login", status="error",
                            message="Browser sign-in timed out. Try again.")
                return

            params = server.result or {}
            returned = str((params.get("state") or [""])[0])
            token = str((params.get("token") or [""])[0])
            if returned != state:
                self._event("nexi_login", status="error",
                            message="Sign-in state mismatch. Try again.")
                return
            if not token:
                self._event("nexi_login", status="error",
                            message="The Nexi site returned no sign-in token.")
                return

            ok, data = self._nexi_call(
                "/api/nexi/launcher-login/"
                + urllib.parse.quote(token, safe=""),
                {"state": state})
            if not ok:
                self._event("nexi_login", status="error",
                            message=data.get("error")
                            or "Browser sign-in failed.")
                return
            api_token = str(data.get("token") or "")
            user = data.get("user") if isinstance(data.get("user"), dict) else {}
            if not api_token:
                self._event("nexi_login", status="error",
                            message="The Nexi site returned no account token.")
                return
            account = self._nexi_account(user, api_token)
            with self._lock:
                stored = self._upsert_account(account)
                self._save()
            log.info("Nexi browser sign-in complete: %s (ID %s)",
                     stored["name"], stored.get("nexi_id") or "?")
            self._event("nexi_login", status="ok", name=stored["name"],
                        state=self.state())
        finally:
            try:
                server.shutdown()
            except Exception:
                log.exception("Nexi browser sign-in listener shutdown failed")
            server.server_close()

    def nexi_friends(self):
        """Friends and pending requests from the Nexi site."""
        account, token, error = self._nexi_token_account()
        if account is None:
            return {"ok": True, "signed_in": False}
        if not token:
            return {"ok": False, "signed_in": True, "error": error}
        ok, data = self._nexi_call("/api/nexi/friends", token=token)
        if not ok:
            return {"ok": False, "signed_in": True,
                    "error": data.get("error") or "Could not load friends."}
        return self._nexi_friends_result(data)

    def nexi_friend_accept(self, friend_id=""):
        return self._nexi_friend_action("accept", friend_id)

    def nexi_friend_decline(self, friend_id=""):
        return self._nexi_friend_action("decline", friend_id)

    def _nexi_friend_action(self, action, friend_id):
        try:
            friend_id = int(str(friend_id).strip())
        except (TypeError, ValueError):
            return {"ok": False, "error": "That friend request is invalid."}
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False, "signed_in": account is not None,
                    "error": error}
        ok, data = self._nexi_call(
            f"/api/nexi/friends/{action}", {"id": friend_id}, token=token)
        if not ok:
            return {"ok": False, "signed_in": True,
                    "error": data.get("error")
                    or "Could not update the friend request."}
        log.info("Nexi friend request %s: %s", action, friend_id)
        return self._nexi_friends_result(data)

    @staticmethod
    def _nexi_friends_result(data):
        data = data if isinstance(data, dict) else {}
        counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
        result = {
            "ok": True,
            "signed_in": True,
            "friends": data.get("friends")
            if isinstance(data.get("friends"), list) else [],
            "incoming": data.get("incoming")
            if isinstance(data.get("incoming"), list) else [],
            "outgoing": data.get("outgoing")
            if isinstance(data.get("outgoing"), list) else [],
            "counts": {
                "friends": int(counts.get("friends") or 0),
                "online": int(counts.get("online") or 0),
                "incoming": int(counts.get("incoming") or 0),
            },
        }
        return result

    def site_profile_url(self):
        """The player's profile page on the Nexi site, for the in-app view."""
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False,
                    "error": error or "Sign in with your Nexi account first."}
        site_id = str(account.get("site_id") or "").strip()
        if not site_id:
            ok, data = self._nexi_call("/api/nexi/me", token=token)
            if not ok:
                return {"ok": False,
                        "error": data.get("error") or "Could not read the "
                                                      "Nexi profile."}
            user = data.get("user") if isinstance(data.get("user"), dict) else {}
            site_id = str(user.get("id") or "").strip()
            self._nexi_apply_user(account, user)
        base = str(getattr(self, "nexi_base_url", "") or "").strip().rstrip("/")
        if not site_id or not base:
            return {"ok": False,
                    "error": "Could not find this profile on the Nexi site."}
        ok, data = self._nexi_call("/api/nexi/embed-token", payload={},
                                   token=token)
        embed = str(data.get("token") or "") if ok else ""
        url = (f"{base}/user/{urllib.parse.quote(site_id, safe='')}"
               f"?embed=1")
        if embed:
            url += "&nexi_embed=" + urllib.parse.quote(embed, safe="")
        try:
            request_obj = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT})
            with open_url(request_obj, timeout=4) as response:
                response.read(1)
        except Exception:
            return {"ok": False, "error": "The Nexi site is not running."}
        return {"ok": True, "url": url}

    def nexi_send_presence(self, online=True):
        """Tell the site whether the player is currently in the game."""
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False, "error": error}
        ok, data = self._nexi_call(
            "/api/nexi/presence", {"online": bool(online)}, token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not update presence."}
        return {"ok": True, "online": bool(data.get("online"))}

    def nexi_send_playtime(self, minutes):
        """Send a chunk of played minutes to the Nexi profile on the site."""
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid play time."}
        if minutes <= 0:
            return {"ok": True, "skipped": True}
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False, "error": error}
        ok, data = self._nexi_call(
            "/api/nexi/activity", {"minutes": minutes}, token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not sync play time."}
        log.info("Play time synced: +%d min (total %s min)",
                 minutes, data.get("minutes"))
        return {"ok": True, "minutes": data.get("minutes"),
                "hours": data.get("hours")}

    def nexi_link_minecraft(self, mc_type="offline", name=""):
        """Link a Minecraft nickname to the Nexi profile on the site."""
        mc_type = str(mc_type or "offline").strip().lower()
        name = str(name or "").strip()
        if mc_type not in MC_TYPES:
            return {"ok": False, "error": "Unknown Minecraft account type."}
        if not name:
            return {"ok": False, "error": "Type the Minecraft nickname."}
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False, "error": error, "state": self.state()}
        ok, data = self._nexi_call(
            "/api/nexi/minecraft", {"type": mc_type, "name": name},
            token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not link the "
                                                  "Minecraft account.",
                    "state": self.state()}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        stored = self._nexi_apply_user(account, user)
        mc = (stored or {}).get("mc") or {}
        log.info("Nexi Minecraft linked: %s (%s)", mc.get("name"),
                 mc.get("type"))
        self._event("refresh")
        return {"ok": True, "message": f"Linked {mc.get('name') or name}.",
                "state": self.state()}

    def nexi_unlink_minecraft(self):
        """Restore the default offline nickname on the Nexi profile."""
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False, "error": error, "state": self.state()}
        ok, data = self._nexi_call(
            "/api/nexi/minecraft", token=token, method="DELETE")
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not unlink the "
                                                  "Minecraft account.",
                    "state": self.state()}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        self._nexi_apply_user(account, user)
        log.info("Nexi Minecraft unlinked")
        self._event("refresh")
        return {"ok": True,
                "message": "Minecraft link reset to the offline nickname.",
                "state": self.state()}

    # ---------------------------------------------------- linking via the site
    # The site creates a one-time link token and opens nexi://link?token=...
    # in the browser. The launcher shows a dialog with the accounts that are
    # signed in here, and sends the chosen one back to the site.

    @staticmethod
    def _nexi_link_token_from_uri(uri):
        """Pull the token out of a ``nexi://link?token=...`` URL."""
        try:
            parsed = urllib.parse.urlparse(str(uri or "").strip())
        except ValueError:
            return ""
        if parsed.scheme.lower() not in ("nexi", "nexilauncher"):
            return ""
        if (parsed.netloc or "").strip().lower() != "link":
            return ""
        values = urllib.parse.parse_qs(parsed.query or "")
        return str((values.get("token") or [""])[0]).strip()

    @staticmethod
    def _nexi_link_base_from_uri(uri):
        """The LAN site address carried by ``nexi://link?base=...``, or ""."""
        try:
            parsed = urllib.parse.urlparse(str(uri or "").strip())
            values = urllib.parse.parse_qs(parsed.query or "")
            base = str((values.get("base") or [""])[0]).strip().rstrip("/")
            address = urllib.parse.urlparse(base)
        except ValueError:
            return ""
        if (address.scheme not in ("http", "https") or not address.netloc
                or address.username or address.password or address.path
                or address.query or address.fragment):
            return ""
        try:
            host = ipaddress.ip_address(address.hostname or "")
        except ValueError:
            return ""
        if not (host.is_private or host.is_loopback):
            return ""
        return base

    def _nexi_adopt_link_base(self, uri):
        """Use the sender's LAN address when this launcher has no site set."""
        base = self._nexi_link_base_from_uri(uri)
        if not base:
            return
        current = str(getattr(self, "nexi_base_url", "") or "").strip()
        if current.startswith(("http://", "https://")):
            current_host = urllib.parse.urlparse(current).hostname or ""
            if current_host not in ("127.0.0.1", "localhost", "::1"):
                return
        with self._lock:
            if self.nexi_base_url != base:
                self.nexi_base_url = base
                self._save()
                log.info("Nexi site address taken from the link: %s", base)

    def _nexi_link_accounts(self):
        """Only accounts that were actually signed in can be linked."""
        with self._lock:
            return [self._account_public(account)
                    for account in self._accounts
                    if account.get("type") in ("microsoft", "ely")
                    and account.get("uuid")
                    and (account.get("refresh_token")
                         or account.get("access_token"))]

    def nexi_handle_link(self, uri):
        """A ``nexi://link`` URL arrived (startup or a second instance)."""
        self._nexi_adopt_link_base(uri)
        token = self._nexi_link_token_from_uri(uri)
        if not token:
            log.warning("Nexi link ignored: no token in %r", str(uri)[:120])
            return {"ok": False, "error": "The link from the site is broken."}
        ok, data = self._nexi_call(
            "/api/nexi/link/" + urllib.parse.quote(token, safe=""))
        if not ok:
            message = data.get("error") or ("The link has expired — start "
                                            "again on the site.")
            self._event("nexi_link", ok=False, error=message)
            return {"ok": False, "error": message}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        display = str(user.get("display_name") or user.get("account_name")
                      or user.get("nexi_id") or "Nexi ID")
        accounts = self._nexi_link_accounts()
        log.info("Nexi link request for %s (%d signed-in account(s))",
                 display, len(accounts))
        self._event("nexi_link", ok=True, token=token, display_name=display,
                    nexi_id=str(user.get("nexi_id") or ""),
                    handle=str(user.get("handle") or ""), accounts=accounts)
        return {"ok": True}

    def nexi_link_start(self):
        """Start the same link flow from the launcher's own Nexi account."""
        account, token, error = self._nexi_token_account()
        if account is None or not token:
            return {"ok": False, "error": error, "state": self.state()}
        ok, data = self._nexi_call("/api/nexi/link/start", {}, token=token)
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not start linking.",
                    "state": self.state()}
        link_token = str(data.get("token") or "")
        if not link_token:
            return {"ok": False,
                    "error": "The Nexi site did not return a link.",
                    "state": self.state()}
        handle_name = (account.get("username") or account.get("nexi_id") or "")
        self._event(
            "nexi_link", ok=True, token=link_token,
            display_name=str(account.get("name") or "Nexi ID"),
            nexi_id=str(account.get("nexi_id") or ""),
            handle=f"@{handle_name}" if handle_name else "",
            accounts=self._nexi_link_accounts())
        return {"ok": True, "state": self.state()}

    def nexi_link_account(self, token, account_id=""):
        """Send the chosen signed-in account to the site and consume the link."""
        token = str(token or "").strip()
        if not token:
            return {"ok": False, "error": "The link has expired — start again "
                                          "on the site."}
        with self._lock:
            account = self._account_by_id(account_id)
            chosen = None
            if (account is not None
                    and account.get("type") in ("microsoft", "ely")
                    and account.get("uuid")
                    and (account.get("refresh_token")
                         or account.get("access_token"))):
                chosen = {
                    "type": account["type"],
                    "name": str(account.get("name") or "").strip()[:16],
                    "uuid": str(account.get("uuid") or "").lower(),
                }
        if chosen is None:
            return {"ok": False, "error": "Choose a Microsoft or Ely.by "
                                          "account that is signed in."}
        ok, data = self._nexi_call(
            "/api/nexi/link/" + urllib.parse.quote(token, safe=""),
            {"type": chosen["type"], "name": chosen["name"],
             "uuid": chosen["uuid"]})
        if not ok:
            return {"ok": False,
                    "error": data.get("error") or "Could not link the "
                                                  "Minecraft account.",
                    "state": self.state()}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        nexi_id = str(user.get("nexi_id") or "")
        # Refresh the launcher's own Nexi account when it is the same user.
        with self._lock:
            local = next((item for item in self._accounts
                          if item.get("type") == "nexi"
                          and item.get("nexi_id") == nexi_id), None)
        if local is not None:
            self._nexi_apply_user(local, user)
        mc = self._nexi_mc(user.get("mc"))
        log.info("Nexi Minecraft linked via the site: %s (%s)",
                 mc.get("name"), mc.get("type"))
        self._event("refresh")
        return {"ok": True,
                "message": f"Linked {mc.get('name') or chosen['name']}.",
                "state": self.state()}

    def set_nexi_base_url(self, value):
        """Save the site address used for Nexi sign-in."""
        value = str(value or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {"ok": False,
                    "error": "Enter a full http(s) address, for example "
                             "http://127.0.0.1:5000.",
                    "state": self.state()}
        with self._lock:
            self.nexi_base_url = value
            self._save()
        log.info("Nexi site address: %s", value)
        return {"ok": True, "state": self.state()}
