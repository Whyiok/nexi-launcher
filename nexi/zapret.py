"""Windows DPI-bypass integration (Flowseal/zapret-discord-youtube).

The launcher never ships winws.exe. It can detect an existing zapret
installation, add the Minecraft/auth/modding hosts to the user part of the
general hostlist, and (re)start the bypass through the existing Windows
service or one of the bundled strategy presets. Starting a service or
winws.exe needs administrator rights, so every write/restart runs through a
small elevated PowerShell helper.

Nothing here touches account tokens; settings.json only keeps the chosen
folder and preset name.
"""

import ctypes
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from ctypes import wintypes
from pathlib import Path

from .config import DATA_DIR
from .logging_setup import log
from .modpacks import _extract_zip
from .net import download_file, http_get, network_event
from .util import InstallCancelled

ZAPRET_REPO = "Flowseal/zapret-discord-youtube"
SERVICE_NAME = "zapret"
STRATEGY_VALUE = "zapret-discord-youtube"
ZAPRET_SITE = f"https://github.com/{ZAPRET_REPO}"
RELEASE_API = f"https://api.github.com/repos/{ZAPRET_REPO}/releases/latest"
BUNDLE_ZIP = "bundle.zip"

# Hosts the launcher itself uses. zapret matches subdomains of a hostlist
# entry, so the parent domain is enough (ely.by covers authserver.ely.by).
ZAPRET_DOMAINS = (
    "launchermeta.mojang.com",
    "piston-meta.mojang.com",
    "piston-data.mojang.com",
    "resources.download.minecraft.net",
    "libraries.minecraft.net",
    "api.minecraftservices.com",
    "api.mojang.com",
    "authserver.mojang.com",
    "sessionserver.mojang.com",
    "textures.minecraft.net",
    "maven.neoforged.net",
    "maven.minecraftforge.net",
    "files.minecraftforge.net",
    "maven.fabricmc.net",
    "meta.fabricmc.net",
    "maven.quiltmc.org",
    "meta.quiltmc.org",
    "meta.prismlauncher.org",
    "api.modrinth.com",
    "cdn.modrinth.com",
    "curseforge.com",
    "www.curseforge.com",
    "api.curseforge.com",
    "mediafilez.forgecdn.net",
    "edge.forgecdn.net",
    "api.cfwidget.com",
    "ely.by",
    "authserver.ely.by",
    "account.ely.by",
    "skinsystem.ely.by",
    "login.microsoftonline.com",
    "login.live.com",
    "user.auth.xboxlive.com",
    "xsts.auth.xboxlive.com",
    "sisu.xboxlive.com",
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "api.github.com",
)

DEFAULT_PRESET = "general.bat"


def is_windows() -> bool:
    return os.name == "nt"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# Service state is read with the Windows service API and the process list with
# the toolhelp snapshot instead of shelling out to PowerShell. Both are read-
# only, cheap, and — unlike a hidden PowerShell process polling every few
# seconds — do not look like malware to antivirus heuristics.

_SERVICE_STATES = {1: "stopped", 2: "running", 3: "stopped", 4: "running"}

_ERROR_SERVICE_DOES_NOT_EXIST = 1060

_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SC_STATUS_PROCESS_INFO = 0

_TH32CS_SNAPPROCESS = 0x00000002


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwServiceFlags", wintypes.DWORD),
    ]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _service_info() -> dict:
    """ImagePath/strategy from the service registry (readable without admin)."""
    if not is_windows():
        return {}
    try:
        import winreg

        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}", 0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            info = {}
            try:
                info["ImagePath"] = str(winreg.QueryValueEx(key, "ImagePath")[0])
            except OSError:
                pass
            try:
                info["Strategy"] = str(
                    winreg.QueryValueEx(key, STRATEGY_VALUE)[0])
            except OSError:
                pass
            return info
    except OSError:
        return {}


