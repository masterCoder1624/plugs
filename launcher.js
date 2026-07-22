const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const fs = require("fs");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8000;
const HEALTH_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}/health`;

const backendDir = path.join(__dirname, "backend");
const backendExe = path.join(backendDir, "plugs-backend.exe");
const flutterExe = path.join(__dirname, "flutter", "Plugs.exe");
const bundledBrowsersDir = path.join(__dirname, "browsers");

let backendProcess = null;
let flutterProcess = null;
let shuttingDown = false;

function waitForHealth(timeoutMs = 30000) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    function check() {
      const req = http.get(HEALTH_URL, (res) => {
        if (res.statusCode === 200) {
          res.resume();
          resolve();
          return;
        }

        res.resume();
        retry();
      });

      req.on("error", retry);

      req.setTimeout(2000, () => {
        req.destroy();
        retry();
      });
    }

    function retry() {
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error(`Backend did not become ready within ${timeoutMs / 1000}s`));
        return;
      }

      setTimeout(check, 500);
    }

    check();
  });
}

function stopProcess(processRef, name) {
  if (!processRef || processRef.killed) {
    return;
  }

  console.log(`Stopping ${name}...`);
  processRef.kill();
}

function shutdown(exitCode = 0) {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;

  stopProcess(flutterProcess, "Flutter app");
  stopProcess(backendProcess, "backend");

  setTimeout(() => {
    process.exit(exitCode);
  }, 500);
}

function launchBackend() {
  console.log("Starting Plugs backend...");

  const env = { ...process.env };
  if (fs.existsSync(bundledBrowsersDir)) {
    env.PLAYWRIGHT_BROWSERS_PATH = bundledBrowsersDir;
  }

  if (fs.existsSync(backendExe)) {
    backendProcess = spawn(backendExe, [], {
      cwd: backendDir,
      stdio: "inherit",
      env,
    });
  } else {
    backendProcess = spawn(
      "python",
      ["-m", "uvicorn", "app:app", "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)],
      {
        cwd: backendDir,
        stdio: "inherit",
        env,
      }
    );
  }

  backendProcess.on("error", (error) => {
    console.error("Failed to start backend:", error.message);
    shutdown(1);
  });

  backendProcess.on("exit", (code) => {
    console.log(`Backend exited with code ${code}`);

    if (!shuttingDown) {
      console.error("Backend closed before Flutter exited.");
      shutdown(code ?? 1);
    }
  });
}

function launchFlutter() {
  if (!fs.existsSync(flutterExe)) {
    throw new Error(`Flutter app not found at: ${flutterExe}`);
  }

  console.log("Launching Flutter app...");

  flutterProcess = spawn(flutterExe, [], {
    cwd: path.dirname(flutterExe),
    stdio: "inherit",
  });

  flutterProcess.on("error", (error) => {
    console.error("Failed to launch Flutter:", error.message);
    shutdown(1);
  });

  flutterProcess.on("exit", (code) => {
    console.log(`Flutter exited with code ${code}`);
    shutdown(code ?? 0);
  });
}

async function main() {
  launchBackend();

  try {
    console.log("Waiting for backend health check...");
    await waitForHealth();

    console.log("Backend is ready.");
    launchFlutter();
  } catch (error) {
    console.error(error.message);
    shutdown(1);
  }
}

process.on("SIGINT", () => {
  shutdown(0);
});

process.on("SIGTERM", () => {
  shutdown(0);
});

main();
