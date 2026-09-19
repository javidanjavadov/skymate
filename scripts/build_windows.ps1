<#
  Builds SkyMate.exe reproducibly in a fresh virtual environment and writes its SHA-256 checksum.

    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Version 1.0.0

  No packers (UPX disabled) and no obfuscation. Sign the result afterwards only with a legitimate
  code-signing certificate:  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 dist\SkyMate.exe
#>
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = "Stop"
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 1.2.3" }

$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "build"
$dist = Join-Path $root "dist"
$venv = Join-Path $env:TEMP "skymate-build-venv"

foreach ($dir in @($build, $dist, $venv)) { if (Test-Path $dir) { Remove-Item -Recurse -Force $dir } }
New-Item -ItemType Directory -Force $build | Out-Null

Write-Host "==> Clean virtual environment"
py -3.11 -m venv $venv
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet --require-virtualenv -r (Join-Path $root "requirements-app.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

Write-Host "==> Icon and version resource"
& $py (Join-Path $PSScriptRoot "make_icon.py") (Join-Path $build "SkyMate.ico")
$parts = $Version.Split(".")
(Get-Content (Join-Path $PSScriptRoot "version_info.txt") -Raw) `
    -replace '\{VERSION\}', $Version -replace '\{V1\}', $parts[0] -replace '\{V2\}', $parts[1] -replace '\{V3\}', $parts[2] |
    Set-Content -Encoding utf8 (Join-Path $build "version_info.txt")
Set-Content -Encoding utf8 (Join-Path $build "app_version.py") "APP_VERSION = '$Version'"

Write-Host "==> PyInstaller"
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
    --name SkyMate `
    --icon (Join-Path $build "SkyMate.ico") `
    --version-file (Join-Path $build "version_info.txt") `
    --collect-data customtkinter `
    --paths $build `
    --distpath $dist --workpath (Join-Path $build "work") --specpath $build `
    (Join-Path $root "app.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $dist "SkyMate.exe"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
"$hash  SkyMate.exe" | Out-File -Encoding ascii (Join-Path $dist "SkyMate.exe.sha256")

Remove-Item -Recurse -Force $venv
Write-Host ""
Write-Host "Built  $exe"
Write-Host "SHA256 $hash"
