"""Game process lifecycle."""

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from ..crash import diagnose_crash
from ..ely_auth import ensure_authlib_injector
from ..game_options import write_game_options
from ..instances import (instance_game_dir, instance_label, instance_mods_dir,
                         write_instance)
from ..java_runtime import ensure_java
from ..loaders import (console_java, neoforge_runtime_missing,
                       repair_neoforge_runtime)
from ..logging_setup import log
from ..vanilla import fetch_missing_libraries
from ..versions import (build_command, game_version_of, load_version,
                        version_meta)


def quick_play_supported(version_id: str) -> bool:
    """Quick Play arguments ship with Minecraft 1.20 and newer releases."""
    match = re.match(r"^(\d+)\.(\d+)", str(version_id or ""))
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (1, 20)


# Play time is reported to the Nexi site during the session, so a crash or a
# force-close loses at most the last few minutes.
PLAYTIME_SYNC_MINUTES = 5
PLAYTIME_POLL_SECONDS = 2
PRESENCE_HEARTBEAT_SECONDS = 60


def world_for_quick_play(game_dir, world: str) -> str:
    """A safe saves/ folder name, or "" when it is gone or not a plain name."""
    name = str(world or "")
    if not name or name in (".", "..") or Path(name).name != name:
        return ""
    return name if (Path(game_dir) / "saves" / name).is_dir() else ""