def service_state() -> str:
    """'running' | 'stopped' | 'absent' | 'unknown'."""
    if not is_windows():
        return "absent"
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.OpenSCManagerW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        advapi32.OpenSCManagerW.restype = wintypes.HANDLE
        advapi32.OpenServiceW.argtypes = [
            wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
        advapi32.OpenServiceW.restype = wintypes.HANDLE
        advapi32.QueryServiceStatusEx.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD)]
        advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
        advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
        advapi32.CloseServiceHandle.restype = wintypes.BOOL

        manager = advapi32.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
        if not manager:
            return "unknown"
        try:
            service = advapi32.OpenServiceW(manager, SERVICE_NAME,
                                            _SERVICE_QUERY_STATUS)
            if not service:
                if ctypes.get_last_error() == _ERROR_SERVICE_DOES_NOT_EXIST:
                    return "absent"
                return "unknown"
            try:
                status = _SERVICE_STATUS_PROCESS()
                needed = wintypes.DWORD()
                if not advapi32.QueryServiceStatusEx(
                        service, _SC_STATUS_PROCESS_INFO,
                        ctypes.byref(status), ctypes.sizeof(status),
                        ctypes.byref(needed)):
                    return "unknown"
                return _SERVICE_STATES.get(int(status.dwCurrentState),
                                           "unknown")
            finally:
                advapi32.CloseServiceHandle(service)
        finally:
            advapi32.CloseServiceHandle(manager)
    except (OSError, AttributeError):
        return "unknown"


def service_strategy() -> str:
    info = _service_info()
    return str(info.get("Strategy", "") or "").strip()


def process_running() -> bool:
    if not is_windows():
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return False
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return False
            while True:
                if str(entry.szExeFile).lower() == "winws.exe":
                    return True
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return False
        finally:
            kernel32.CloseHandle(snapshot)
    except (OSError, AttributeError):
        return False


def parse_image_path(value: str):
    """Return (root, {"exe", "hostlists"}) from a service ImagePath value."""
    text = str(value or "").strip()
    if not text:
        return None, {"exe": "", "hostlists": []}
    if text.startswith('"'):
        end = text.find('"', 1)
        exe = text[1:end] if end > 0 else ""
    else:
        exe = text.split()[0] if text.split() else ""
    hostlists = []
    for match in re.finditer(
            r"--hostlist(?:\s+|=)(?:\"([^\"]+)\"|(\S+))", text):
        path = (match.group(1) or match.group(2) or "").strip()
        if path:
            hostlists.append(path)
    if not exe or not exe.lower().endswith(".exe"):
        return None, {"exe": exe, "hostlists": hostlists}
    exe = os.path.expandvars(exe)
    exe_path = Path(exe)
    root = exe_path.parent.parent if exe_path.parent.name.lower() == "bin" \
        else exe_path.parent
    return root, {"exe": str(exe_path), "hostlists": hostlists}


def _valid_root(root: Path) -> bool:
    if root is None:
        return False
    try:
        if not Path(root).is_dir():
            return False
    except OSError:
        return False
    root = Path(root)
    return ((root / "bin" / "winws.exe").is_file()
            or (root / "lists" / "list-general.txt").is_file()
            or any(root.glob("general*.bat")))


def list_presets(root: Path) -> list:
    try:
        names = [path.name for path in Path(root).glob("*.bat")
                 if path.name.lower() != "service.bat"
                 # Our own hidden copies (see build_apply_script) are not presets.
                 and not path.name.lower().startswith(".nexi-")]
    except OSError:
        return []
    return sorted(names, key=lambda name: (name.lower() != DEFAULT_PRESET,
                                           name.lower()))


def _target_list(root: Path, hostlists) -> Path:
    """Prefer the user list the running preset actually reads."""
    paths = [Path(os.path.expandvars(str(item))) for item in hostlists or []]
    for wanted in ("list-general-user.txt", "list-general.txt"):
        for path in paths:
            if path.name.lower() == wanted:
                return path
    return Path(root) / "lists" / "list-general-user.txt"


