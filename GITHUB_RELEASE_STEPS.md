# GitHub Release Steps

Repository:

```text
https://github.com/masterCoder1624/plugs
```

## Files Ready To Upload

Use these local files:

```text
C:\Users\aadit\Desktop\plugs\dist\github-release-assets\PlugsSetup.exe
C:\Users\aadit\Desktop\plugs\dist\github-release-assets\plugs-windows.zip
C:\Users\aadit\Desktop\plugs\dist\github-release-assets\plugs-version.json
```

## Release Tag

Create this GitHub Release tag:

```text
v0.1.0
```

Upload this file as the release asset:

```text
plugs-windows.zip
```

`PlugsSetup.exe` can also be uploaded to the same release so your lead can download one file.

## Required Repo File

Commit this file to the root of the GitHub repo:

```text
plugs-version.json
```

It currently points to:

```text
https://github.com/masterCoder1624/plugs/releases/download/v0.1.0/plugs-windows.zip
```

The setup exe reads:

```text
https://raw.githubusercontent.com/masterCoder1624/plugs/main/plugs-version.json
```

If the GitHub repo default branch is `master` instead of `main`, update `native\PlugsSetup\Program.cs` and rebuild `PlugsSetup.exe`.

## MongoDB Atlas URI

Do not commit the real MongoDB Atlas URI.

Safe options:

1. The setup exe asks for the URI during install.
2. If skipped during install, paste it later into:

```text
%LOCALAPPDATA%\Plugs\plugs\config\config.json
```

The field is:

```json
{
  "mongoUri": "PASTE_MONGODB_ATLAS_URI_HERE"
}
```

For local developer testing before upload, paste it here:

```text
C:\Users\aadit\Desktop\plugs\dist\plugs\config\config.json
```

## User Flow

The user receives:

```text
PlugsSetup.exe
```

Then:

```text
User runs PlugsSetup.exe
↓
Setup downloads plugs-windows.zip from GitHub
↓
Setup verifies SHA256
↓
Setup extracts the compiled app to AppData
↓
Setup asks for MongoDB Atlas URI if needed
↓
Setup starts Plugs
```
