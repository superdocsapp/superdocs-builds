import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";
import { computeRegions } from "./diff.js";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Resolve the locally installed SuperDoc CLI and run it via `node` directly
// against its JS entry point. This deliberately avoids both `npx superdoc`
// (the *browser editor* is separately published to npm as plain "superdoc",
// so npx risks resolving the wrong package) and the `node_modules/.bin`
// shims (on Windows the extensionless shim is a POSIX script that spawn
// cannot execute — ENOENT). A JS file under the current `node` is
// deterministic on every platform.
const CLI_ENTRY = path.join(
  __dirname,
  "..",
  "..",
  "node_modules",
  "@superdoc-dev",
  "cli",
  "dist",
  "index.js"
);

async function runCli(args) {
  const { stdout } = await execFileAsync(process.execPath, [CLI_ENTRY, ...args], {
    maxBuffer: 1024 * 1024 * 25,
  });
  const trimmed = stdout.trim();
  if (!trimmed) return null;
  // The CLI prints "[super-editor] ..." log lines to stdout before the JSON
  // payload (telemetry banner, etc.). Parse from the first '{' to skip them.
  return JSON.parse(trimmed.slice(trimmed.indexOf("{")));
}

/**
 * Session wrapper around the installed SuperDoc CLI (verified against
 * `describe command` on v0.1.0):
 *
 *   superdoc open <path> --session <id>
 *   superdoc blocks list --session <id> --limit <n> --include-text
 *   superdoc replace --session <id> --target-json '{...}' --text "..." --change-mode tracked
 *   superdoc save --session <id> --in-place
 *   superdoc close --session <id>
 *
 * Confirmed on the installed version:
 *   - Every session-scoped command accepts --session.
 *   - `blocks list` returns only truncated previews unless --include-text
 *     is passed, and responses are wrapped as { ok, data, ... }.
 *   - `replace` accepts { kind: 'block', nodeType, nodeId } as --target-json
 *     (targeting a block directly avoids ambiguity with repeated wording,
 *     which a text-pattern match would have).
 */
export class SuperDocSession {
  constructor() {
    this.sessionId = crypto.randomUUID();
  }

  async open(docxPath) {
    return runCli(["open", docxPath, "--session", this.sessionId]);
  }

  async listBlocks(limit = 500) {
    const result = await runCli([
      "blocks",
      "list",
      "--session",
      this.sessionId,
      "--limit",
      String(limit),
      // Without this, blocks come back as short previews, not full text.
      "--include-text",
    ]);
    // CLI responses are wrapped as { ok, data, ... }; the blocks live under
    // data.result.blocks. Fall back gracefully just in case.
    return result?.data?.result?.blocks ?? result?.data?.blocks ?? result?.blocks ?? [];
  }

  async replaceBlockTracked(block, newText) {
    // `replace --text` requires a SelectionTarget (the {kind:"block"} form
    // is only accepted with the structural `--content-json` path). Split the
    // revision into word-level regions (see diff.js) and replace each region
    // with its own tracked change: replacing the whole block at once makes
    // the runtime diff at the character level, fragmenting one revision
    // into un-reviewable mid-word edits.
    const edits = computeRegions(block.text, newText).map((r) => ({
      target: {
        kind: "selection",
        start: { kind: "text", blockId: block.nodeId, offset: r.start },
        end: { kind: "text", blockId: block.nodeId, offset: r.end },
      },
      text: r.newText,
    }));

    // Apply right to left so earlier offsets stay valid: edits to the right
    // never shift text that lies to the left of the next region.
    edits.sort((x, y) => y.target.start.offset - x.target.start.offset);

    const responses = [];
    for (const edit of edits) {
      responses.push(
        await runCli([
          "replace",
          "--session",
          this.sessionId,
          "--target-json",
          JSON.stringify(edit.target),
          "--text",
          edit.text,
          "--change-mode",
          "tracked",
        ])
      );
    }
    return responses;
  }

  async save() {
    return runCli(["save", "--session", this.sessionId, "--in-place"]);
  }

  async close() {
    return runCli(["close", "--session", this.sessionId]);
  }
}
