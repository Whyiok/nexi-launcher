# Build the onefile Windows executable.
# Usage:  .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller "build/Nexi Launcher.spec" `
    --distpath _dist --workpath _build_tmp --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Copy-Item "_dist/Nexi-Portable.exe" "Nexi-Portable.exe" -Force
Write-Host "Built: $PSScriptRoot\Nexi-Portable.exe"
