# Build the Windows executables.
# Usage:  .\build.ps1
#
# Produces two builds of the same launcher:
#   _dist\Nexi-Portable.exe              single-file build for the portable download
#   _dist\NexiLauncher\NexiLauncher.exe  folder build used by the installer
#   _dist\NexiLauncher.zip               the folder build, updates installed copies
#
# If a code-signing certificate is configured (see sign.ps1), both executables
# are signed before packaging.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller "build/Nexi Launcher.spec" `
    --distpath _dist --workpath _build_tmp --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

python -m PyInstaller "build/Nexi App.spec" `
    --distpath _dist --workpath _build_tmp --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (folder build) failed with exit code $LASTEXITCODE" }

& "$PSScriptRoot\sign.ps1" -Path @(
    "$PSScriptRoot\_dist\Nexi-Portable.exe",
    "$PSScriptRoot\_dist\NexiLauncher\NexiLauncher.exe"
)

Copy-Item "_dist/Nexi-Portable.exe" "Nexi-Portable.exe" -Force

$zip = "$PSScriptRoot\_dist\NexiLauncher.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$PSScriptRoot\_dist\NexiLauncher\*" `
    -DestinationPath $zip -CompressionLevel Optimal

Write-Host "Built: $PSScriptRoot\Nexi-Portable.exe"
Write-Host "Built: $PSScriptRoot\_dist\NexiLauncher\NexiLauncher.exe"
Write-Host "Built: $zip"
