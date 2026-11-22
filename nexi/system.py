"""Machine detection for the first-run setup screen."""

import ctypes
import os


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def total_memory_gb() -> float:
    """Physical RAM in GB, or 0 when it cannot be detected."""
    if os.name == "nt":
        try:
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(status)):
                return round(status.ullTotalPhys / (1024 ** 3), 1)
        except (AttributeError, OSError, ValueError):
            pass
        return 0.0
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page / (1024 ** 3), 1)
    except (AttributeError, TypeError, ValueError, OSError):
        return 0.0


def recommend_setup(total_gb, ram_min=1, ram_max=16) -> dict:
    """RAM and game options that suit a machine with this much memory."""
    total = max(0.0, float(total_gb or 0))
    if total <= 0:
        ram = 4
    elif total <= 4:
        ram = 2
    elif total <= 8:
        ram = 4
    elif total <= 12:
        ram = 5
    elif total <= 16:
        ram = 6
    elif total <= 24:
        ram = 8
    elif total <= 32:
        ram = 10
    else:
        ram = 12
    if total:
        # Leave the rest of the machine to Windows and the launcher itself;
        # never plan to allocate more than ~60% of physical memory.
        ram = min(ram, max(2, int(total * 0.6)))
    ram = max(int(ram_min), min(int(ram_max), ram))

    if total and total <= 8:
        tier = "light"
        game = {"render_distance": 8, "particles": 2, "fps_limit": 60}
    elif total and total <= 16:
        tier = "balanced"
        game = {"render_distance": 10, "particles": 1, "fps_limit": 120}
    else:
        tier = "quality"
        game = {"render_distance": 12, "particles": 0, "fps_limit": 260}
    game.update({"gui_scale": 0, "fov": 70, "brightness": 50})
    return {"ram": ram, "game": game, "total_ram": int(round(total)),
            "tier": tier}
