# Plugs

Plugs is a Windows desktop prototype that launches a Flutter UI with a compiled FastAPI backend.

## Current Distribution Plan

End users should receive only:

```text
PlugsSetup.exe
```

`PlugsSetup.exe` downloads the latest compiled app package from GitHub Releases, verifies the package hash, installs it under `%LOCALAPPDATA%\Plugs`, asks for the MongoDB Atlas URI if needed, and starts the app.

## GitHub Release Files

For release `v0.1.0`, upload:

```text
plugs-windows.zip
PlugsSetup.exe
```

The repo root must contain:

```text
plugs-version.json
```

## MongoDB Atlas URI

Do not commit the real MongoDB Atlas URI.

The setup exe asks for it during install. If skipped, paste it later in:

```text
%LOCALAPPDATA%\Plugs\plugs\config\config.json
```

For local developer testing:

```text
C:\Users\aadit\Desktop\plugs\dist\plugs\config\config.json
```

## Developer Build

Build backend exe:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-backend.ps1
```

Build native launcher:

```powershell
cd native\PlugsLauncher
dotnet publish -c Release -r win-x64 --self-contained true
```

Build setup exe:

```powershell
cd native\PlugsSetup
dotnet publish -c Release -r win-x64 --self-contained true
```

Build release zip:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-release.ps1
```
