import { describe, expect, it } from "vitest";
import { runTests } from "@vscode/test-electron";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

const EXTENSION_ROOT = path.resolve(__dirname, "..");

const BOOT_SCRIPT = String.raw`
const vscode = require("vscode");
async function run() {
  const ext = vscode.extensions.all.find((e) => e.id.endsWith(".latex-bridge"));
  if (!ext) throw new Error("extension not loaded");
  await ext.activate();
  const expected = [
    "latex-bridge.open",
    "latex-bridge.uploadProject",
    "latex-bridge.exportDocx",
    "latex-bridge.writeBack",
    "latex-bridge.importTrackChanges",
    "latex-bridge.setKey",
    "latex-bridge.clearKey",
  ];
  for (const id of expected) {
    const cmds = await vscode.commands.getCommands(true);
    if (!cmds.includes(id)) throw new Error("command not registered: " + id);
  }
  console.log("[latex-bridge-boot] all " + expected.length + " commands registered");
  return true;
}
module.exports = { run };
`;

describe("extension host boot", () => {
  it("activates the extension and registers all commands", async () => {
    const scratch = path.join(os.tmpdir(), "latex-bridge-boot-" + process.pid);
    fs.mkdirSync(scratch, { recursive: true });
    const bootFile = path.join(scratch, "boot.js");
    fs.writeFileSync(bootFile, BOOT_SCRIPT);
    try {
      const exitCode = await runTests({
        extensionDevelopmentPath: EXTENSION_ROOT,
        extensionTestsPath: bootFile,
        launchArgs: ["--disable-gpu", `--user-data-dir=${path.join(os.tmpdir(), "lb-boot-" + process.pid)}`],
      });
      expect(exitCode).toBe(0);
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  }, 180000);
});
