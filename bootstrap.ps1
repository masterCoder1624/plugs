$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "====================================="
Write-Host "        Plugs Bootstrap Setup"
Write-Host "====================================="
Write-Host ""

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Command-Exists($command) {
    return $null -ne (Get-Command $command -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Show-Manual-Links {
    Write-Host ""
    Write-Host "Manual download links:"
    Write-Host "Node.js: https://nodejs.org/en/download/"
    Write-Host "Python:  https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "After installing manually, close PowerShell, reopen it in this folder, and run:"
    Write-Host "powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1"
    Write-Host ""
}

function Install-With-Winget($id, $name) {
    Write-Host "$name not found. Installing with winget..."

    winget install --id $id --exact --accept-source-agreements --accept-package-agreements

    Refresh-Path
}

Write-Host "[1/5] Checking Node.js..."

if (-not (Command-Exists node)) {
    Install-With-Winget "OpenJS.NodeJS.LTS" "Node.js"
} else {
    Write-Host "Node.js found."
    node --version
}

Refresh-Path

if (-not (Command-Exists node)) {
    Show-Manual-Links
    throw "Node.js was installed, but PATH did not refresh. Please reopen PowerShell and rerun bootstrap.ps1."
}

if (-not (Command-Exists npm)) {
    Show-Manual-Links
    throw "npm was not found. Please reinstall Node.js LTS and rerun bootstrap.ps1."
}

Write-Host "npm found."
npm --version

Write-Host ""
Write-Host "[2/5] Checking Python..."

if (Command-Exists python) {
    Write-Host "Python found."
    python --version
} elseif (Command-Exists py) {
    Write-Host "Python launcher found."
    py --version
} elseif (Command-Exists python3) {
    Write-Host "Python3 found."
    python3 --version
} else {
    Install-With-Winget "Python.Python.3.12" "Python"
}

Refresh-Path

if (-not (Command-Exists python) -and -not (Command-Exists py) -and -not (Command-Exists python3)) {
    Show-Manual-Links
    throw "Python was installed, but PATH did not refresh. Please reopen PowerShell and rerun bootstrap.ps1."
}

Write-Host ""
Write-Host "[3/5] Preparing MongoDB Atlas config..."

$configDir = Join-Path $Root "config"
$configFile = Join-Path $configDir "config.json"

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir | Out-Null
}

if (-not (Test-Path $configFile)) {
    Write-Host ""
    Write-Host "This project uses MongoDB Atlas."
    Write-Host "Paste MongoDB Atlas URI now, or press Enter to add it later."
    $mongoUri = Read-Host "MongoDB Atlas URI"

    if ([string]::IsNullOrWhiteSpace($mongoUri)) {
        $mongoUri = "PASTE_MONGODB_ATLAS_URI_HERE"
    }

    $config = @{
        backendHost = "127.0.0.1"
        backendPort = 8000
        mongoUri = $mongoUri
    } | ConvertTo-Json -Depth 5

    Set-Content -Path $configFile -Value $config
    Write-Host "Created config/config.json"
} else {
    Write-Host "Config already exists."
}

Write-Host ""
Write-Host "[4/5] Installing Plugs dependencies..."

npm install

Write-Host ""
Write-Host "[5/5] Starting Plugs..."
Write-Host ""

node launcher.js