"""Explain a Minecraft crash from the log and the newest crash report."""

import re
from pathlib import Path

LOG_LIMIT = 262144
REPORT_LIMIT = 65536
EXCERPT_LINES = 14
EXCERPT_CHARS = 4000


def _read_tail(path: Path, limit: int) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def latest_crash_report(game_dir) -> Path | None:
    folder = Path(game_dir) / "crash-reports"
    try:
        reports = [item for item in folder.glob("crash-*.txt") if item.is_file()]
        reports.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return reports[0] if reports else None


def _description(report_text: str) -> str:
    match = re.search(r"^Description:\s*(.+)$", report_text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _excerpt(report_text: str, log_text: str, stderr_text: str = "") -> str:
    interesting = []
    keys = ("exception", "error", "caused by", "fatal", "crash", "failed",
            "unsupported", "outofmemory", "could not", "cannot", "heap")
    for source in (report_text, log_text, stderr_text):
        for line in source.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(key in line.lower() for key in keys):
                interesting.append(line[:400])
    if not interesting:
        interesting = [line.strip()[:400]
                       for line in (log_text + "\n" + stderr_text).splitlines()
                       if line.strip()][-8:]
    return "\n".join(interesting[-EXCERPT_LINES:])[-EXCERPT_CHARS:]


def _has(text: str, *patterns: str) -> bool:
    return any(pattern in text for pattern in patterns)


def diagnose_crash(game_dir, exit_code, ram=0, ram_max=16,
                   java_override=False, mods_present=False,
                   options_present=False, stderr_text="") -> dict:
    """Return a readable crash card for the last session of *game_dir*.

    The result is JSON-ready and is sent to the page with the ``gameproc``
    event. ``fix`` is only present when the launcher can repair the cause
    without guessing at the user's files.
    """
    game_dir = Path(game_dir)
    report = latest_crash_report(game_dir)
    report_text = _read_tail(report, REPORT_LIMIT) if report else ""
    log_text = _read_tail(game_dir / "logs" / "latest.log", LOG_LIMIT)
    stderr_text = str(stderr_text or "")[-REPORT_LIMIT:]
    text = (report_text + "\n" + log_text + "\n" + stderr_text).lower()
    description = _description(report_text)
    crash = {
        "exit_code": exit_code,
        "log": _excerpt(report_text, log_text, stderr_text),
        "report": str(report) if report else "",
        "report_name": report.name if report else "",
        "description": description,
    }

    if _has(text, "outofmemoryerror", "java heap space",
            "insufficient memory for the java runtime",
            "there is insufficient memory",
            "could not reserve enough space for object heap",
            "invalid maximum heap size"):
        target = min(int(ram_max), max(4, int(ram) + 2))
        fix = ({"action": "raise_ram",
                "label": f"Raise memory to {target} GB"}
               if target > int(ram) else None)
        steps = ["Close browsers, other games and heavy programs, then "
                 "start the game again."]
        if fix:
            steps.append("Use Auto-fix to give this profile more memory.")
        else:
            steps.append("The profile already uses the maximum memory the "
                         "launcher allows.")
        steps.append("If it keeps happening, lower the render distance or "
                     "remove some heavy mods and shaderpacks.")
        crash.update(
            kind="memory",
            title="Minecraft ran out of memory",
            summary="Java reached the profile's memory limit and the game "
                    "was stopped.",
            why="The game needed more memory than the profile was allowed to "
                "use. Large modpacks, high render distance and shaderpacks "
                "increase that need.",
            steps=steps,
            fix=fix)
        return crash

    if _has(text, "unsupportedclassversionerror", "class file version",
            "has been compiled by a more recent version", "requires java",
            "error occurred during initialization of vm",
            "could not create the java virtual machine",
            "unrecognized vm option", "java: not found"):
        fix = ({"action": "reset_java", "label": "Use the launcher's Java"}
               if java_override else None)
        steps = []
        if fix:
            steps.append("Use Auto-fix to stop forcing a custom Java — the "
                         "launcher will pick the runtime this version "
                         "expects.")
        else:
            steps.append("Open Settings → Java and make sure no custom Java "
                         "path is set.")
        steps.append("If a mod requires a newer Java, update the mod or use "
                     "a Minecraft version that supports it.")
        steps.append("Use Profile → Verify files if Java's runtime files "
                     "look damaged.")
        crash.update(
            kind="java",
            title="The game is running on the wrong Java version",
            summary="A class in the game or in a mod was built for a "
                    "different Java version, or Java could not start at all.",
            why="Newer Minecraft versions and many mods need a newer Java. A "
                "manually selected Java can also be too old, too new or "
                "incomplete.",
            steps=steps,
            fix=fix)
        return crash

    if _has(text, "incompatible mod set", "mod resolution encountered an error",
            "missing or unsupported mandatory dependencies",
            "duplicate mods", "incompatible mods found",
            "mod resolution failed", "mods.toml"):
        fix = ({"action": "disable_mods", "label": "Disable mods"}
               if mods_present else None)
        steps = []
        if fix:
            steps.append("Use Auto-fix to move the mods folder aside — the "
                         "game will start without mods.")
        else:
            steps.append("Remove the mods one by one from the mods folder "
                         "and start the game after each removal.")
        steps.append("Read the crash report to find the named mod, then "
                     "reinstall it with its required dependencies for this "
                     "game version.")
        steps.append("Add mods back in small groups to find the one that "
                     "breaks the game.")
        crash.update(
            kind="mods",
            title="A mod stopped the game from starting",
            summary="The loader found conflicting, missing or incompatible "
                    "mods and refused to launch.",
            why="Mods must match the game version and the loader, and every "
                "dependency has to be installed at a compatible version.",
            steps=steps,
            fix=fix)
        return crash

    if _has(text, "failed to locate library", "missing library",
            "invalid or corrupt jarfile", "error opening zip file",
            "could not find or load main class", "unable to access jarfile",
            "noclassdeffounderror", "classnotfoundexception", "jvm.cfg"):
        crash.update(
            kind="files",
            title="Game files are missing or damaged",
            summary="Minecraft could not find a library or one of its core "
                    "files, so it exited.",
            why="A download was interrupted, a file was deleted, or an "
                "antivirus removed a library. Loader installs can also leave "
                "a version without all of its libraries.",
            steps=[
                "Use Auto-fix to re-download any missing or damaged files.",
                "If an antivirus lists a game file as a threat, add the "
                "launcher folder to its exclusions.",
                "Start the game again after the check finishes.",
            ],
            fix={"action": "verify_files", "label": "Verify game files"})
        return crash

    if _has(text, "pixel format not accelerated", "glfw error",
            "failed to create window", "opengl error",
            "unsupported opengl", "wglcreatecontext failed",
            "exception_access_violation", "0xc0000005", "-1073741819",
            "ig4icd", "ig9icd", "nvoglv"):
        fix = ({"action": "reset_graphics",
                "label": "Reset graphics settings"}
               if options_present else None)
        steps = [
            "Update the graphics driver from the GPU manufacturer's site "
            "(NVIDIA, AMD or Intel), not through Windows Update."
        ]
        if fix:
            steps.append("Use Auto-fix to reset options.txt if a wrong "
                         "graphics mode was saved.")
        else:
            steps.append("Delete options.txt in the game folder to return "
                         "Minecraft to its default graphics settings.")
        steps.append("Disable overlays and try starting the game without "
                     "mods.")
        crash.update(
            kind="graphics",
            title="The graphics driver stopped the game",
            summary="Minecraft could not create a graphics context or the "
                    "driver crashed while the game was running.",
            why="Outdated or broken GPU drivers, forced graphics settings and "
                "overlay programs (Discord, GeForce Experience, MSI Afterburner) "
                "can all interrupt the game this way.",
            steps=steps,
            fix=fix)
        return crash

    if _has(text, "invalid session", "failed to authenticate",
            "authentication servers are down", "invalid credentials"):
        crash.update(
            kind="auth",
            title="The account could not sign in",
            summary="Minecraft closed because the session or the account "
                    "credentials were rejected.",
            why="The login token expired, the account was signed in "
                "elsewhere, or the authentication service was unavailable.",
            steps=[
                "Remove the account in Settings → Accounts and add it again.",
                "Make sure the system clock and time zone are correct.",
                "Wait a few minutes if the authentication servers are down, "
                "then try again.",
            ],
            fix=None)
        return crash

    if description:
        summary = f"The game reported: {description}."
    else:
        summary = (f"Minecraft closed with exit code {exit_code} before it "
                   f"could show a clear error.")
    crash.update(
        kind="unknown",
        title="Minecraft closed unexpectedly",
        summary=summary,
        why="The launcher did not find a known cause in the log. The crash "
            "report usually names the failing mod or driver.",
        steps=[
            "Use Auto-fix to check the game files — it is safe and fixes "
            "damaged downloads.",
            "Open the crash report (Technical details below) and look for "
            "'Caused by' or the last 'at ...' lines.",
            "If the crash started after adding mods or changing settings, "
            "undo that change and try again.",
        ],
        fix={"action": "verify_files", "label": "Verify game files"})
    return crash
