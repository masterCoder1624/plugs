using System.Diagnostics;
using System.Net;

const string BackendHost = "127.0.0.1";
const int BackendPort = 8000;

var appRoot = AppContext.BaseDirectory;
var backendExe = Path.Combine(appRoot, "backend", "plugs-backend.exe");
var flutterExe = Path.Combine(appRoot, "flutter", "Plugs.exe");
var browsersDir = Path.Combine(appRoot, "browsers");
var healthUrl = $"http://{BackendHost}:{BackendPort}/health";

Process? backendProcess = null;
Process? flutterProcess = null;
var shuttingDown = false;

try
{
    if (!File.Exists(backendExe))
    {
        throw new FileNotFoundException("Backend executable was not found.", backendExe);
    }

    if (!File.Exists(flutterExe))
    {
        throw new FileNotFoundException("Flutter executable was not found.", flutterExe);
    }

    backendProcess = StartProcess(backendExe, Path.GetDirectoryName(backendExe)!, configureEnvironment: true);

    await WaitForHealthAsync(healthUrl, TimeSpan.FromSeconds(30));

    flutterProcess = StartProcess(flutterExe, Path.GetDirectoryName(flutterExe)!, configureEnvironment: false);
    flutterProcess.WaitForExit();

    Shutdown(flutterProcess.ExitCode);
}
catch (Exception error)
{
    MessageBox(error.Message);
    Shutdown(1);
}

Process StartProcess(string fileName, string workingDirectory, bool configureEnvironment)
{
    var startInfo = new ProcessStartInfo
    {
        FileName = fileName,
        WorkingDirectory = workingDirectory,
        UseShellExecute = false,
    };

    if (configureEnvironment && Directory.Exists(browsersDir))
    {
        startInfo.Environment["PLAYWRIGHT_BROWSERS_PATH"] = browsersDir;
    }

    startInfo.Environment["PLUGS_BACKEND_HOST"] = BackendHost;
    startInfo.Environment["PLUGS_BACKEND_PORT"] = BackendPort.ToString();

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
