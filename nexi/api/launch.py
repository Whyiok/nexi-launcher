"""Game process lifecycle."""

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from ..ely_auth import ensure_authlib_injector
from ..instances import (instance_game_dir, instance_label,
                         write_instance)
from ..java_runtime import ensure_java
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
            self._event("gameproc", running=False, slug=slug, crashed=True,
                        exit_code=code,
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
        self._launching.discard(slug)
        message = f'{instance.get("name", "Minecraft")} is running.'
        self._event("play", ok=True, starting=False, running=True, slug=slug,
                    message=message)
        return {"ok": True, "message": message}

    def _read_stderr(self, process):
        stream = process.stderr
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._game_line(line)
        except (OSError, ValueError):
            pass