def _read_list(list_path: Path) -> list:
    try:
        text = Path(list_path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    return text.splitlines()


def find_missing(list_path: Path, domains=ZAPRET_DOMAINS) -> list:
    present = {line.strip().lower() for line in _read_list(list_path)
               if line.strip() and not line.lstrip().startswith("#")}
    return [domain for domain in domains if domain.lower() not in present]


def merge_domains(list_path: Path, domains=ZAPRET_DOMAINS):
    """Add missing hosts to the user list; returns (added, total)."""
    path = Path(list_path)
    existed = path.is_file()
    lines = _read_list(path)
    existing = {line.strip().lower() for line in lines
                if line.strip() and not line.lstrip().startswith("#")}
    added = 0
    for domain in domains:
        if domain.lower() in existing:
            continue
        lines.append(domain)
        existing.add(domain.lower())
        added += 1
    if not added:
        return 0, len(domains)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = Path(str(path) + ".nexi-backup")
    try:
        if existed and not backup.exists():
            shutil.copy2(path, backup)
    except OSError:
        pass
    if not existed:
        lines.insert(0, "# Nexi Launcher - Minecraft hosts")
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return added, len(domains)


def detect_install(saved_path: str = "", prefer_saved: bool = False) -> dict:
    """Find zapret and describe the service, presets and list state.

    The service's ImagePath wins over a remembered folder: that is where the
    running winws.exe actually reads its lists from. ``prefer_saved`` is used
    by the folder picker, where the user's explicit choice must win.
    """
    result = {
        "found": False, "root": "", "service": "absent", "strategy": "",
        "presets": [], "preset": "", "running": False, "admin": is_admin(),
        "list_path": "", "missing": [], "version": "", "candidates": [],
        "error": "",
    }
    candidates = []

    def consider(root, hostlists=()):
        if root is None or not _valid_root(Path(root)):
            return None
        root = Path(root).resolve()
        if any(root == item for item in candidates):
            return None
        candidates.append(root)
        return root

    chosen = None
    if prefer_saved and saved_path:
        chosen = consider(saved_path)

    info = _service_info()
    image_root = None
    hostlists = []
    if info.get("ImagePath"):
        image_root, parsed = parse_image_path(info["ImagePath"])
        hostlists = parsed.get("hostlists") or []
        if chosen is None:
            chosen = consider(image_root)
    result["service"] = service_state()
    result["strategy"] = str(info.get("Strategy", "") or "").strip()

    if process_running():
        result["running"] = True

    if chosen is None and saved_path:
        chosen = consider(saved_path)

    for base in (DATA_DIR / "zapret",):
        consider(base)
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA",
                     "USERPROFILE"):
        base = os.environ.get(env_name)
        if base:
            consider(Path(base) / "zapret")
    consider(Path("C:/zapret"))
    for env_name in ("USERPROFILE",):
        base = os.environ.get(env_name)
        if base:
            for folder in ("Desktop", "Downloads"):
                parent = Path(base) / folder
                try:
                    for path in parent.glob("zapret*"):
                        consider(path)
                except OSError:
                    pass

    if chosen is None and candidates:
        chosen = candidates[0]
    if chosen is None:
        result["candidates"] = [str(path) for path in candidates]
        if result["service"] == "running":
            result["found"] = True
            result["running"] = True
            result["error"] = ""
        return result

    root = Path(chosen)
    result.update({
        "found": True, "root": str(root),
        "presets": list_presets(root),
        "candidates": [str(path) for path in candidates],
    })
    presets = result["presets"]
    preset = ""
    for name in presets:
        if name.lower() == (result["strategy"] + ".bat").lower():
            preset = name
            break
    if not preset:
        preset = next((name for name in presets
                       if name.lower() == DEFAULT_PRESET), "")
    if not preset and presets:
        preset = presets[0]
    result["preset"] = preset

    match = re.search(r"(\d+(?:\.\d+){1,3})", root.name)
    if match:
        result["version"] = match.group(1)

    list_path = _target_list(root, hostlists)
    result["list_path"] = str(list_path)
    try:
        result["missing"] = find_missing(list_path)
    except OSError as exc:
        result["error"] = f"The zapret list is not readable: {exc}"
    result["running"] = (result["service"] == "running"
                         or result["running"] or process_running())
    return result


def fetch_latest_zip(log_fn=print) -> dict:
    """Latest release's .zip asset from the GitHub API."""
    raw = http_get(RELEASE_API, timeout=60)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub returned an unreadable release list: {exc}")
    assets = data.get("assets") or []
    zips = [item for item in assets
            if str(item.get("name", "")).lower().endswith(".zip")]
    if not zips:
        names = ", ".join(str(item.get("name", "?")) for item in assets) or "none"
        raise RuntimeError(
            f"The latest zapret release has no .zip asset (found: {names})")
    asset = zips[0]
    version = str(data.get("tag_name") or "").strip()
    log_fn(f"Using zapret {version or 'release'} ({asset['name']}).")
    return {"url": asset["browser_download_url"], "version": version,
            "size": int(asset.get("size") or 0), "name": asset["name"]}


