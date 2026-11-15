# Nexi Launcher

A lightweight custom Minecraft launcher for Windows. The backend is Python,
the interface is plain HTML/CSS/JS rendered with
[pywebview](https://pywebview.flowrl.com/) (Edge WebView2), and the release
build is a single `Nexi Launcher.exe` produced by PyInstaller.

> Unofficial project. Not affiliated with Mojang, Microsoft or Modrinth.
> You still need to own a copy of Minecraft to play online.

## Features

- **Isolated profiles** (Prism-style): each profile has its own game directory
  under `%APPDATA%\.minecraft\instances\<slug>\minecraft`, while the Mojang
  versions, libraries and assets are shared. Nothing is copied or migrated from
  an existing `.minecraft`.
- **Version management**: releases, snapshots, old betas and old alphas with
  filter chips; change the Minecraft version, the mod loader or the loader
  build of an existing profile without recreating it.
- **Loaders**: Fabric, Forge and NeoForge installed from their official
  installers.
- **Mods**: Modrinth browser with infinite scroll (pages are prefetched before
  you reach the bottom), multi-select batch install, per-profile browser state,
  installed mod names and icons resolved from Modrinth or straight from the jar
  files (works offline).
- **Resource packs, shaders and modpacks**: packs work on vanilla profiles;
  mods require a loader. `.mrpack`, CurseForge `.zip` and plain archives can be
  imported as new profiles.
- **Accounts**: Microsoft (device-code OAuth), Ely.by (Yggdrasil password or
  OAuth2 + PKCE) and offline accounts, kept as a list you can switch between.
- **Automatic Java**: the Mojang runtime matching the selected version is
  reused or downloaded on demand.
- **Profile tools**: duplicate, worlds backup, file verification, custom icon,
  log viewer, worlds and screenshots panes, Play / Stop / Restart.

## Requirements

- Windows 10 or 11 (x64)
- Microsoft Edge WebView2 Runtime (preinstalled on Windows 11; otherwise
  install the Evergreen runtime from Microsoft)
- Python 3.11+ to run from source (`tomllib` is used)

## Run from source

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python launcher.py
```

## Build the executable

```powershell
pip install -r requirements-dev.txt
.\build.ps1
```

or manually:

```powershell
python -m PyInstaller "build/Nexi Launcher.spec" `
    --distpath _dist --workpath _build_tmp --noconfirm
```

The result is `_dist\Nexi Launcher.exe` (onefile, no console window).

## Project layout

```
launcher.py          Python backend, Mojang/Modrinth/auth logic and the JS bridge
webui/index.html     single-page UI
webui/style.css      design tokens and layout
webui/app.js         UI logic, talks to Python via window.pywebview.api
build/Nexi Launcher.spec  PyInstaller spec (bundles the webui folder)
build.ps1            convenience build script
```

## Local data and privacy

Runtime files are created next to the executable / `launcher.py` and are
excluded from git:

- `settings.json` — accounts, tokens, RAM and Java settings;
- `logs\launcher.log` — rotating diagnostic log;
- `authlib-injector-*.jar` — downloaded automatically for Ely.by launches.

Passwords and Ely.by OAuth secrets are never written to the log (the
corresponding API calls are excluded from tracing). Never commit
`settings.json` or `logs\` — they can contain account tokens.

## Notes

- Modrinth requests are made directly from Python; on networks where
  `api.modrinth.com` is blocked the browser shows a clear error instead of
  hanging.
- The launcher is Windows-only: it relies on WinForms/WebView2 through
  pywebview and on PowerShell dialogs for file picking.

## License

[MIT](LICENSE) © 2026 Whyiok
