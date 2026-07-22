# Plugs Compiled Release Build

This path is for the final-style distribution where the user receives only `PlugsSetup.exe`.

## Target User Flow

```text
User receives PlugsSetup.exe
↓
Setup downloads latest plugs-windows.zip from GitHub
↓
Setup extracts compiled app files into AppData
↓
Setup starts Plugs.exe
```

## Build Prerequisites

Install on the developer/build machine:

- Python 3.10+
- Flutter with Windows desktop support
- .NET SDK 8+
- PyInstaller
- Playwright browsers

## Build Backend Exe

```powershell
cd C:\Users\aadit\Desktop\plugs
powershell -ExecutionPolicy Bypass -File .\build-backend.ps1
```

Output:

```text
dist\backend\plugs-backend.exe
```

## Build Native Launcher Exe

The launcher starts `backend\plugs-backend.exe`, waits for `/health`, opens `flutter\Plugs.exe`, and kills the backend when Flutter closes.

```powershell
cd C:\Users\aadit\Desktop\plugs\native\PlugsLauncher
dotnet publish -c Release -r win-x64 --self-contained true
```

Output:

```text
native\PlugsLauncher\bin\Release\net8.0-windows\win-x64\publish\PlugsLauncher.exe
```

## Build Release Zip

```powershell
cd C:\Users\aadit\Desktop\plugs
powershell -ExecutionPolicy Bypass -File .\build-release.ps1
```

Output:

```text
dist\plugs\
dist\plugs-windows-YYYYMMDD-HHMMSS.zip
```

Upload the zip to GitHub Releases.

## Version Manifest

Copy:

```text
plugs-version.example.json
```

to:

```text
plugs-version.json
```

Then update:

```json
{
  "version": "0.1.0",
  "downloadUrl": "https://github.com/masterCoder1624/plugs/releases/download/v0.1.0/plugs-windows.zip",
  "sha256": "PUT_RELEASE_ZIP_SHA256_HERE",
  "notes": "Initial compiled desktop release."
}
```

The setup exe reads this file to know which version to download.

## Build Setup Exe

The setup project is currently configured for:

```text
https://raw.githubusercontent.com/masterCoder1624/plugs/main/plugs-version.json
```

If the repo default branch is `master` instead of `main`, update that URL in `native\PlugsSetup\Program.cs` before building.

Then build:

```powershell
cd C:\Users\aadit\Desktop\plugs\native\PlugsSetup
dotnet publish -c Release -r win-x64 --self-contained true
```

If your shell has permission issues with NuGet config, use the project-local config:

```powershell
dotnet publish -c Release -r win-x64 --self-contained true --configfile C:\Users\aadit\Desktop\plugs\NuGet.Config
```

Output:

```text
native\PlugsSetup\bin\Release\net8.0-windows\win-x64\publish\PlugsSetup.exe
```

This is the only file to send to the user.