def install_bundle(target: Path, log_fn=print, progress=None, cancel=None) -> dict:
    """Download and unpack the latest release into *target*."""
    info = fetch_latest_zip(log_fn)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    archive = target / BUNDLE_ZIP
    network_event("info", f"Downloading zapret {info['version']}…")
    download_file(info["url"], archive, size=info["size"] or None,
                  cancel=cancel, on_progress=progress)
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    log_fn(f"Unpacking zapret {info['version']}…")
    with zipfile.ZipFile(archive) as bundle:
        names = [name.replace("\\", "/") for name in bundle.namelist()
                 if not name.endswith("/")]
        tops = {name.split("/")[0] for name in names if "/" in name}
        prefix = ""
        if len(tops) == 1 and all("/" in name for name in names):
            prefix = next(iter(tops)) + "/"
        count = _extract_zip(bundle, target, prefix, log_fn, cancel=cancel)
    try:
        archive.unlink()
    except OSError:
        pass
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()
    if not count:
        raise RuntimeError("The zapret archive did not contain any files.")
    network_event("ok", f"zapret {info['version']} unpacked.")
    return {"ok": True, "root": str(target), "version": info["version"],
            "count": count}


def _ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _apply_script(root: Path, preset: str, list_path, pending_domains,
                  stop_only: bool, log_file: Path, result_file: Path) -> str:
    list_arg = _ps_quote(list_path) if list_path else "''"
    domains_arg = _ps_quote(pending_domains) if pending_domains else "''"
    # PowerShell has no bare true/false literals: they must be $true/$false.
    stop_literal = "$true" if stop_only else "$false"
    return f"""$ErrorActionPreference = 'Stop'
$result = {_ps_quote(result_file)}
try {{
  $logFile = {_ps_quote(log_file)}
  $root = {_ps_quote(root)}
  $preset = {_ps_quote(preset)}
  $listPath = {list_arg}
  $domainsFile = {domains_arg}
  $stopOnly = {stop_literal}
  function Write-Step([string]$text) {{
    $stamp = Get-Date -Format 'HH:mm:ss'
    "$stamp $text" | Add-Content -LiteralPath $logFile -Encoding UTF8
  }}
  Write-Step 'helper started'
  if ($listPath -and $domainsFile) {{
    $existing = @()
    if (Test-Path -LiteralPath $listPath) {{
      $existing = @(Get-Content -LiteralPath $listPath -Encoding UTF8)
    }} else {{
      $parent = Split-Path -LiteralPath $listPath
      if ($parent) {{ New-Item -ItemType Directory -Force -Path $parent | Out-Null }}
      $existing = @('# Nexi Launcher - Minecraft hosts')
    }}
    $added = 0
    foreach ($domain in @(Get-Content -LiteralPath $domainsFile -Encoding UTF8)) {{
      $domain = $domain.Trim()
      if (-not $domain) {{ continue }}
      if ($existing -notcontains $domain) {{ $existing += $domain; $added++ }}
    }}
    if ($added -gt 0) {{
      $existing | Set-Content -LiteralPath $listPath -Encoding ASCII
      Write-Step "list: added $added domain(s)"
    }} else {{
      Write-Step 'list: nothing to add'
    }}
  }}
  $svc = Get-Service -Name '{SERVICE_NAME}' -ErrorAction SilentlyContinue
  if ($null -ne $svc) {{
    Write-Step "service: $($svc.Status)"
    if ($stopOnly) {{
      if ($svc.Status -eq 'Running') {{
        Stop-Service -Name '{SERVICE_NAME}' -Force
        try {{ $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(15)) }} catch {{}}
      }}
      Write-Step 'service stopped'
    }} else {{
      if ($svc.Status -eq 'Running') {{
        try {{
          Stop-Service -Name '{SERVICE_NAME}' -Force
          try {{ $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(15)) }} catch {{}}
          Write-Step 'service stopped'
        }} catch {{
          Write-Step "stop failed: $($_.Exception.Message)"
        }}
      }}
      Start-Service -Name '{SERVICE_NAME}'
      $svc.Refresh()
      try {{ $svc.WaitForStatus('Running', [TimeSpan]::FromSeconds(20)) }} catch {{}}
      $svc.Refresh()
      if ($svc.Status -ne 'Running') {{
        throw 'The zapret service did not start.'
      }}
      Write-Step 'service started'
    }}
  }} else {{
    # Never kill winws.exe from another installation: compare paths first.
    $all = @(Get-Process -Name 'winws' -ErrorAction SilentlyContinue)
    $ours = @($all | Where-Object {{
      try {{ $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) }}
      catch {{ $false }}
    }})
    $foreign = @($all | Where-Object {{ $ours -notcontains $_ }})
    if ($foreign.Count -gt 0 -and -not $stopOnly) {{
      throw 'Another zapret instance is running from a different folder. Stop it first.'
    }}
    if ($ours.Count -gt 0) {{
      $ours | Stop-Process -Force
      Start-Sleep -Milliseconds 500
    }}
    if ($stopOnly) {{
      Write-Step 'winws stopped'
    }} else {{
      Start-Sleep -Milliseconds 500
      $bat = Join-Path $root $preset
      if (-not (Test-Path -LiteralPath $bat)) {{
        throw "Preset not found: $bat"
      }}
      # Run a modified copy of the preset. Its check_updates call opens the
      # zapret page in a browser when the install is outdated, and ``start
      # /min`` gives winws.exe its own console window. The copy has to stay in
      # the zapret folder: the preset builds every path from %~dp0.
      $hidden = Join-Path $root ('.nexi-' + [IO.Path]::GetFileName($bat))
      $source = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($bat))
      $lines = New-Object 'System.Collections.Generic.List[string]'
      foreach ($line in ($source -split "`r`n|`n")) {{
        if ($line -match '^\\s*call\\s+service\\.bat\\s+check_updates\\b') {{ continue }}
        $lines.Add([regex]::Replace($line,
          '^(\\s*)start\\s+"[^"]*"\\s+/min\\s+', '$1'))
      }}
      [IO.File]::WriteAllText($hidden, ($lines -join "`r`n"),
        [System.Text.UTF8Encoding]::new($false))
      $env:NO_UPDATE_CHECK = '1'
      Start-Process -FilePath $hidden -WorkingDirectory $root -WindowStyle Hidden
      Start-Sleep -Seconds 2
      $running = @(Get-Process -Name 'winws' -ErrorAction SilentlyContinue).Count -gt 0
      if (-not $running) {{
        throw 'winws.exe did not start. Check the strategy and antivirus.'
      }}
      Write-Step "preset started: $preset"
    }}
  }}
  'OK' | Set-Content -LiteralPath $result -Encoding UTF8
}} catch {{
  "ERR $($_.Exception.Message)" | Set-Content -LiteralPath $result -Encoding UTF8
  Write-Step "ERROR: $($_.Exception.Message)"
}}
"""


