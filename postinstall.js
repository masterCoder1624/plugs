const { spawnSync } = require("child_process");
const path = require("path");

const installScript = path.join(__dirname, "install.js");

console.log("Running Plugs postinstall setup...");

const result = spawnSync("node", [installScript], {
  stdio: "inherit",
  shell: true,
});

if (result.error) {
  console.error("Postinstall failed:", result.error.message);
  process.exit(1);
}

if (result.status !== 0) {
  console.error(`Postinstall failed with exit code ${result.status}`);
  process.exit(result.status);
}

console.log("Plugs postinstall setup complete.");