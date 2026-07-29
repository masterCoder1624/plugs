using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

const string VersionManifestUrl = "https://raw.githubusercontent.com/masterCoder1624/plugs/main/plugs-version.json";
const string LocalAiInstallerUrl = "https://ollama.com/download/OllamaSetup.exe";
const string LocalAiModel = "llama3.2:1b";
const int KeepOldVersionCount = 2;

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

var versionsDir = Path.Combine(installDir, "versions");
var userDataDir = Path.Combine(installDir, "user-data");
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
    Directory.CreateDirectory(installDir);
    Directory.CreateDirectory(versionsDir);
    Directory.CreateDirectory(userDataDir);
    Directory.CreateDirectory(Path.Combine(userDataDir, "logs"));
    Directory.CreateDirectory(Path.Combine(userDataDir, "cache"));
    Directory.CreateDirectory(tempDir);

    MigrateOldUserDataIfNeeded();

    Console.WriteLine("[1/6] Reading latest version...");
    using var http = new HttpClient { Timeout = TimeSpan.FromMinutes(30) };
    http.DefaultRequestHeaders.UserAgent.ParseAdd("PlugsSetup/1.0");
    var manifest = await ReadManifestAsync(http);

    Console.WriteLine($"Latest version: {manifest.Version}");

    var installedVersionPath = Path.Combine(installDir, "installed-version.json");
    var installedVersion = ReadInstalledVersion(installedVersionPath);
    var globalLauncherExe = Path.Combine(installDir, "Plugs.exe");

    if (File.Exists(globalLauncherExe) &&
        IsInstalledVersionCurrentOrNewer(installedVersion, manifest.Version))
    {
        Console.WriteLine($"Plugs {installedVersion} is already installed.");
        Console.WriteLine("Starting existing app...");

        StartApp(globalLauncherExe, installDir);
        return;
    }

    Console.WriteLine("[2/6] Downloading Plugs package...");
    if (File.Exists(zipPath))
    {
        File.Delete(zipPath);
    }

    await DownloadFileAsync(http, manifest.DownloadUrl, zipPath);

    if (!string.IsNullOrWhiteSpace(manifest.Sha256))
    {
        Console.WriteLine("[3/6] Verifying package...");
        var actualHash = ComputeSha256(zipPath);

        if (!actualHash.Equals(manifest.Sha256, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"Downloaded package hash did not match the release manifest. Expected {manifest.Sha256}, got {actualHash}."
            );
        }
    }
    else
    {
        Console.WriteLine("[3/6] No SHA256 provided, skipping verification.");
    }

    Console.WriteLine("[4/6] Installing latest version...");
    var versionDir = Path.Combine(versionsDir, manifest.Version);

    if (Directory.Exists(versionDir))
    {
        Directory.Delete(versionDir, recursive: true);
    }

    Directory.CreateDirectory(versionDir);
    ZipFile.ExtractToDirectory(zipPath, versionDir, overwriteFiles: true);
    File.Delete(zipPath);

    var appRoot = ResolveExtractedAppRoot(versionDir);
    var versionLauncherExe = Path.Combine(appRoot, "Plugs.exe");

    if (!File.Exists(versionLauncherExe))
    {
        throw new FileNotFoundException("Installed package did not contain Plugs.exe.", versionLauncherExe);
    }

    EnsureUserConfig(appRoot);

    File.Copy(versionLauncherExe, globalLauncherExe, overwrite: true);

    File.WriteAllText(
        Path.Combine(installDir, "current.txt"),
        manifest.Version
    );

    File.WriteAllText(
        installedVersionPath,
        $$"""
        {
          "version": "{{manifest.Version}}",
          "installedAt": "{{DateTime.UtcNow:O}}"
        }
        """
    );

    CleanupOldVersions(manifest.Version);

    Console.WriteLine("[5/6] Setting up Local AI Engine...");
    await EnsureLocalAiAsync(http, tempDir);

    Console.WriteLine("[6/6] Starting Plugs...");
    StartApp(globalLauncherExe, installDir);

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
    }

    Console.ReadLine();
    Environment.Exit(1);
}

