"""Microsoft and Ely.by account flows."""

import re
import secrets
import threading
import time
import urllib.request
import uuid

from ..config import ELY_OAUTH_REDIRECT_DEFAULT
from ..ely_auth import (
    ELY_INVALIDATE_URL, ELY_OAUTH_AUTHORIZE_URL, ELY_OAUTH_CLIENT_ID_DEFAULT,
    ELY_OAUTH_SCOPE, ElyAuthError, _ElyCallbackServer, ely_account_info,
    ely_authenticate, ely_oauth_exchange, ely_oauth_refresh, ely_refresh,
    loopback_redirect_target, pkce_pair,
)
from ..logging_setup import log
from ..ms_auth import (
    MSRequestError, MS_CLIENT_ID_DEFAULT, MS_DEVICE_URL, MS_SCOPE,
    MS_TOKEN_URL, _http_json, minecraft_login, minecraft_profile,
    xbox_authenticate, xbox_xsts,
)
from ..util import open_in_system


class AccountsApi:
    def account_select(self, account_id):
        with self._lock:
            account = self._account_by_id(account_id)
            if account is None:
                return {"ok": False,
                        "error": "That account no longer exists.",
                        "state": self.state()}
            self._active_account_id = str(account_id)
            if account["type"] == "offline":
                self.player = account["name"]
            self._save()
        return {"ok": True, "state": self.state()}

    def account_add_offline(self, name=""):
        name = str(name or "").strip()[:16] or "Player"
        with self._lock:
            account = next(
                (item for item in self._accounts
                 if item["type"] == "offline"
                 and item["name"].lower() == name.lower()), None)
            if account is None:
                account = {"id": uuid.uuid4().hex, "type": "offline",
                           "name": name, "uuid": ""}
                self._accounts.append(account)
            self._active_account_id = account["id"]
            self.player = account["name"]
            self._save()
        log.info("Offline account added/selected: %s", name)
        return {"ok": True, "name": name, "state": self.state()}

    def account_reorder(self, order):
        """Persist a new account order, given the account ids from top to
        bottom."""
        if not isinstance(order, (list, tuple)):
            return {"ok": False, "error": "Invalid account order.",
                    "state": self.state()}
        ids = [str(item) for item in order]
        with self._lock:
            by_id = {account["id"]: account for account in self._accounts}
            if len(ids) != len(by_id) or set(ids) != set(by_id):
                return {"ok": False, "error": "The account list changed.",
                        "state": self.state()}
            if [account["id"] for account in self._accounts] == ids:
                return {"ok": True, "state": self.state()}
            self._accounts = [by_id[item] for item in ids]
            self._save()
        return {"ok": True, "state": self.state()}

    def account_remove(self, account_id):
        with self._lock:
            account = self._account_by_id(account_id)
            if account is None:
                return {"ok": False,
                        "error": "That account no longer exists.",
                        "state": self.state()}
            self._accounts = [item for item in self._accounts
                              if item["id"] != account["id"]]
            if self._active_account_id == account["id"]:
                self._active_account_id = self._accounts[0]["id"] \
                    if self._accounts else ""
                active = self._active_account()
                if active is not None and active["type"] == "offline":
                    self.player = active["name"]
            self._save()
        if account["type"] == "ely" and account.get("kind") != "oauth" \
                and account.get("access_token"):
            try:
                _http_json(ELY_INVALIDATE_URL, {
                    "accessToken": account["access_token"],
                    "clientToken": account.get("client_token", "")})
            except Exception as exc:
                log.warning("Ely.by token invalidation failed: %s", exc)
        log.info("Account removed: %s (%s)", account["name"], account["type"])
        self._event("refresh")
        return {"ok": True, "state": self.state()}

    def set_ms_client_id(self, value):
        value = str(value or "").strip()
        if value and not re.fullmatch(r"[0-9a-fA-F][0-9a-fA-F-]{15,60}", value):
            return {"ok": False,
                    "error": "That does not look like an Application (client) "
                             "ID — copy the value from Azure.",
                    "state": self.state()}
        self._ms_client_id = value
        self._save()
        return {"ok": True, "state": self.state()}

    def ms_login(self):
        client_id = self._ms_client_id or MS_CLIENT_ID_DEFAULT
        if not client_id:
            return {"ok": False,
                    "error": "Add your Azure Application (client) ID first."}
        if self._ms_device_thread is not None \
                and self._ms_device_thread.is_alive():
            return {"ok": False, "error": "Sign-in is already in progress."}
        self._ely_oauth_stop.set()
        try:
            data = _http_json(MS_DEVICE_URL,
                              {"client_id": client_id, "scope": MS_SCOPE},
                              form=True)
        except MSRequestError as exc:
            log.warning("MS device code request failed: %s", exc)
            message = str(exc)
            if "client" in message.lower() or \
                    (exc.payload or {}).get("error") in ("invalid_client",
                                                         "unauthorized_client"):
                message = ("Microsoft rejected this Client ID. Check that the "
                           "app is registered for personal Microsoft accounts "
                           "and that public client flows are enabled.")
            return {"ok": False, "error": message}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ok": False,
                    "error": f"Could not reach Microsoft: {exc}"}
        device_code = str(data.get("device_code", ""))
        user_code = str(data.get("user_code", ""))
        verification = str(data.get("verification_uri")
                           or "https://microsoft.com/link")
        try:
            interval = max(1, int(data.get("interval") or 5))
        except (TypeError, ValueError):
            interval = 5
        try:
            expires = int(data.get("expires_in") or 900)
        except (TypeError, ValueError):
            expires = 900
        if not device_code or not user_code:
            return {"ok": False,
                    "error": "Microsoft returned an incomplete sign-in code."}
        self._ms_device_stop = threading.Event()
        self._ms_device_thread = threading.Thread(
            target=self._ms_login_worker,
            args=(client_id, device_code, interval, expires),
            name="ms-login", daemon=True)
        self._ms_device_thread.start()
        log.info("Microsoft device code issued: %s", user_code)
        self._event("msauth", status="code", user_code=user_code,
                    verification_uri=verification, expires_in=expires)
        browser_url = verification
        if "microsoft.com/link" in browser_url:
            browser_url += ("&" if "?" in browser_url else "?") \
                + "otc=" + urllib.parse.quote(user_code)
        open_in_system(browser_url)
        return {"ok": True, "user_code": user_code,
                "verification_uri": verification, "expires_in": expires}

    def ms_cancel_login(self):
        self._ms_device_stop.set()
        return {"ok": True}

    def ms_logout(self):
        self._ms_device_stop.set()
        account = self._active_account()
        if account is None or account["type"] != "microsoft":
            account = next((item for item in self._accounts
                            if item["type"] == "microsoft"), None)
        if account is not None:
            self.account_remove(account["id"])
        self._event("msauth", status="signed_out")
        log.info("Microsoft account removed")
        return {"ok": True, "state": self.state()}

    def _ms_login_worker(self, client_id, device_code, interval, expires):
        deadline = time.monotonic() + expires
        while time.monotonic() < deadline:
            if self._ms_device_stop.wait(interval):
                self._event("msauth", status="cancelled")
                return
            try:
                token = _http_json(MS_TOKEN_URL, {
                    "client_id": client_id,
                    "grant_type":
                        "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                }, form=True)
            except MSRequestError as exc:
                error = (exc.payload or {}).get("error", "")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                if error == "authorization_declined":
                    self._event("msauth", status="error",
                                message="Sign-in was declined.")
                    return
                if error in ("expired_token", "bad_verification_code"):
                    self._event("msauth", status="error",
                                message="The sign-in code expired. "
                                        "Start again.")
                    return
                log.warning("MS token poll failed: %s", exc)
                self._event("msauth", status="error", message=str(exc))
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                log.warning("MS token poll network error: %s", exc)
                continue
            self._finish_ms_login(token)
            return
        self._event("msauth", status="error",
                    message="The sign-in code expired. Start again.")

    def _finish_ms_login(self, token):
        try:
            ms_access = str(token.get("access_token", ""))
            if not ms_access:
                raise RuntimeError("Microsoft returned no access token.")
            xbl, uhs = xbox_authenticate(ms_access)
            xsts, xuid = xbox_xsts(xbl)
            mc_token, expires = minecraft_login(xsts, uhs)
            profile = minecraft_profile(mc_token)
        except MSRequestError as exc:
            log.warning("MS sign-in failed: %s", exc)
            self._event("msauth", status="error", message=str(exc))
            return
        except Exception as exc:
            log.exception("MS sign-in failed")
            self._event("msauth", status="error", message=str(exc))
            return
        with self._lock:
            account = {
                "type": "microsoft",
                "name": str(profile.get("name", "") or "")[:16],
                "uuid": str(profile.get("id", "") or ""),
                "refresh_token": str(token.get("refresh_token", "") or ""),
                "xuid": xuid,
                "_access": mc_token,
                "_exp": time.time() + max(60, expires - 60),
            }
            existing = self._account_for_profile(
                "microsoft", account["uuid"])
            if existing is not None and not account["refresh_token"]:
                account["refresh_token"] = existing.get("refresh_token", "")
            stored = self._upsert_account(account)
            self._save()
        log.info("Microsoft sign-in complete: %s (%s)", stored["name"],
                 stored["uuid"])
        self._event("msauth", status="ok", name=stored["name"],
                    uuid=stored["uuid"])
        self._event("refresh")

    def _ms_refresh(self, account):
        """Return a fresh Minecraft access token, or "" if refresh failed."""
        with self._lock:
            cached = account.get("_access", "")
            if cached and time.time() < account.get("_exp", 0.0):
                return cached
            refresh_token = account.get("refresh_token", "")
            client_id = self._ms_client_id or MS_CLIENT_ID_DEFAULT
        if not refresh_token or not client_id:
            return ""
        try:
            data = _http_json(MS_TOKEN_URL, {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": MS_SCOPE,
            }, form=True)
            xbl, uhs = xbox_authenticate(str(data.get("access_token", "")))
            xsts, xuid = xbox_xsts(xbl)
            mc_token, expires = minecraft_login(xsts, uhs)
            profile = minecraft_profile(mc_token)
        except Exception as exc:
            log.warning("Microsoft token refresh failed: %s", exc)
            return ""
        with self._lock:
            account["_access"] = mc_token
            account["_exp"] = time.time() + max(60, expires - 60)
            if data.get("refresh_token"):
                account["refresh_token"] = str(data["refresh_token"])
            account["name"] = str(profile.get("name", "") or "")[:16]
            account["uuid"] = str(profile.get("id", "") or "")
            account["xuid"] = xuid
            self._save()
        return mc_token

    def ely_login(self, username, password, totp=""):
        """Sign in to Ely.by. The password is used once and never stored."""
        username = str(username or "").strip()
        password = str(password or "")
        totp = str(totp or "").strip()
        if not username or not password:
            return {"ok": False,
                    "error": "Enter your Ely.by e-mail/username and password."}
        self._ely_oauth_stop.set()
        self._ms_device_stop.set()
        with self._lock:
            client_token = str(uuid.uuid4())
        secret = password + (":" + totp if totp else "")
        try:
            data = ely_authenticate(username, secret, client_token)
        except ElyAuthError as exc:
            log.warning("Ely.by sign-in failed: %s", exc)
            if exc.two_factor:
                return {"ok": False, "two_factor": True,
                        "error": "This account uses two-factor "
                                 "authentication. Enter the current 6-digit "
                                 "code from your authenticator app."}
            message = str(exc)
            if "invalid credentials" in message.lower():
                message = ("Invalid Ely.by e-mail/username or password."
                           if not totp else
                           "Invalid password or two-factor code.")
            return {"ok": False, "error": message}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ok": False,
                    "error": f"Could not reach Ely.by: {exc}"}
        access = str(data.get("accessToken", ""))
        profile = data.get("selectedProfile") or {}
        name = str(profile.get("name", "") or "")
        profile_id = str(profile.get("id", "") or "")
        if not access or not profile_id or not name:
            return {"ok": False,
                    "error": "Ely.by returned an incomplete profile."}
        with self._lock:
            account = {
                "type": "ely",
                "name": name[:16],
                "uuid": profile_id,
                "access_token": access,
                "client_token": str(data.get("clientToken")
                                    or client_token),
                "refresh_token": "",
                "kind": "yggdrasil",
            }
            stored = self._upsert_account(account)
            self._save()
        log.info("Ely.by sign-in complete: %s (%s)", stored["name"],
                 stored["uuid"])
        self._event("refresh")
        return {"ok": True, "name": stored["name"], "state": self.state()}

    def ely_logout(self):
        self._ely_oauth_stop.set()
        account = self._active_account()
        if account is None or account["type"] != "ely":
            account = next((item for item in self._accounts
                            if item["type"] == "ely"), None)
        if account is not None:
            self.account_remove(account["id"])
        log.info("Ely.by account removed")
        return {"ok": True, "state": self.state()}

    def _ely_refresh(self, account):
        """Return a fresh Ely.by access token, or "" if it cannot be renewed."""
        with self._lock:
            kind = account.get("kind", "")
            token = account.get("access_token", "")
            client_token = account.get("client_token", "")
            refresh_token = account.get("refresh_token", "")
            client_id = self._ely_oauth_client_id \
                or ELY_OAUTH_CLIENT_ID_DEFAULT
            client_secret = self._ely_oauth_secret
        if not token:
            return ""
        if kind == "oauth":
            if not refresh_token or not client_id:
                return ""
            try:
                data = ely_oauth_refresh(refresh_token, client_id,
                                         client_secret)
            except Exception as exc:
                log.warning("Ely.by OAuth refresh failed: %s", exc)
                return ""
            new_token = str(data.get("access_token", ""))
            if not new_token:
                return ""
            with self._lock:
                account["access_token"] = new_token
                if data.get("refresh_token"):
                    account["refresh_token"] = str(data["refresh_token"])
                self._save()
            return new_token
        try:
            data = ely_refresh(token, client_token)
        except Exception as exc:
            log.warning("Ely.by token refresh failed: %s", exc)
            return ""
        new_token = str(data.get("accessToken", ""))
        if not new_token:
            return ""
        profile = data.get("selectedProfile") or {}
        with self._lock:
            account["access_token"] = new_token
            if profile.get("id") and profile.get("name"):
                account["name"] = str(profile["name"])[:16]
                account["uuid"] = str(profile["id"])
            self._save()
        return new_token

    def set_ely_oauth(self, client_id, client_secret="", redirect_uri=""):
        """Store the Ely.by OAuth2 application used for browser sign-in."""
        client_id = str(client_id or "").strip()
        client_secret = str(client_secret or "").strip()
        redirect_uri = str(redirect_uri or "").strip() \
            or ELY_OAUTH_REDIRECT_DEFAULT
        with self._lock:
            saved_id = self._ely_oauth_client_id
            saved_secret = self._ely_oauth_secret
        if client_id and not client_secret and client_id == saved_id:
            client_secret = saved_secret
        try:
            loopback_redirect_target(redirect_uri)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "state": self.state()}
        with self._lock:
            self._ely_oauth_client_id = client_id
            self._ely_oauth_secret = client_secret
            self._ely_oauth_redirect = redirect_uri
            self._save()
        log.info("Ely.by OAuth settings saved: client_id=%r redirect=%r "
                 "secret=%s", client_id, redirect_uri,
                 "set" if client_secret else "empty")
        return {"ok": True, "state": self.state()}

    def ely_browser_login(self):
        if self._ely_oauth_thread is not None \
                and self._ely_oauth_thread.is_alive():
            return {"ok": False,
                    "error": "Browser sign-in is already in progress."}
        self._ms_device_stop.set()
        with self._lock:
            client_id = self._ely_oauth_client_id \
                or ELY_OAUTH_CLIENT_ID_DEFAULT
            client_secret = self._ely_oauth_secret
            redirect_uri = self._ely_oauth_redirect \
                or ELY_OAUTH_REDIRECT_DEFAULT
        if not client_id:
            return {"ok": False, "setup": True,
                    "error": "Browser sign-in is not configured yet. Open "
                             "“Advanced: browser sign-in (OAuth) setup” and "
                             "add the Ely.by Client ID (the Client Secret is "
                             "only needed for “Website” apps)."}
        try:
            address, path = loopback_redirect_target(redirect_uri)
        except ValueError as exc:
            return {"ok": False, "setup": True, "error": str(exc)}
        self._ely_oauth_stop = threading.Event()
        self._ely_oauth_thread = threading.Thread(
            target=self._ely_oauth_worker,
            args=(client_id, client_secret, redirect_uri, address, path),
            name="ely-oauth", daemon=True)
        self._ely_oauth_thread.start()
        return {"ok": True}

    def ely_cancel_login(self):
        self._ely_oauth_stop.set()
        return {"ok": True}

    def _ely_oauth_worker(self, client_id, client_secret, redirect_uri,
                          address, path):
        state = secrets.token_urlsafe(24)
        verifier, challenge = pkce_pair()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ELY_OAUTH_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        query = urllib.parse.urlencode(params)
        try:
            server = _ElyCallbackServer(address, path)
        except OSError as exc:
            log.warning("Ely.by OAuth callback server failed: %s", exc)
            self._event("elyauth", status="error",
                        message=f"Could not listen on {address[0]}:"
                                f"{address[1]} for the browser redirect: "
                                f"{exc}")
            return
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self._event("elyauth", status="waiting")
            open_in_system(ELY_OAUTH_AUTHORIZE_URL + "?" + query)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self._ely_oauth_stop.is_set():
                    self._event("elyauth", status="cancelled")
                    return
                if server.event.wait(0.5):
                    break
            else:
                self._event("elyauth", status="error",
                            message="Browser sign-in timed out. Try again.")
                return
            params = server.result or {}
            if params.get("error"):
                message = (params.get("error_message")
                           or params.get("error") or ["Sign-in failed."])[0]
                self._event("elyauth", status="error",
                            message=urllib.parse.unquote_plus(str(message)))
                return
            code = (params.get("code") or [""])[0]
            returned = (params.get("state") or [""])[0]
            if returned != state:
                self._event("elyauth", status="error",
                            message="Sign-in state mismatch. Try again.")
                return
            if not code:
                self._event("elyauth", status="error",
                            message="Ely.by returned no authorization code.")
                return
            try:
                data = ely_oauth_exchange(code, client_id, client_secret,
                                          redirect_uri,
                                          "" if client_secret else verifier)
                access = str(data.get("access_token", ""))
                if not access:
                    raise RuntimeError("Ely.by returned no access token.")
                info = ely_account_info(access)
            except ElyAuthError as exc:
                log.warning("Ely.by browser sign-in failed: %s", exc)
                self._event("elyauth", status="error", message=str(exc))
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                self._event("elyauth", status="error",
                            message=f"Could not reach Ely.by: {exc}")
                return
            except Exception as exc:
                log.exception("Ely.by browser sign-in failed")
                self._event("elyauth", status="error", message=str(exc))
                return
            name = str(info.get("username", "") or "")
            profile_id = str(info.get("uuid", "") or "").replace("-", "")
            if not name or not profile_id:
                self._event("elyauth", status="error",
                            message="Ely.by returned an incomplete profile.")
                return
            with self._lock:
                account = {
                    "type": "ely",
                    "name": name[:16],
                    "uuid": profile_id,
                    "access_token": access,
                    "client_token": "",
                    "refresh_token": str(
                        data.get("refresh_token", "") or ""),
                    "kind": "oauth",
                }
                stored = self._upsert_account(account)
                self._save()
            log.info("Ely.by browser sign-in complete: %s (%s)",
                     stored["name"], stored["uuid"])
            self._event("elyauth", status="ok", name=stored["name"],
                        uuid=stored["uuid"])
            self._event("refresh")
        finally:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