def build_apply_script(root: Path, preset: str, list_path, pending_domains,
                       stop_only: bool = False):
    temp_dir = Path(tempfile.mkdtemp(prefix="nexi-zapret-"))
    log_file = temp_dir / "apply.log"
    result_file = temp_dir / "result.txt"
    # Create both files before elevation. Files created by the elevated
    # helper would be owned by the Administrators group and inherit an ACL
    # the normal launcher process cannot read; pre-created files keep the
    # current user's owner rights, while the helper can still write them.
    log_file.touch()
    result_file.touch()
    domains_file = None
    if pending_domains:
        domains_file = temp_dir / "domains.txt"
        domains_file.write_text(
            "\n".join(str(item) for item in pending_domains) + "\n",
            encoding="utf-8")
    script = _apply_script(Path(root), preset or DEFAULT_PRESET, list_path,
                           domains_file, stop_only, log_file, result_file)
    script_file = temp_dir / "apply.ps1"
    script_file.write_text(script, encoding="utf-8-sig")
    return temp_dir, script_file, result_file, log_file


def _read_log(path: Path) -> list:
    for _ in range(10):
        try:
            return [line.strip() for line in
                    path.read_text(encoding="utf-8-sig",
                                   errors="replace").splitlines()
                    if line.strip()]
        except PermissionError:
            # The elevated helper is still writing to the file.
            time.sleep(0.1)
        except OSError:
            return []
    return []


def _read_result(path: Path) -> str:
    text = ""
    for _ in range(30):
        try:
            text = path.read_text(encoding="utf-8-sig",
                                  errors="replace").strip()
            if text:
                return text
        except PermissionError:
            pass
        except OSError:
            return ""
        time.sleep(0.1)
    return text