string ResolveExtractedAppRoot(string versionDir)
{
    var nestedPlugsRoot = Path.Combine(versionDir, "plugs");

    if (Directory.Exists(nestedPlugsRoot))
    {
        return nestedPlugsRoot;
    }

    return versionDir;
}

void EnsureUserConfig(string appRoot)
{
    var userConfigPath = Path.Combine(userDataDir, "config.json");
    var bundledConfigPath = Path.Combine(appRoot, "config", "config.json");

    if (File.Exists(userConfigPath) &&
        !File.ReadAllText(userConfigPath).Contains("PASTE_MONGODB_ATLAS_URI_HERE", StringComparison.OrdinalIgnoreCase))
    {
        Console.WriteLine("Existing user config preserved.");
        return;
    }

    if (File.Exists(bundledConfigPath))
    {
        File.Copy(bundledConfigPath, userConfigPath, overwrite: true);
        Console.WriteLine("User config created from bundled config.");
        return;
    }

    File.WriteAllText(
        userConfigPath,
        """
        {
          "backendHost": "127.0.0.1",
          "backendPort": 8000,
          "mongoUri": "PASTE_MONGODB_ATLAS_URI_HERE"
        }
        """
    );

    Console.WriteLine("Default user config created.");
}

void MigrateOldUserDataIfNeeded()
{
    var userConfigPath = Path.Combine(userDataDir, "config.json");
    var userSessionPath = Path.Combine(userDataDir, "linkedin_session.json");

    var oldConfigPath = Path.Combine(installDir, "plugs", "config", "config.json");
    var oldSessionPath = Path.Combine(installDir, "plugs", "config", "linkedin_session.json");

    if (!File.Exists(userConfigPath) && File.Exists(oldConfigPath))
    {
        File.Copy(oldConfigPath, userConfigPath, overwrite: false);
        Console.WriteLine("Old config migrated.");
    }

    if (!File.Exists(userSessionPath) && File.Exists(oldSessionPath))
    {
        File.Copy(oldSessionPath, userSessionPath, overwrite: false);
        Console.WriteLine("Old LinkedIn session migrated.");
    }
}

void CleanupOldVersions(string activeVersion)
{
    try
    {
        var versionDirs = new DirectoryInfo(versionsDir)
            .GetDirectories()
            .Where(dir => !dir.Name.Equals(activeVersion, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(dir => dir.LastWriteTimeUtc)
            .Skip(KeepOldVersionCount - 1)
            .ToList();

        foreach (var dir in versionDirs)
        {
            try
            {
                dir.Delete(recursive: true);
            }
            catch
            {
            }
        }
    }
    catch
    {
    }
}

void StartApp(string launcherExe, string workingDirectory)
{
    Process.Start(new ProcessStartInfo
    {
        FileName = launcherExe,
        WorkingDirectory = workingDirectory,
        UseShellExecute = true,
    });
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

static bool IsInstalledVersionCurrentOrNewer(string? installedVersion, string latestVersion)
{
    if (string.IsNullOrWhiteSpace(installedVersion))
    {
        return false;
    }

    if (installedVersion.Equals(latestVersion, StringComparison.OrdinalIgnoreCase))
    {
        return true;
    }

    if (Version.TryParse(installedVersion, out var installed) &&
        Version.TryParse(latestVersion, out var latest))
    {
        return installed >= latest;
    }

    return false;
}

static string ComputeSha256(string filePath)
{
    using var sha = SHA256.Create();
    using var stream = File.OpenRead(filePath);
    return Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
}

static async Task EnsureLocalAiAsync(HttpClient http, string tempDir)
{
    var localAiExe = FindLocalAiExe();

    if (string.IsNullOrWhiteSpace(localAiExe))
    {
        Console.WriteLine("Installing Local AI Engine dependency...");

        var installerPath = Path.Combine(tempDir, "local-ai-engine-setup.exe");
        await DownloadFileAsync(http, LocalAiInstallerUrl, installerPath);

        await RunHiddenAsync(
            installerPath,
            "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART",
            TimeSpan.FromMinutes(10)
        );

        localAiExe = FindLocalAiExe();
    }

    if (string.IsNullOrWhiteSpace(localAiExe))
    {
        Console.WriteLine("Local AI Engine could not be installed automatically. Chatbot may be unavailable.");
        return;
    }

    await EnsureLocalAiServerAsync(localAiExe);

    Console.WriteLine("Preparing chatbot model. This may take time on first install...");
    await EnsureLocalAiModelAsync(localAiExe, LocalAiModel);
}

static string? FindLocalAiExe()
{
    var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

    var knownPaths = new[]
    {
        Path.Combine(localAppData, "Programs", "Ollama", "ollama.exe"),
        Path.Combine(localAppData, "Ollama", "ollama.exe"),
    };

    foreach (var path in knownPaths)
    {
        if (File.Exists(path))
        {
            return path;
        }
    }

    var pathValue = Environment.GetEnvironmentVariable("PATH") ?? "";

    foreach (var dir in pathValue.Split(Path.PathSeparator))
    {
        try
        {
            var candidate = Path.Combine(dir.Trim(), "ollama.exe");
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }
        catch
        {
        }
    }

    return null;
}

static async Task EnsureLocalAiServerAsync(string localAiExe)
{
    if (await IsLocalAiServerRunningAsync())
    {
        return;
    }

    try
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = localAiExe,
            Arguments = "serve",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        });
    }
    catch
    {
    }

    var startedAt = DateTime.UtcNow;

    while (DateTime.UtcNow - startedAt < TimeSpan.FromSeconds(60))
    {
        if (await IsLocalAiServerRunningAsync())
        {
            return;
        }

        await Task.Delay(1000);
    }

    Console.WriteLine("Local AI Engine did not start yet. Chatbot may become available after app launch.");
}

