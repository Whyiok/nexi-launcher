# Build the self-contained Windows installer.
# Usage:  .\build_installer.ps1
#
# Rebuilds nexi.exe first, then packs it (plus the icon and the launcher's
# round star icon) into a single NexiLauncher-Setup.exe. The setup installs
# per user, so it never needs administrator rights.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller "build/Nexi Launcher.spec" `
    --distpath _dist --workpath _build_tmp --noconfirm
if ($LASTEXITCODE -ne 0) { throw "Launcher build failed with exit code $LASTEXITCODE" }

# Absolute sources: the generated spec is written to _installer_tmp, and
# PyInstaller resolves relative --add-data paths against the spec's folder.
$root = $PSScriptRoot

python -m PyInstaller "installer/installer.py" `
    --name "NexiLauncher-Setup" `
    --onefile --windowed --noconfirm --clean `
    --icon "$root\assets\nexi.ico" `
    --version-file "$root\installer\version_info_setup.txt" `
    --specpath _installer_tmp `
    --add-data "$root\_dist\nexi.exe;." `
    --add-data "$root\assets\nexi.ico;." `
    --add-data "$root\webui\star_icon_rounded.png;." `
    --add-data "$root\installer\web;web" `
    --distpath _dist --workpath _installer_tmp
if ($LASTEXITCODE -ne 0) { throw "Installer build failed with exit code $LASTEXITCODE" }

Copy-Item "_dist/NexiLauncher-Setup.exe" "NexiLauncher-Setup.exe" -Force
Write-Host "Built: $PSScriptRoot\NexiLauncher-Setup.exe"
