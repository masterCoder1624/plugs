const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const rootDir = __dirname;
const backendDir = path.join(rootDir, "backend");
const requirementsFile = path.join(backendDir, "requirements.txt");

const configDir = path.join(rootDir, "config");
const logsDir = path.join(rootDir, "logs");
const flutterDir = path.join(rootDir, "flutter");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    shell: true,
    ...options,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with exit code ${result.status}`);
  }
}

function commandWorks(command, args) {
  const result = spawnSync(command, args, {
    stdio: "ignore",
    shell: true,
  });

  return result.status === 0;
}

function findPythonCommand() {
  const candidates = [
    ["python", ["--version"]],
    ["py", ["--version"]],
    ["python3", ["--version"]],
  ];

  for (const [command, args] of candidates) {
    if (commandWorks(command, args)) {
      return command;
    }
  }

  throw new Error(
    "Python was not found. Please install Python 3.10+ and make sure it is available in PATH."
  );
}

function ensureFolders() {
  for (const dir of [configDir, logsDir, flutterDir]) {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
      console.log(`Created ${dir}`);
    }
  }
}

function ensureConfigFile() {
  const configFile = path.join(configDir, "config.json");

  if (!fs.existsSync(configFile)) {
    const defaultConfig = {
      backendHost: "127.0.0.1",
      backendPort: 8000,
      mongoUri: "mongodb://localhost:27017"
    };

    fs.writeFileSync(configFile, JSON.stringify(defaultConfig, null, 2));
    console.log(`Created ${configFile}`);
  }
}

function main() {
  console.log("Installing Plugs dependencies...");

  ensureFolders();
  ensureConfigFile();

  if (!fs.existsSync(requirementsFile)) {
    throw new Error(`Missing backend requirements file: ${requirementsFile}`);
  }

  const python = findPythonCommand();

  console.log("Python found.");
  console.log("Checking pip...");
  run(python, ["-m", "pip", "--version"]);

  console.log("Installing Python requirements...");
  run(python, ["-m", "pip", "install", "-r", requirementsFile]);

  console.log("Installing Playwright browsers...");
  run(python, ["-m", "playwright", "install"]);

  console.log("Plugs installation complete.");
}

main();