class LaunchApi:
    def _game_line(self, line):
        if self._log_queue.qsize() < 5000:
            self._log_queue.put(line)

    def _running_slugs(self):
        """Slugs whose game process is still alive."""
        with self._game_lock:
            items = list(self._game_processes.items())
            slugs = []
            for slug, process in items:
                try:
                    alive = process is not None and process.poll() is None
                except (OSError, ValueError):
                    alive = False
                if alive:
                    slugs.append(slug)
                elif self._game_processes.get(slug) is process:
                    self._game_processes.pop(slug, None)
        return slugs

    def _instance_running(self, slug):
        return str(slug or "") in self._running_slugs()

    def _game_running(self):
        return bool(self._running_slugs())

    def _store_playtime(self, slug, seconds):
        """Add played seconds to the profile so its page can count them."""
        seconds = int(seconds)
        if seconds <= 0:
            return
        stored = False
        with self._lock:
            for instance in self.instances:
                if instance.get("_slug") != slug:
                    continue
                try:
                    total = int(instance.get("playtime") or 0)
                except (TypeError, ValueError):
                    total = 0
                instance["playtime"] = max(0, total) + seconds
                write_instance(instance["_root"], instance)
                stored = True
                break
        if stored:
            self._event("refresh")

    def _track_playtime(self, process, slug):
        """While the game runs, send played minutes and presence to the site."""
        started = time.monotonic()
        sent = 0
        stored = 0
        last_presence = started
        presence_warned = not self._sync_presence(True, slug)
        while process.poll() is None:
            time.sleep(PLAYTIME_POLL_SECONDS)
            now = time.monotonic()
            if now - last_presence >= PRESENCE_HEARTBEAT_SECONDS:
                last_presence = now
                if not self._sync_presence(True, slug, quiet=presence_warned):
                    presence_warned = True
            elapsed = int(now - started)
            # The page counter updates once a minute instead of on every poll.
            if elapsed - stored >= 60:
                self._store_playtime(slug, elapsed - stored)
                stored = elapsed
            played = elapsed // 60
            if played - sent >= PLAYTIME_SYNC_MINUTES:
                self._sync_playtime(played - sent, slug)
                sent = played
        elapsed = int(time.monotonic() - started)
        if elapsed > stored:
            self._store_playtime(slug, elapsed - stored)
        played = elapsed // 60
        if played > sent:
            self._sync_playtime(played - sent, slug)
        self._sync_presence(False, slug, quiet=True)

    def _sync_presence(self, online, slug, quiet=False):
        try:
            result = self.nexi_send_presence(online)
        except Exception as exc:
            if not quiet:
                log.warning("Presence update failed: %s", exc)
            return False
        if not result.get("ok"):
            if not quiet:
                log.info("Presence not updated for %r: %s", slug,
                         result.get("error"))
            return False
        return True

    def _sync_playtime(self, minutes, slug):
        if minutes <= 0:
            return
        try:
            result = self.nexi_send_playtime(minutes)
        except Exception as exc:
            log.warning("Play time sync failed: %s", exc)
            return
        if not result.get("ok"):
            log.info("Play time not synced for %r: %s", slug,
                     result.get("error"))

    def _kill_game(self, process):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            else:
                process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _instance_for(self, slug):
        with self._lock:
            if not slug:
                return self.active_instance()
            return next((item for item in self.instances
                         if item.get("_slug") == slug), None)

    def _explain_crash(self, slug, exit_code, stderr_text=""):
        """Read the game's log and turn the crash into a readable card."""
        instance = self._instance_for(str(slug or ""))
        if instance is None:
            return {}
        game_dir = instance_game_dir(instance["_root"])
        mods_dir = instance_mods_dir(instance["_root"])
        try:
            mods_present = any(mods_dir.glob("*.jar"))
        except OSError:
            mods_present = False
        try:
            ram = int(instance.get("ram") or self.ram)
        except (TypeError, ValueError):
            ram = int(self.ram)
        try:
            return diagnose_crash(
                game_dir, exit_code, ram=ram, ram_max=self.RAM_MAX,
                java_override=bool(self.java_path),
                mods_present=mods_present,
                options_present=(game_dir / "options.txt").is_file(),
                stderr_text=stderr_text)
        except Exception:
            log.exception("could not diagnose the crash of %r", slug)
            return {}

    def crash_fix(self, action, slug=""):
        """Apply the repair offered by the crash card."""
        action = str(action or "")
        slug = str(slug or "")
        instance = self._instance_for(slug)
        if instance is None:
            return {"ok": False, "error": "That profile no longer exists."}
        slug = str(instance.get("_slug", ""))
        game_dir = instance_game_dir(instance["_root"])
        if action == "raise_ram":
            with self._lock:
                try:
                    current = int(instance.get("ram") or self.ram)
                except (TypeError, ValueError):
                    current = int(self.ram)
                target = min(self.RAM_MAX, max(4, current + 2))
                if target <= current:
                    return {
                        "ok": False,
                        "error": f"Memory is already at the maximum "
                                 f"({self.RAM_MAX} GB). Close other programs "
                                 f"or remove heavy mods."}
                instance["ram"] = target
                write_instance(instance["_root"], instance)
                if self.selected_slug == slug:
                    self.ram = target
                self._save()
            self.refresh_instances(select=self.selected_slug)
            self._event("refresh")
            return {"ok": True,
                    "message": f"Memory raised to {target} GB. Start the "
                               f"game again.",
                    "state": self.state()}
        if action == "reset_java":
            if not self.java_path:
                return {"ok": False,
                        "error": "The launcher already picks Java for this "
                                 "version automatically."}
            result = self.set_java("")
            if not result.get("ok"):
                return result
            return {"ok": True,
                    "message": "Custom Java disabled — the launcher will use "
                               "the runtime this version expects.",
                    "state": self.state()}
        if action == "verify_files":
            if self.selected_slug != slug:
                self.refresh_instances(select=slug)
            result = self.verify_files()
            if result.get("ok"):
                result["state"] = self.state()
            return result
        if action == "disable_mods":
            mods = instance_mods_dir(instance["_root"])
            if not mods.is_dir():
                return {"ok": False,
                        "error": "This profile has no mods folder."}
            target = mods.with_name(
                f"{mods.name}.disabled-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                mods.rename(target)
            except OSError as exc:
                return {"ok": False,
                        "error": f"Could not move the mods folder: {exc}"}
            log.info("mods disabled for %r: %s", slug, target.name)
            self._event("refresh")
            return {"ok": True,
                    "message": f"Mods moved to {target.name}. Rename that "
                               f"folder back to '{mods.name}' to enable them "
                               f"again.",
                    "state": self.state()}
        if action == "reset_graphics":
            options = game_dir / "options.txt"
            if not options.is_file():
                return {"ok": False,
                        "error": "options.txt has already been removed."}
            backup = options.with_name(
                f"options.txt.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                options.rename(backup)
            except OSError as exc:
                return {"ok": False,
                        "error": f"Could not reset options.txt: {exc}"}
            log.info("options.txt reset for %r: %s", slug, backup.name)
            return {"ok": True,
                    "message": "Graphics settings were reset. Start the game "
                               "again.",
                    "state": self.state()}
        return {"ok": False, "error": "Unknown crash repair."}

    def _watch_game(self, process, slug):
        """Announce the game's exit so the Play button comes back."""
        try:
            process.wait()
        except Exception:
            pass
        code = process.returncode
        with self._game_lock:
            if self._game_processes.get(slug) is not process:
                return
            self._game_processes.pop(slug, None)
            stopped = process.pid in self._game_stop_requested
            self._game_stop_requested.discard(process.pid)
        if stopped:
            self._event("gameproc", running=False, slug=slug,
                        message="Game stopped.")
        elif code:
            # A non-zero exit that we did not ask for is a crash: keep the
            # status bar quiet and put a notification in the lower-right.
            log.warning("game %r exited with code %s", slug, code)
            # The game can still be flushing latest.log right after exit.
            time.sleep(0.3)
            crash = self._explain_crash(slug, code, self._take_stderr(process))
            self._event("gameproc", running=False, slug=slug, crashed=True,
                        exit_code=code, crash=crash,
                        message=f"Minecraft closed unexpectedly "
                                f"(exit code {code}). Check the game log.")
        else:
            self._event("gameproc", running=False, slug=slug,
                        message="The game has closed.")

    def game_stop(self):
        instance = self.active_instance()
        slug = (str(instance.get("_slug", "")) if instance is not None
                else self.selected_slug)
        with self._game_lock:
            process = self._game_processes.get(slug)
        if process is None or process.poll() is not None:
            with self._game_lock:
                if self._game_processes.get(slug) is process:
                    self._game_processes.pop(slug, None)
            self._event("gameproc", running=False, slug=slug,
                        message="Game stopped.")
            return {"ok": True, "message": "Game stopped."}
        with self._game_lock:
            # Mark the kill as intentional so the watcher does not report the
            # taskkill exit code as a crash.
            self._game_stop_requested.add(process.pid)
        self._kill_game(process)
        with self._game_lock:
            stopped = self._game_processes.get(slug) is process
            if stopped:
                self._game_processes.pop(slug, None)
        if stopped:
            self._event("gameproc", running=False, slug=slug,
                        message="Game stopped.")
        return {"ok": True, "message": "Game stopped."}

    def game_restart(self):
        instance = self.active_instance()
        if instance is None:
            return {"ok": False, "error": "Create or select a profile first."}
        slug = str(instance.get("_slug", ""))
        if slug in self._launching:
            return {"ok": False, "error": "The game is already starting."}
        self.game_stop()
        return self.play()

    def play(self, world=""):
        instance = self.active_instance()
        slug = str(instance.get("_slug", "")) if instance is not None else ""
        if instance is None:
            return {"ok": False, "error": "Create or select a profile first."}
        if slug in self._launching:
            return {"ok": False, "error": "The game is already starting."}
        if self._instance_running(slug):
            return {"ok": False, "error": "This profile is already running."}
        # A profile may pin its own account; otherwise the account active in
        # Settings is used. A pinned account that was removed falls back too.
        account = (self._account_by_id(instance.get("account", ""))
                   or self._active_account())
        # A Nexi site account carries the Minecraft identity linked to it.
        # When that identity is a local Microsoft/Ely.by account, sign in with
        # that account; otherwise start offline with the linked nickname.
        nexi_offline_name = ""
        nexi_linked_type = ""
        if account is not None and account["type"] == "nexi":
            mc = account.get("mc")
            mc = mc if isinstance(mc, dict) else {}
            mc_type = str(mc.get("type") or "offline").strip().lower()
            mc_name = str(mc.get("name") or account.get("name")
                          or "").strip()[:16] or "Player"
            linked = None
            if mc_type in ("microsoft", "ely") and mc.get("uuid"):
                linked = self._account_for_profile(
                    mc_type, str(mc.get("uuid")))
            if linked is not None:
                account = linked
            else:
                nexi_offline_name = mc_name
                nexi_linked_type = mc_type
        auth = None
        if account is not None and account["type"] == "microsoft":
            token = self._ms_refresh(account)
            if not token:
                message = ("This Microsoft account needs to sign in again. "
                           "Remove it and add it from Settings.")
                self._event("play", ok=False, slug=slug, message=message)
                return {"ok": False, "error": message}
            auth = {"name": account["name"],
                    "uuid": account["uuid"],
                    "token": token, "xuid": account.get("xuid", ""),
                    "kind": "microsoft"}
            player = auth["name"]
        elif account is not None and account["type"] == "ely":
            token = self._ely_refresh(account)
            if not token:
                message = ("This Ely.by account needs to sign in again. "
                           "Remove it and add it from Settings.")
                self._event("play", ok=False, slug=slug, message=message)
                return {"ok": False, "error": message}
            auth = {"name": account["name"],
                    "uuid": account["uuid"],
                    "token": token, "xuid": "", "kind": "ely"}
            player = auth["name"]
        else:
            if nexi_offline_name:
                player = nexi_offline_name
                if nexi_linked_type in ("microsoft", "ely"):
                    label = {"microsoft": "Microsoft",
                             "ely": "Ely.by"}[nexi_linked_type]
                    self._game_line(
                        f"Nexi account is linked to a {label} account that is "
                        f"not signed in to this launcher — starting offline "
                        f"as {player}.")
            else:
                player = (account["name"] if account is not None
                          else self.player).strip() or "Player"
                if account is None:
                    self.player = player
                    self._save()
        self._launching.add(slug)
        self._event("play", ok=True, starting=True, slug=slug,
                    message="Starting…")
        try:
            version_id = str(instance.get("version", ""))
            meta = version_meta(version_id)
            if not Path(meta).is_file():
                raise RuntimeError(f'Version "{version_id}" is not installed')
            version = load_version(meta)
            progress_shown = [0]

            def java_progress(done, total):
                if not total:
                    return
                percent = int(done * 100 / total)
                if percent >= progress_shown[0] + 10 or done == total:
                    progress_shown[0] = percent
                    self._game_line(f"Java download: {percent}%")

            try:
                java = ensure_java(version, self._game_line, java_progress,
                                   None)
                self._game_line(f"Java: {java}")
            except Exception as exc:
                raise RuntimeError(f"Java is not available: {exc}") from exc
            game_dir = instance_game_dir(instance["_root"])
            game_dir.mkdir(parents=True, exist_ok=True)
            # Per-profile defaults (GUI scale, FOV, …) go into options.txt
            # before the game starts; other options are left untouched.
            if isinstance(instance.get("game_defaults"), dict):
                try:
                    write_game_options(game_dir, instance["game_defaults"])
                    self._game_line(
                        "Game defaults written to options.txt.")
                except OSError as exc:
                    log.warning("Could not write options.txt: %s", exc)
            if auth and auth.get("kind") == "ely":
                auth["authlib"] = str(ensure_authlib_injector())
            # Home's recent worlds launch straight into a save when the
            # version supports Quick Play (1.20+); older versions just open
            # the main menu.
            extra_args = []
            target_world = world_for_quick_play(game_dir, world)
            if target_world:
                if quick_play_supported(game_version_of(meta)):
                    extra_args = ["--quickPlaySingleplayer", target_world]
                else:
                    self._game_line(
                        "This version cannot open a world directly — "
                        "starting the main menu.")
            profile_id = version.get("id") or Path(meta).stem
            if neoforge_runtime_missing(profile_id):
                # NeoForge's universal/client/srg jars are not in the version
                # JSON, so a profile installed elsewhere can lack them. Only
                # the installer can rebuild them (the client jar is not on
                # maven), so run it before the game starts.
                self._game_line(
                    "NeoForge runtime files are missing — running the "
                    "installer…")
                try:
                    if not repair_neoforge_runtime(
                            profile_id, console_java(version),
                            self._game_line):
                        raise RuntimeError("the jars are still missing")
                except Exception as exc:
                    log.warning("NeoForge repair failed: %s", exc)
                    raise RuntimeError(
                        f"Could not rebuild the NeoForge files: {exc}") from exc
            command, missing = build_command(
                version, meta, player, int(self.ram), game_dir, auth=auth,
                extra_args=extra_args)
            if missing:
                # Loader installs can leave a profile whose version JSON lists
                # libraries that never arrived (an interrupted installer, a
                # shared .minecraft, a modpack made elsewhere). Fetch those
                # jars on the spot instead of failing the launch.
                self._game_line(
                    f"{len(missing)} library file(s) are missing — "
                    "downloading them…")
                fetch_missing_libraries(version, meta, self._game_line)
                command, missing = build_command(
                    version, meta, player, int(self.ram), game_dir, auth=auth,
                    extra_args=extra_args)
            if missing:
                shown = ", ".join(missing[:3])
                extra = "" if len(missing) <= 3 \
                    else f" and {len(missing) - 3} more"
                self._game_line(
                    "ERROR: could not download the missing files. Use "
                    "Profile → Verify files, then Play again.")
                raise RuntimeError(f"Missing files: {shown}{extra}")
            mode = ("Ely.by account"
                    if auth and auth.get("kind") == "ely"
                    else "Microsoft account" if auth else "offline mode")
            self._game_line(
                f"--- launching {instance_label(instance)} as {player} "
                f"({int(self.ram)} GB, {mode}) ---")
            process = subprocess.Popen(
                command, cwd=str(game_dir), close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == "nt" else 0,
            )
            # Home shows the most recently played build first.
            instance["last_played"] = time.time()
            write_instance(instance["_root"], instance)
            self.refresh_instances(select=slug)
        except Exception as exc:
            self._game_line(f"ERROR: {exc}")
            self._launching.discard(slug)
            self._event("play", ok=False, slug=slug, message=str(exc))
            return {"ok": False, "error": str(exc)}
        threading.Thread(target=self._read_stderr, args=(process,),
                         daemon=True).start()
        with self._game_lock:
            self._game_processes[slug] = process
        threading.Thread(target=self._watch_game, args=(process, slug),
                         daemon=True).start()
        threading.Thread(target=self._track_playtime, args=(process, slug),
                         daemon=True).start()
        self._launching.discard(slug)
        message = f'{instance.get("name", "Minecraft")} is running.'
        self._event("play", ok=True, starting=False, running=True, slug=slug,
                    message=message)
        return {"ok": True, "message": message}

    def _remember_stderr(self, process, line):
        """Keep the JVM's last words: startup errors never reach latest.log."""
        with self._game_lock:
            store = getattr(self, "_game_stderr_tail", None)
            if store is None:
                store = self._game_stderr_tail = {}
            lines = store.setdefault(process.pid, [])
            lines.append(line)
            if len(lines) > 300:
                del lines[:len(lines) - 300]
            if len(store) > 8:
                store.pop(next(iter(store)))

    def _take_stderr(self, process):
        with self._game_lock:
            store = getattr(self, "_game_stderr_tail", None) or {}
            return "\n".join(store.get(process.pid, []))

    def _read_stderr(self, process):
        stream = process.stderr
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._game_line(line)
                    self._remember_stderr(process, line)
        except (OSError, ValueError):
            pass
