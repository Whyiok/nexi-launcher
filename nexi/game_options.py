"""Per-profile Minecraft options.txt defaults.

The launcher keeps a small set of presentation/gameplay values per profile
and writes them into the profile's ``minecraft/options.txt`` before every
launch. Only the keys listed below are touched — anything else the player
changed inside the game (controls, sound, packs, …) is left exactly as it is.
"""

from pathlib import Path

# Launcher-facing value -> options.txt key. Values are in the units the UI
# shows (degrees, percent, chunks, …), not raw options.txt numbers.
DEFAULTS = {
    "gui_scale": 0,        # 0 = auto, 1–4 = fixed scale
    "fov": 70,             # degrees, vanilla default
    "render_distance": 12,  # chunks
    "brightness": 50,      # percent 0–100
    "particles": 0,        # 0 = all, 1 = decreased, 2 = minimal
    "fps_limit": 260,      # 260 = unlimited
}

LIMITS = {
    "gui_scale": (0, 4),
    "fov": (30, 110),
    "render_distance": (2, 32),
    "brightness": (0, 100),
    "particles": (0, 2),
    "fps_limit": (1, 260),
}


def normalize_defaults(values) -> dict:
    """Known keys only, integers clamped to the UI ranges."""
    data = dict(DEFAULTS)
    if isinstance(values, dict):
        for key, (low, high) in LIMITS.items():
            try:
                number = int(float(values.get(key, data[key])))
            except (TypeError, ValueError):
                continue
            data[key] = max(low, min(high, number))
    return data


def options_for(values) -> dict:
    """options.txt entries that represent the launcher defaults."""
    data = normalize_defaults(values)
    return {
        "guiScale": str(data["gui_scale"]),
        # options.txt stores FOV as (degrees - 70) / 40.
        "fov": f"{(data['fov'] - 70) / 40:.2f}",
        "renderDistance": str(data["render_distance"]),
        "gamma": f"{data['brightness'] / 100:.2f}",
        "particles": str(data["particles"]),
        "maxFps": str(data["fps_limit"]),
    }


def write_game_options(game_dir, values) -> dict:
    """Merge the defaults into options.txt, preserving every other key."""
    path = Path(game_dir) / "options.txt"
    data = normalize_defaults(values)
    updates = options_for(data)
    try:
        raw = path.read_text(encoding="utf-8-sig",
                             errors="replace").splitlines()
    except OSError:
        raw = []

    keys = {line.split(":", 1)[0] for line in raw if ":" in line}
    # Versions before 1.16 call the frame cap fpsLimit instead of maxFps.
    if "fpsLimit" in keys:
        updates["fpsLimit"] = str(data["fps_limit"])

    lines = []
    seen = set()
    for line in raw:
        key = line.split(":", 1)[0] if ":" in line else ""
        if key in updates and key not in seen:
            lines.append(f"{key}:{updates[key]}")
            seen.add(key)
        else:
            lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}:{value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".tmp")
    part.write_text("\n".join(lines) + ("\n" if lines else ""),
                    encoding="utf-8")
    part.replace(path)
    return updates
