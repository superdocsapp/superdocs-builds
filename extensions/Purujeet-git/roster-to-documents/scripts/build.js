const fs = require("fs");
const path = require("path");
const childProcess = require("child_process");

const projectRoot = path.resolve(__dirname, "..");
const dist = path.join(projectRoot, "dist");

if (fs.existsSync(dist)) fs.rmSync(dist, { recursive: true, force: true });
childProcess.execFileSync(process.execPath, [path.join(projectRoot, "node_modules", "typescript", "bin", "tsc")], {
  cwd: projectRoot,
  stdio: "inherit"
});

function copyDirectory(name) {
  fs.cpSync(path.join(projectRoot, name), path.join(dist, name), { recursive: true });
}

fs.copyFileSync(path.join(projectRoot, "appsscript.json"), path.join(dist, "appsscript.json"));
copyDirectory("sidebar");
copyDirectory("settings");
copyDirectory("templates");
