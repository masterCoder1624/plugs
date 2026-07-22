$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$BackendOutDir = Join-Path $DistDir "backend"

Write-Host ""
Write-Host "====================================="
Write-Host "        Building backend exe"
Write-Host "====================================="
Write-Host ""

Set-Location $BackendDir

python -m pip install -r requirements.txt
python -m pip install pyinstaller

if (Test-Path $BuildDir) {
    Remove-Item $BuildDir -Recurse -Force
}

if (-not (Test-Path $BackendOutDir)) {
    New-Item -ItemType Directory -Path $BackendOutDir -Force | Out-Null
}

python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --name plugs-backend `
    --distpath $BackendOutDir `
    --workpath (Join-Path $BuildDir "pyinstaller") `
    app.py

Write-Host ""
Write-Host "Backend exe created:"
Write-Host (Join-Path $BackendOutDir "plugs-backend.exe")
