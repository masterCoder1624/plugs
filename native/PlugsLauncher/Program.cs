using System.Diagnostics;
using System.Net;

const string BackendHost = "127.0.0.1";
const int BackendPort = 8000;

var launcherDir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
var appRoot = ResolveAppRoot(launcherDir);
var installRoot = ResolveInstallRoot(launcherDir, appRoot);
var userDataDir = Path.Combine(installRoot, "user-data");

var backendExe = Path.Combine(appRoot, "backend", "plugs-backend.exe");
var flutterExe = Path.Combine(appRoot, "flutter", "Plugs.exe");
var browsersDir = Path.Combine(appRoot, "browsers");
var healthUrl = $"http://{BackendHost}:{BackendPort}/health";

Process? backendProcess = null;
Process? flutterProcess = null;
var shuttingDown = false;

try
{
    Directory.CreateDirectory(userDataDir);
    Directory.CreateDirectory(Path.Combine(userDataDir, "logs"));
    Directory.CreateDirectory(Path.Combine(userDataDir, "cache"));

    if (!File.Exists(backendExe))
    {
        throw new FileNotFoundException("Backend executable was not found.", backendExe);
    }

    if (!File.Exists(flutterExe))
    {
        throw new FileNotFoundException("Flutter executable was not found.", flutterExe);
    }

    backendProcess = StartProcess(backendExe, Path.GetDirectoryName(backendExe)!, configureEnvironment: true);

    await WaitForHealthAsync(healthUrl, TimeSpan.FromSeconds(45));

    flutterProcess = StartProcess(flutterExe, Path.GetDirectoryName(flutterExe)!, configureEnvironment: false);
    flutterProcess.WaitForExit();

    Shutdown(flutterProcess.ExitCode);
}
catch (Exception error)
{
    MessageBox(error.Message);
    Shutdown(1);
}

string ResolveAppRoot(string launcherDirectory)
{
    var currentPath = Path.Combine(launcherDirectory, "current.txt");
    var versionsDir = Path.Combine(launcherDirectory, "versions");

    if (File.Exists(currentPath) && Directory.Exists(versionsDir))
    {
        var version = File.ReadAllText(currentPath).Trim();
        var versionRoot = Path.Combine(versionsDir, version);
        var nestedPlugsRoot = Path.Combine(versionRoot, "plugs");

        if (Directory.Exists(nestedPlugsRoot))
        {
            return nestedPlugsRoot;
        }

        return versionRoot;
    }

    return launcherDirectory;
}

string ResolveInstallRoot(string launcherDirectory, string resolvedAppRoot)
{
    if (File.Exists(Path.Combine(launcherDirectory, "current.txt")))
    {
        return launcherDirectory;
    }

    var current = new DirectoryInfo(resolvedAppRoot);

    while (current is not null)
    {
        if (Directory.Exists(Path.Combine(current.FullName, "user-data")) ||
            Directory.Exists(Path.Combine(current.FullName, "versions")) ||
            File.Exists(Path.Combine(current.FullName, "current.txt")))
        {
            return current.FullName;
        }

        current = current.Parent;
    }

    return launcherDirectory;
}

Process StartProcess(string fileName, string workingDirectory, bool configureEnvironment)
{
    var startInfo = new ProcessStartInfo
    {
        FileName = fileName,
        WorkingDirectory = workingDirectory,
        UseShellExecute = false,
        CreateNoWindow = configureEnvironment,
        RedirectStandardOutput = configureEnvironment,
        RedirectStandardError = configureEnvironment,
    };

    if (configureEnvironment && Directory.Exists(browsersDir))
    {
        startInfo.Environment["PLAYWRIGHT_BROWSERS_PATH"] = browsersDir;
    }

    startInfo.Environment["PLUGS_BACKEND_HOST"] = BackendHost;
    startInfo.Environment["PLUGS_BACKEND_PORT"] = BackendPort.ToString();

    startInfo.Environment["PLUGS_INSTALL_DIR"] = installRoot;
    startInfo.Environment["PLUGS_USER_DATA_DIR"] = userDataDir;
    startInfo.Environment["PLUGS_CONFIG_FILE"] = Path.Combine(userDataDir, "config.json");
    startInfo.Environment["PLUGS_LINKEDIN_SESSION_FILE"] = Path.Combine(userDataDir, "linkedin_session.json");
    startInfo.Environment["PLUGS_LOGS_DIR"] = Path.Combine(userDataDir, "logs");

    return Process.Start(startInfo)
        ?? throw new InvalidOperationException($"Could not start {fileName}");
}

async Task WaitForHealthAsync(string url, TimeSpan timeout)
{
    using var client = new HttpClient();
    var startedAt = DateTime.UtcNow;

    while (DateTime.UtcNow - startedAt < timeout)
    {
        try
        {
            using var response = await client.GetAsync(url);
            if (response.StatusCode == HttpStatusCode.OK)
            {
                return;
            }
        }
        catch
        {
        }

        await Task.Delay(500);
    }

    throw new TimeoutException("Backend did not become ready in time.");
}

void Shutdown(int exitCode)
{
    if (shuttingDown)
    {
        return;
    }

    shuttingDown = true;

    TryKill(flutterProcess);
    TryKill(backendProcess);

    Environment.Exit(exitCode);
}

void TryKill(Process? process)
{
    try
    {
        if (process is { HasExited: false })
        {
            process.Kill(entireProcessTree: true);
        }
    }
    catch
    {
    }
}

void MessageBox(string message)
{
    try
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell",
            Arguments = $"-NoProfile -Command \"Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('{Escape(message)}', 'Plugs')\"",
            UseShellExecute = false,
            CreateNoWindow = true,
        });
    }
    catch
    {
        Console.Error.WriteLine(message);
    }
}

string Escape(string value) => value.Replace("'", "''");