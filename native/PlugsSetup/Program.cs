using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

const string VersionManifestUrl = "https://raw.githubusercontent.com/masterCoder1624/plugs/main/plugs-version.json";
const string BundledManifestJson = """
{
  "version": "0.1.0",
  "downloadUrl": "https://github.com/masterCoder1624/plugs/releases/download/v0.1.0/plugs-windows.zip",
  "sha256": "EBD92FA8774640E75B1A660F4D15F4788958979D314C7EABD489922CBE1E203C",
  "notes": "Initial compiled desktop release."
}
""";

var installDir = Path.Combine(
    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
    "Plugs"
);
var tempDir = Path.Combine(Path.GetTempPath(), "plugs-installer");
var zipPath = Path.Combine(tempDir, "plugs-windows.zip");
var setupLogPath = Path.Combine(tempDir, "setup-error.log");

Console.Title = "Plugs Setup";
Console.WriteLine();
Console.WriteLine("=====================================");
Console.WriteLine("        Plugs Setup");
Console.WriteLine("=====================================");
Console.WriteLine();

try
{
    Directory.CreateDirectory(tempDir);

    var previousAppRoot = Path.Combine(installDir, "plugs");
    var previousConfigPath = Path.Combine(previousAppRoot, "config", "config.json");
    var previousConfig = File.Exists(previousConfigPath)
        ? File.ReadAllText(previousConfigPath)
        : null;

    Console.WriteLine("[1/5] Reading latest version...");
    using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
    http.DefaultRequestHeaders.UserAgent.ParseAdd("PlugsSetup/0.1.0");
    var manifest = await ReadManifestAsync(http);

    Console.WriteLine($"Latest version: {manifest.Version}");
    var installedVersionPath = Path.Combine(installDir, "installed-version.json");
    var installedVersion = ReadInstalledVersion(installedVersionPath);
    var existingLauncherExe = Path.Combine(installDir, "plugs", "Plugs.exe");

    if (File.Exists(existingLauncherExe) &&
        string.Equals(installedVersion, manifest.Version, StringComparison.OrdinalIgnoreCase))
    {
        Console.WriteLine($"Plugs {installedVersion} is already installed.");
        Console.WriteLine("Starting existing app...");

        Process.Start(new ProcessStartInfo
        {
            FileName = existingLauncherExe,
            WorkingDirectory = Path.GetDirectoryName(existingLauncherExe)!,
            UseShellExecute = true,
        });

        return;
    }

    Console.WriteLine("[2/5] Downloading Plugs package...");
    await DownloadFileAsync(http, manifest.DownloadUrl, zipPath);

    if (!string.IsNullOrWhiteSpace(manifest.Sha256))
    {
        Console.WriteLine("[3/5] Verifying package...");
        var actualHash = ComputeSha256(zipPath);
        if (!actualHash.Equals(manifest.Sha256, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Downloaded package hash did not match the release manifest.");
        }
    }
    else
    {
        Console.WriteLine("[3/5] No SHA256 provided, skipping verification.");
    }

    Console.WriteLine("[4/5] Installing files...");
    if (Directory.Exists(installDir))
    {
        Directory.Delete(installDir, recursive: true);
    }

    Directory.CreateDirectory(installDir);
    ZipFile.ExtractToDirectory(zipPath, installDir, overwriteFiles: true);
    File.Delete(zipPath);

    var appRoot = Path.Combine(installDir, "plugs");
    var launcherExe = Path.Combine(appRoot, "Plugs.exe");

    if (!File.Exists(launcherExe))
    {
        throw new FileNotFoundException("Installed package did not contain Plugs.exe.", launcherExe);
    }

    var configDir = Path.Combine(appRoot, "config");
    var configPath = Path.Combine(configDir, "config.json");
    Directory.CreateDirectory(configDir);

    if (!string.IsNullOrWhiteSpace(previousConfig) &&
        !previousConfig.Contains("PASTE_MONGODB_ATLAS_URI_HERE", StringComparison.OrdinalIgnoreCase))
    {
        File.WriteAllText(configPath, previousConfig);
        Console.WriteLine("Existing config preserved.");
    }
    else if (File.Exists(configPath) &&
            !File.ReadAllText(configPath).Contains("PASTE_MONGODB_ATLAS_URI_HERE", StringComparison.OrdinalIgnoreCase))
    {
        Console.WriteLine("Bundled config found.");
    }
    else
    {
        Console.WriteLine("Config created from bundled package.");
    }

    File.WriteAllText(
        Path.Combine(installDir, "installed-version.json"),
        $$"""
        {
          "version": "{{manifest.Version}}",
          "installedAt": "{{DateTime.UtcNow:O}}"
        }
        """
    );

    Console.WriteLine("[5/5] Starting Plugs...");
    Process.Start(new ProcessStartInfo
    {
        FileName = launcherExe,
        WorkingDirectory = appRoot,
        UseShellExecute = true,
    });

    Console.WriteLine("Plugs installed successfully.");
}
catch (Exception error)
{
    Console.Error.WriteLine();
    Console.Error.WriteLine("Plugs setup failed:");
    Console.Error.WriteLine(error.GetType().Name);
    Console.Error.WriteLine(error.Message);
    Console.Error.WriteLine();
    Console.Error.WriteLine($"Error log: {setupLogPath}");
    Console.Error.WriteLine("If this keeps failing, install from the latest GitHub release manually.");
    Console.Error.WriteLine();
    Console.Error.WriteLine("Press Enter to close this window.");

    try
    {
        Directory.CreateDirectory(tempDir);
        File.WriteAllText(setupLogPath, error.ToString());
    }
    catch
    {
        // Best-effort logging only.
    }

    Console.ReadLine();
    Environment.Exit(1);
}

static async Task<VersionManifest> ReadManifestAsync(HttpClient http)
{
    try
    {
        var manifest = await http.GetFromJsonAsync<VersionManifest>(VersionManifestUrl)
            ?? throw new InvalidOperationException("Could not read Plugs version manifest.");

        if (string.IsNullOrWhiteSpace(manifest.DownloadUrl))
        {
            throw new InvalidOperationException("Plugs version manifest did not contain a download URL.");
        }

        return manifest;
    }
    catch (Exception error)
    {
        Console.WriteLine($"Could not read latest version online: {error.Message}");
        Console.WriteLine("Using bundled release information instead.");

        return JsonSerializer.Deserialize<VersionManifest>(BundledManifestJson)
            ?? throw new InvalidOperationException("Bundled Plugs version manifest is invalid.");
    }
}

static async Task DownloadFileAsync(HttpClient http, string url, string destinationPath)
{
    using var response = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead);
    response.EnsureSuccessStatusCode();

    var totalBytes = response.Content.Headers.ContentLength;
    await using var download = await response.Content.ReadAsStreamAsync();
    await using var file = File.Create(destinationPath);

    var buffer = new byte[1024 * 128];
    long copiedBytes = 0;
    var lastProgressAt = DateTimeOffset.MinValue;

    while (true)
    {
        var read = await download.ReadAsync(buffer);
        if (read == 0)
        {
            break;
        }

        await file.WriteAsync(buffer.AsMemory(0, read));
        copiedBytes += read;

        if (DateTimeOffset.UtcNow - lastProgressAt > TimeSpan.FromMilliseconds(750))
        {
            lastProgressAt = DateTimeOffset.UtcNow;
            if (totalBytes.HasValue)
            {
                Console.Write($"\rDownloaded {copiedBytes / 1024 / 1024} MB of {totalBytes.Value / 1024 / 1024} MB...");
            }
            else
            {
                Console.Write($"\rDownloaded {copiedBytes / 1024 / 1024} MB...");
            }
        }
    }

    Console.WriteLine();
}

static string? ReadInstalledVersion(string installedVersionPath)
{
    try
    {
        if (!File.Exists(installedVersionPath))
        {
            return null;
        }

        using var document = JsonDocument.Parse(File.ReadAllText(installedVersionPath));
        if (document.RootElement.TryGetProperty("version", out var version))
        {
            return version.GetString();
        }

        return null;
    }
    catch
    {
        return null;
    }
}

static string ComputeSha256(string filePath)
{
    using var sha = SHA256.Create();
    using var stream = File.OpenRead(filePath);
    return Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
}

internal sealed class VersionManifest
{
    [JsonPropertyName("version")]
    public string Version { get; set; } = "";

    [JsonPropertyName("downloadUrl")]
    public string DownloadUrl { get; set; } = "";

    [JsonPropertyName("sha256")]
    public string Sha256 { get; set; } = "";

    [JsonPropertyName("notes")]
    public string Notes { get; set; } = "";
}
