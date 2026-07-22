$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseRoot = Join-Path $Root "dist\plugs"
$ReleaseZip = Join-Path $Root ("dist\plugs-windows-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".zip")

Write-Host ""
Write-Host "====================================="
Write-Host "        Building Plugs release"
Write-Host "====================================="
Write-Host ""

if (Test-Path $ReleaseRoot) {
    Remove-Item $ReleaseRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot "backend") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot "config") -Force | Out-Null

Write-Host "[1/5] Building backend exe..."
& (Join-Path $Root "build-backend.ps1")

Copy-Item `
    -LiteralPath (Join-Path $Root "dist\backend\plugs-backend.exe") `
    -Destination (Join-Path $ReleaseRoot "backend\plugs-backend.exe") `
    -Force

Write-Host "[2/5] Building Flutter Windows app..."
Set-Location (Join-Path $Root "flutter_app")
flutter build windows --release

Write-Host "[3/5] Copying Flutter runtime bundle..."
$FlutterRelease = Join-Path $Root "flutter_app\build\windows\x64\runner\Release"
Copy-Item -LiteralPath $FlutterRelease -Destination (Join-Path $ReleaseRoot "flutter") -Recurse -Force

$GeneratedExe = Join-Path $ReleaseRoot "flutter\flutter_app.exe"
$FinalExe = Join-Path $ReleaseRoot "flutter\Plugs.exe"
if (Test-Path $GeneratedExe) {
    Move-Item -LiteralPath $GeneratedExe -Destination $FinalExe -Force
}

Write-Host "[4/5] Copying bundled Playwright browsers when available..."
$LocalBrowsers = Join-Path $env:LOCALAPPDATA "ms-playwright"
if (Test-Path $LocalBrowsers) {
    $BrowserDest = Join-Path $ReleaseRoot "browsers"
    New-Item -ItemType Directory -Path $BrowserDest -Force | Out-Null

    $Chromium = Get-ChildItem -LiteralPath $LocalBrowsers -Directory |
        Where-Object { $_.Name -match '^chromium-\d+$' } |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if (-not $Chromium) {
        throw "No bundled Chromium browser found in $LocalBrowsers. Run: python -m playwright install chromium"
    }

    Copy-Item -LiteralPath $Chromium.FullName -Destination $BrowserDest -Recurse -Force

    $LinksDir = Join-Path $LocalBrowsers ".links"
    if (Test-Path $LinksDir) {
        Copy-Item -LiteralPath $LinksDir -Destination $BrowserDest -Recurse -Force
    }
} else {
    Write-Host "No local Playwright browsers found at $LocalBrowsers"
    Write-Host "Run: python -m playwright install chromium"
}

$ConfigTemplate = @{
    backendHost = "127.0.0.1"
    backendPort = 8000
    mongoUri = "PASTE_MONGODB_ATLAS_URI_HERE"
} | ConvertTo-Json -Depth 5
Set-Content -Path (Join-Path $ReleaseRoot "config\config.json") -Value $ConfigTemplate

if (Test-Path (Join-Path $Root "native\PlugsLauncher\bin\Release\net8.0-windows\win-x64\publish\PlugsLauncher.exe")) {
    Copy-Item `
        -LiteralPath (Join-Path $Root "native\PlugsLauncher\bin\Release\net8.0-windows\win-x64\publish\PlugsLauncher.exe") `
        -Destination (Join-Path $ReleaseRoot "Plugs.exe") `
        -Force
} else {
    Write-Host "Native launcher exe not found yet. Build native\PlugsLauncher before final packaging."
}

if (Test-Path (Join-Path $Root "native\PlugsSetup\bin\Release\net8.0-windows\win-x64\publish\PlugsSetup.exe")) {
    Copy-Item `
        -LiteralPath (Join-Path $Root "native\PlugsSetup\bin\Release\net8.0-windows\win-x64\publish\PlugsSetup.exe") `
        -Destination (Join-Path $Root "dist\PlugsSetup.exe") `
        -Force
}

Write-Host "[5/5] Creating release zip..."
if (-not (Test-Path (Join-Path $Root "dist"))) {
    New-Item -ItemType Directory -Path (Join-Path $Root "dist") -Force | Out-Null
}

Compress-Archive -LiteralPath $ReleaseRoot -DestinationPath $ReleaseZip -Force

Write-Host ""
Write-Host "Release folder:"
Write-Host $ReleaseRoot
Write-Host ""
Write-Host "Release zip:"
Write-Host $ReleaseZip