def _result_ready(path: Path) -> bool:
    """The result file is pre-created empty; wait until it has content."""
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


# SEE_MASK_NOCLOSEPROCESS gives us the helper's handle, SEE_MASK_NOASYNC
# keeps ShellExecuteEx from returning before the process exists.
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100


def _launch_elevated(params: str, program: str = "powershell.exe"):
    """Start a program elevated.

    Returns (error_code, process_handle). error_code is 0 on success; a
    non-zero value is the ShellExecuteEx error (1223 = UAC dismissed).
    """
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = program
    info.lpParameters = params
    info.nShow = 0
    if shell32.ShellExecuteExW(ctypes.byref(info)):
        return 0, info.hProcess
    return ctypes.get_last_error() or 1, None


def _process_exited(handle) -> bool:
    if not handle:
        return False
    kernel32 = ctypes.windll.kernel32
    return kernel32.WaitForSingleObject(handle, 0) == 0


def _close_handle(handle) -> None:
    if handle:
        try:
            ctypes.windll.kernel32.CloseHandle(handle)
        except OSError:
            pass


def elevate_apply(root: Path, preset: str, list_path, pending_domains,
                  stop_only: bool = False, cancel=None,
                  on_log=None) -> dict:
    """Run the apply script elevated and wait for its result file.

    on_log, when given, receives each helper log line as it appears so the
    UI can show progress during the elevation prompt and service restart.
    """
    if not is_windows():
        return {"ok": False,
                "error": "The zapret integration is Windows-only."}
    temp_dir, script_file, result_file, log_file = build_apply_script(
        root, preset, list_path, pending_domains, stop_only)
    console_file = temp_dir / "console.log"
    console_file.touch()
    handle = None
    try:
        # cmd.exe keeps the helper's console output (including script-load
        # errors that never reach our own log) in a readable file.
        params = (f'/c powershell.exe -NoProfile -ExecutionPolicy Bypass '
                  f'-File "{script_file}" > "{console_file}" 2>&1')
        comspec = str(os.environ.get("COMSPEC", "") or "")
        if not comspec.lower().endswith("cmd.exe") or not os.path.isfile(
                comspec):
            comspec = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                   "System32", "cmd.exe")
        rc, handle = _launch_elevated(params, comspec)
        if rc:
            cancelled = rc in (5, 31, 1223)
            return {"ok": False, "cancelled": cancelled,
                    "error": ("Administrator rights were not granted."
                              if cancelled else
                              f"Could not start the elevated helper (code {rc})."),
                    "log": []}
        deadline = time.monotonic() + 120
        exited = False
        seen = 0

        def flush_log():
            nonlocal seen
            lines = _read_log(log_file)
            if on_log is not None and len(lines) > seen:
                for line in lines[seen:]:
                    on_log(line)
            seen = len(lines)

        while time.monotonic() < deadline:
            flush_log()
            if _result_ready(result_file):
                # The helper writes the result as its last step. Give the
                # process a moment to exit so the file is fully flushed.
                if handle:
                    for _ in range(50):
                        if _process_exited(handle):
                            break
                        time.sleep(0.1)
                break
            if cancel is not None and cancel.is_set():
                return {"ok": False, "cancelled": True,
                        "log": _read_log(log_file),
                        "error": "Cancelled. The elevated step may still "
                                 "finish in the background."}
            if _process_exited(handle):
                exited = True
                break
            time.sleep(0.25)
        flush_log()
        log_lines = _read_log(log_file)
        for line in _read_log(console_file)[-10:]:
            if line not in log_lines:
                log_lines.append(line)
        outcome = _read_result(result_file)
        if not outcome:
            if exited:
                return {"ok": False, "log": log_lines,
                        "error": ("The elevated helper exited without a "
                                  "result. Run it again; if it keeps "
                                  "failing, check the log.")}
            return {"ok": False, "log": log_lines,
                    "error": ("The elevated helper did not finish. Check "
                              "whether the Windows prompt is still open.")}
        if outcome.upper().startswith("OK"):
            return {"ok": True, "log": log_lines, "message": outcome}
        message = outcome[4:].strip() if outcome.upper().startswith("ERR") \
            else outcome or "Unknown error."
        return {"ok": False, "log": log_lines, "error": message}
    finally:
        _close_handle(handle)
        shutil.rmtree(temp_dir, ignore_errors=True)