static async Task<bool> IsLocalAiServerRunningAsync()
{
    try
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
        using var response = await client.GetAsync("http://127.0.0.1:11434/api/tags");
        return response.IsSuccessStatusCode;
    }
    catch
    {
        return false;
    }
}

static async Task EnsureLocalAiModelAsync(string localAiExe, string model)
{
    var listResult = await RunHiddenCaptureAsync(
        localAiExe,
        "list",
        TimeSpan.FromMinutes(2)
    );

    if (listResult.Contains(model, StringComparison.OrdinalIgnoreCase))
    {
        Console.WriteLine("Chatbot model already available.");
        return;
    }

    Console.WriteLine("Downloading chatbot model dependency...");
    await RunHiddenAsync(
        localAiExe,
        $"pull {model}",
        TimeSpan.FromMinutes(60)
    );
}

static async Task RunHiddenAsync(string fileName, string arguments, TimeSpan timeout)
{
    using var process = Process.Start(new ProcessStartInfo
    {
        FileName = fileName,
        Arguments = arguments,
        UseShellExecute = false,
        CreateNoWindow = true,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
    }) ?? throw new InvalidOperationException($"Could not start {fileName}");

    using var cancellation = new CancellationTokenSource(timeout);

    try
    {
        await process.WaitForExitAsync(cancellation.Token);
    }
    catch (OperationCanceledException)
    {
        try
        {
            process.Kill(entireProcessTree: true);
        }
        catch
        {
        }

        throw new TimeoutException($"{fileName} timed out.");
    }
}

static async Task<string> RunHiddenCaptureAsync(string fileName, string arguments, TimeSpan timeout)
{
    using var process = Process.Start(new ProcessStartInfo
    {
        FileName = fileName,
        Arguments = arguments,
        UseShellExecute = false,
        CreateNoWindow = true,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
    }) ?? throw new InvalidOperationException($"Could not start {fileName}");

    using var cancellation = new CancellationTokenSource(timeout);

    var outputTask = process.StandardOutput.ReadToEndAsync();
    var errorTask = process.StandardError.ReadToEndAsync();

    try
    {
        await process.WaitForExitAsync(cancellation.Token);
    }
    catch (OperationCanceledException)
    {
        try
        {
            process.Kill(entireProcessTree: true);
        }
        catch
        {
        }

        return "";
    }

    var output = await outputTask;
    var error = await errorTask;

    return output + Environment.NewLine + error;
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