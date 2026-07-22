using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

const string VersionManifestUrl = "https://raw.githubusercontent.com/masterCoder1624/plugs/main/plugs-version.json";

var installDir = Path.Combine(
    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
    "Plugs"
);
var tempDir = Path.Combine(Path.GetTempPath(), "plugs-installer");
var zipPath = Path.Combine(tempDir, "plugs-windows.zip");

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
    using var http = new HttpClient();
    var manifest = await http.GetFromJsonAsync<VersionManifest>(VersionManifestUrl)
        ?? throw new InvalidOperationException("Could not read Plugs version manifest.");

    Console.WriteLine($"Latest version: {manifest.Version}");

    Console.WriteLine("[2/5] Downloading Plugs package...");
    await using (var download = await http.GetStreamAsync(manifest.DownloadUrl))
    await using (var file = File.Create(zipPath))
    {
        await download.CopyToAsync(file);
    }

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
        Console.WriteLine("Existing MongoDB Atlas config preserved.");
    }
    else
    {
        Console.WriteLine();
        Console.WriteLine("MongoDB Atlas is used for storage.");
        Console.Write("Paste MongoDB Atlas URI, or press Enter to add it later: ");
        var mongoUri = Console.ReadLine();

        if (string.IsNullOrWhiteSpace(mongoUri))
        {
            mongoUri = "PASTE_MONGODB_ATLAS_URI_HERE";
        }

        var config = new
        {
            backendHost = "127.0.0.1",
            backendPort = 8000,
            mongoUri
        };

        File.WriteAllText(
            configPath,
            JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true })
        );
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
    Console.Error.WriteLine(error.Message);
    Console.Error.WriteLine();
    Console.Error.WriteLine("If this keeps failing, install from the latest GitHub release manually.");
    Environment.Exit(1);
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
