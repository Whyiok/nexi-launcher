# Sign built executables with an Authenticode certificate.
#
# Optional: without a configured certificate the build stays unsigned (exactly
# as before) and only prints a note. Configure one of these before building:
#
#   $env:NEXI_SIGN_PFX = "C:\certs\nexi.pfx"
#   $env:NEXI_SIGN_PASSWORD = "pfx-password"
#
# or a certificate already installed in the user's store:
#
#   $env:NEXI_SIGN_THUMBPRINT = "AB12CD34..."
#
# Set NEXI_SIGN_REQUIRED=1 to make a missing signtool/certificate a build error.
param([Parameter(Mandatory = $true)][string[]]$Path)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin",
               "$env:ProgramFiles\Windows Kits\10\bin")
    $found = @()
    foreach ($root in $roots) {
        if ($root -and (Test-Path $root)) {
            $found += Get-ChildItem -Path $root -Filter signtool.exe -Recurse `
                -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' }
        }
    }
    if ($found.Count -gt 0) {
        return ($found | Sort-Object FullName -Descending |
                Select-Object -First 1).FullName
    }
    return $null
}

$hasPfx = [bool]$env:NEXI_SIGN_PFX
$hasThumbprint = [bool]$env:NEXI_SIGN_THUMBPRINT
if (-not ($hasPfx -or $hasThumbprint)) {
    Write-Host "sign: no certificate configured; binaries stay unsigned."
    if ($env:NEXI_SIGN_REQUIRED -eq "1") {
        throw "NEXI_SIGN_REQUIRED=1 but no signing certificate is configured."
    }
    exit 0
}

$signtool = Find-SignTool
if (-not $signtool) {
    if ($env:NEXI_SIGN_REQUIRED -eq "1") {
        throw "signtool.exe was not found; install the Windows SDK signing tools."
    }
    Write-Host "sign: signtool.exe was not found; binaries stay unsigned."
    exit 0
}

$signArgs = @("sign", "/fd", "sha256", "/td", "sha256",
              "/tr", "http://timestamp.digicert.com")
if ($hasPfx) {
    $signArgs += @("/f", $env:NEXI_SIGN_PFX)
    if ($env:NEXI_SIGN_PASSWORD) {
        $signArgs += @("/p", $env:NEXI_SIGN_PASSWORD)
    }
} else {
    $signArgs += @("/sha1", $env:NEXI_SIGN_THUMBPRINT)
}

foreach ($item in $Path) {
    if (-not (Test-Path $item)) { throw "sign: $item does not exist." }
    & $signtool @signArgs $item
    if ($LASTEXITCODE -ne 0) { throw "sign: signtool failed for $item" }
    & $signtool verify /pa /q $item
    if ($LASTEXITCODE -ne 0) { throw "sign: verification failed for $item" }
    Write-Host "sign: signed $item"
}
