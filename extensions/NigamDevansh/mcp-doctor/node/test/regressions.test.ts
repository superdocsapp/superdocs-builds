// One test per bug found in review. Each fails on the code as it was.

import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { describe, expect, it } from "vitest";

import { isDirectRun, parseArgs, run } from "../src/cli.js";
import { findSharedRoot, loadContract } from "../src/contract.js";
import { parseJsonLike } from "../src/parsers.js";
import { resolveBase } from "../src/paths.js";
import { repair } from "../src/repair.js";
import { scan, type ScanOptions } from "../src/scan.js";

const contract = loadContract();

function sandbox(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-reg-"));
  for (const [rel, content] of Object.entries(files)) {
    const full = join(dir, rel);
    mkdirSync(dirname(full), { recursive: true });
    writeFileSync(full, content, "utf8");
  }
  return dir;
}

function scanIn(dir: string, client: string, deterministic = true) {
  const opts: ScanOptions = {
    cwd: dir,
    env: { HOME: dir, USERPROFILE: dir, CODEX_HOME: join(dir, ".codex") },
    os: "darwin",
    clientFilter: client,
    keyEnvVar: "SUPERDOCS_API_KEY",
    deterministic,
  };
  return scan(contract, opts);
}

/** Grant a cloned contract permission solely to prove the writer. */
function writableContract(clientId: string) {
  const clients = structuredClone(contract.clients);
  const client = clients.find((item) => item.id === clientId)!;
  client.write_capable = { darwin: true, linux: true, win32: true };
  client.repairs.allowed = [...(client.repairs.planned ?? [])];
  return { ...contract, clients };
}

// ── 1 · the contract must not load a stale bundled snapshot ──────────────

describe("shared contract resolution", () => {
  it("loads the source tree, not a bundled snapshot", () => {
    const root = findSharedRoot();
    // Assert the PROPERTY, not the address. An earlier version matched the
    // literal path `extensions/mcp-doctor/shared`, which encoded one checkout's
    // layout into the test: vendoring the project one directory deeper — into
    // `extensions/<user>/mcp-doctor/`, say — failed a test while the code was
    // behaving perfectly. What actually matters is which of two candidate
    // contracts was chosen, and the source tree is the one with a sibling
    // tools/validate_contract.py; a packaging snapshot never has it.
    expect(existsSync(join(root, "..", "tools", "validate_contract.py"))).toBe(true);
    expect(root.endsWith(join("mcp-doctor", "shared"))).toBe(true);
    expect(root).not.toMatch(/node[/\\]shared$/);
  });

  it("prefers the source tree even when a snapshot is listed first", () => {
    const chosen = findSharedRoot([
      join(contract.root, "..", "node", "shared"), // absent in dev
      contract.root,
    ]);
    expect(chosen).toBe(contract.root);
  });

  it("sees edits immediately — no build step between contract and tests", () => {
    // If this ever reads a copy, a contract edit would not show up here.
    expect(contract.catalogue.defects.some((d) => d.id === "config.duplicate-keys")).toBe(true);
  });
});

// ── 2 · project-scoped MCP entries ───────────────────────────────────────

describe("project-scoped containers", () => {
  it("finds a SuperDocs entry under projects[*].mcpServers", () => {
    const dir = sandbox({
      ".claude.json": JSON.stringify(
        {
          projects: {
            "/work/thing": {
              mcpServers: {
                superdocs: {
                  type: "http",
                  url: "http://api.superdocs.app/mcp",
                  headers: { Authorization: "Bearer sk_fixture_proj_00000000" },
                },
              },
            },
          },
        },
        null,
        2,
      ),
    });
    try {
      const report = scanIn(dir, "claude-code");
      const ids = report.findings.map((f) => f.id);
      // It must be FOUND (so: a real defect), not dismissed as "no entry".
      expect(ids).toContain("config.scheme-insecure");
      expect(ids).not.toContain("config.no-entry");
      expect(report.summary.entries_found).toBe(1);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("still reads the top-level container", () => {
    const dir = sandbox({
      ".claude.json": JSON.stringify({
        mcpServers: {
          superdocs: { type: "http", url: "https://api.superdocs.app/mcp", headers: {} },
        },
      }),
    });
    try {
      expect(scanIn(dir, "claude-code").summary.entries_found).toBe(1);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("repairs a discovered project entry, including in deterministic mode", () => {
    const dir = sandbox({
      ".claude.json": JSON.stringify(
        {
          projects: {
            "/work/thing": {
              mcpServers: {
                superdocs: {
                  type: "http",
                  url: "http://api.superdocs.app/mcp",
                  headers: { Authorization: "Bearer sk_fixture_nested_fix_0000" },
                },
              },
            },
          },
        },
        null,
        2,
      ),
    });
    try {
      const result = repair(writableContract("claude-code"), {
        cwd: dir,
        env: { HOME: dir, USERPROFILE: dir },
        os: "darwin",
        clientFilter: "claude-code",
        keyEnvVar: "SUPERDOCS_API_KEY",
        deterministic: true,
      });
      expect(result.exitCode).toBe(0);
      expect(result.files[0]?.applied.map((fix) => fix.findingId)).toContain(
        "config.scheme-insecure",
      );
      expect(result.after.summary.fixed).toBe(1);
      expect(result.after.findings.find((finding) => finding.fixed)?.id).toBe(
        "config.scheme-insecure",
      );
      expect(readFileSync(join(dir, ".claude.json"), "utf8")).toContain(
        "https://api.superdocs.app/mcp",
      );
      expect(readdirSync(dir).some((name) => name.includes(".mcp-doctor-") && name.endsWith(".bak"))).toBe(true);
      // The public deterministic report remains portable even though repair
      // internally used absolute paths to locate the live file.
      expect(JSON.stringify(result.after)).not.toContain(dir);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ── 3 · deterministic mode emits relative paths ──────────────────────────

describe("deterministic output", () => {
  it("contains no absolute path anywhere", () => {
    const dir = sandbox({
      ".mcp.json": JSON.stringify({
        mcpServers: {
          superdocs: { type: "http", url: "http://api.superdocs.app/mcp", headers: {} },
        },
      }),
    });
    try {
      const report = scanIn(dir, "claude-code", true);
      const blob = JSON.stringify(report);
      expect(blob).not.toContain(dir);
      expect(blob).not.toContain(tmpdir());
      for (const file of report.clients.flatMap((c) => c.config_files)) {
        expect(isAbsolute(file.path), `absolute: ${file.path}`).toBe(false);
      }
      for (const f of report.findings) {
        if (f.location?.path) expect(isAbsolute(f.location.path)).toBe(false);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("re-renders messages so no absolute path hides inside one", () => {
    const dir = sandbox({ ".mcp.json": JSON.stringify({ mcpServers: {} }) });
    try {
      const report = scanIn(dir, "claude-code", true);
      const noEntry = report.findings.find((f) => f.id === "config.no-entry");
      expect(noEntry).toBeDefined();
      expect(noEntry!.message).not.toContain(dir);
      expect(noEntry!.message).toContain(".mcp.json");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("omits volatile fields", () => {
    const dir = sandbox({ ".mcp.json": JSON.stringify({ mcpServers: {} }) });
    try {
      const report = scanIn(dir, "claude-code", true);
      expect(report.generated_at).toBeUndefined();
      expect(report.tool.version).toBe("deterministic");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ── 4 · duplicate keys are reported, not silently dropped ────────────────

describe("duplicate keys", () => {
  it("the parser records a repeat", () => {
    const parsed = parseJsonLike('{\n  "url": "http://bad/mcp",\n  "url": "https://good/mcp"\n}\n');
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.duplicates).toEqual([{ container: "(root)", key: "url" }]);
  });

  it("a shadowed url is surfaced instead of hidden", () => {
    const dir = sandbox({
      ".mcp.json":
        '{\n  "mcpServers": {\n    "superdocs": {\n      "type": "http",\n' +
        '      "url": "http://api.superdocs.app/wrong",\n' +
        '      "url": "https://api.superdocs.app/mcp",\n' +
        '      "headers": { "Authorization": "Bearer sk_fixture_dupkey_0000" }\n' +
        "    }\n  }\n}\n",
    });
    try {
      const report = scanIn(dir, "claude-code");
      const dup = report.findings.find((f) => f.id === "config.duplicate-keys");
      expect(dup, "the repeated key must be reported").toBeDefined();
      expect(dup!.data?.field_name).toBe("url");
      // The last one wins, so the surviving value is valid and nothing else fires.
      expect(report.findings.map((f) => f.id)).not.toContain("config.path-wrong");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("a clean file reports none", () => {
    const parsed = parseJsonLike('{"a": 1, "b": {"c": 2}}');
    expect(parsed.ok && parsed.duplicates).toEqual([]);
  });
});

// ── 5 · argument handling ────────────────────────────────────────────────

describe("argument handling", () => {
  it.each(["--client", "--key-env", "--config"])("%s with no value is a usage error", (flag) => {
    const args = parseArgs([flag]);
    expect(args.error).toContain("requires a value");
    const result = run([flag], { HOME: "/nonexistent" });
    expect(result.code).toBe(2);
    expect(result.stdout).toBe("");
  });

  it("a flag swallowing the next flag is a usage error", () => {
    // `--client --json` used to set client to "--json" and scan nothing.
    expect(parseArgs(["--client", "--json"]).error).toContain("requires a value");
  });

  it("--config is accepted and scoped to that file", () => {
    const dir = sandbox({
      "custom/.mcp.json": JSON.stringify({
        mcpServers: {
          superdocs: { type: "http", url: "http://api.superdocs.app/mcp", headers: {} },
        },
      }),
    });
    try {
      const result = run(
        ["--config", join(dir, "custom", ".mcp.json"), "--client", "claude-code", "--json"],
        { HOME: dir },
        dir,
      );
      expect(result.code).toBe(1);
      const report = JSON.parse(result.stdout);
      expect(report.findings.map((f: { id: string }) => f.id)).toContain(
        "config.scheme-insecure",
      );
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("an unknown argument is a usage error", () => {
    expect(run(["--wat"], {}).code).toBe(2);
  });

  it("--fix runs but writes nothing while no client is write-capable", () => {
    // Step 3 replaced the blanket refusal with a per-client gate. The
    // behaviour that matters is unchanged: nothing is written, and the user is
    // told why rather than left to infer it from a silent clean run.
    const dir = sandbox({
      ".mcp.json": JSON.stringify({
        mcpServers: {
          superdocs: { type: "http", url: "http://api.superdocs.app/mcp", headers: {} },
        },
      }),
    });
    const before = readFileSync(join(dir, ".mcp.json"), "utf8");
    try {
      const result = run(["--fix", "--client", "claude-code"], { HOME: dir }, dir);
      expect(result.stdout).toContain("not write-capable");
      expect(result.code).toBe(1);
      expect(readFileSync(join(dir, ".mcp.json"), "utf8")).toBe(before);
      expect(readdirSync(dir).some((f) => f.includes(".bak"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ── 6 · adding an entry has an explicit destination and credential ───────

describe("missing SuperDocs entries", () => {
  it("adds one entry, backs up first, and records it as fixed", () => {
    const dir = sandbox({
      ".mcp.json": '{\n  "mcpServers": { "postgres": { "command": "pg" } }\n}\n',
    });
    try {
      const result = repair(writableContract("claude-code"), {
        cwd: dir,
        env: { HOME: dir, USERPROFILE: dir, SUPERDOCS_API_KEY: "sk_fixture_add_entry_0000" },
        os: "darwin",
        clientFilter: "claude-code",
        keyEnvVar: "SUPERDOCS_API_KEY",
        deterministic: false,
      });
      expect(result.exitCode).toBe(0);
      expect(result.after.summary.fixed).toBe(1);
      const contents = readFileSync(join(dir, ".mcp.json"), "utf8");
      expect(contents).toContain('"superdocs"');
      expect(contents).toContain("Bearer sk_fixture_add_entry_0000");
      expect(readdirSync(dir).some((name) => name.endsWith(".bak"))).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("does not create a backup or config entry without a key", () => {
    const dir = sandbox({ ".mcp.json": '{ "mcpServers": {} }\n' });
    try {
      const result = repair(writableContract("claude-code"), {
        cwd: dir,
        env: { HOME: dir, USERPROFILE: dir },
        os: "darwin",
        clientFilter: "claude-code",
        keyEnvVar: "SUPERDOCS_API_KEY",
        deterministic: false,
      });
      expect(result.exitCode).toBe(1);
      expect(readFileSync(join(dir, ".mcp.json"), "utf8")).toBe('{ "mcpServers": {} }\n');
      expect(readdirSync(dir).some((name) => name.endsWith(".bak"))).toBe(false);
      expect(result.files[0]?.refused[0]?.reason).toContain("no key available");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ── 7 · project-root resolution is hermetic ──────────────────────────────

describe("hermetic project root", () => {
  it("uses the supplied environment, not the ambient one", () => {
    const declared = { HOME: "/declared/home" };
    const got = resolveBase("project_root", contract.bases, {
      os: "darwin",
      cwd: "/declared/home/work/project",
      env: declared,
    });
    // No marker exists on disk, so it stops at cwd — the point is that it did
    // not consult process.env.HOME to decide where to stop.
    expect(got.path).toBe("/declared/home/work/project");
  });

  it("honours USERPROFILE when HOME is absent", () => {
    const got = resolveBase("home", contract.bases, {
      os: "win32",
      cwd: "C:\\x",
      env: { USERPROFILE: "C:\\Users\\dev" },
    });
    expect(got.path).toBe("C:\\Users\\dev");
  });
});

// ── 8 · entry-point detection works with Windows paths ───────────────────

describe("direct-run detection", () => {
  it("does not match on a shared basename alone", () => {
    // The old check compared basenames split on "/", so any cli.js matched.
    expect(isDirectRun("file:///Users/x/pkg/dist/cli.js", "/Users/x/other/cli.js")).toBe(false);
  });

  it("matches the same file", () => {
    expect(isDirectRun("file:///Users/x/pkg/dist/cli.js", "/Users/x/pkg/dist/cli.js")).toBe(true);
  });

  it("handles a Windows-style argv without throwing", () => {
    expect(() =>
      isDirectRun("file:///C:/pkg/dist/cli.js", "C:\\pkg\\dist\\cli.js"),
    ).not.toThrow();
  });

  it("returns false when argv[1] is absent", () => {
    expect(isDirectRun("file:///x/cli.js", undefined)).toBe(false);
  });
});

// ── the read-only CLI does not direct users at --fix ─────────────────────

describe("read-only honesty", () => {
  it("no remediation points at a command that exits 2", () => {
    for (const d of contract.catalogue.defects) {
      if (d.remediation) expect(d.remediation, d.id).not.toContain("--fix");
    }
  });

  it("says repair is unavailable when something is fixable", () => {
    const dir = sandbox({ ".mcp.json": JSON.stringify({ mcpServers: {} }) });
    try {
      const result = run(["--client", "claude-code"], { HOME: dir }, dir);
      expect(result.stdout).toContain("Automatic repair is not available yet");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("marks clients whose knowledge is not captured as experimental", () => {
    const dir = sandbox({ ".mcp.json": JSON.stringify({ mcpServers: {} }) });
    try {
      const result = run(["--client", "claude-code"], { HOME: dir }, dir);
      expect(result.stdout).toContain("experimental");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ── found by differential testing against the Python CLI ────────────────

describe("cross-implementation regressions", () => {
  it("resolves symlinks before relativising a --config path", () => {
    const dir = sandbox({
      ".mcp.json": JSON.stringify({
        mcpServers: {
          superdocs: { type: "http", url: "http://api.superdocs.app/mcp", headers: {} },
        },
      }),
    });
    try {
      const viaSymlinkedTmp = join("/tmp", dir.replace("/private/tmp/", ""));
      const target = existsSync(viaSymlinkedTmp) ? viaSymlinkedTmp : dir;
      const result = run(
        ["--json", "--client", "claude-code", "--config", join(target, ".mcp.json")],
        { HOME: dir, MCP_DOCTOR_DETERMINISTIC: "1" },
        target,
      );
      const report = JSON.parse(result.stdout);
      for (const file of report.clients.flatMap((c: { config_files: { path: string }[] }) => c.config_files)) {
        expect(file.path, `escaped the scan root: ${file.path}`).not.toContain("..");
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("diagnoses a file once when two locations resolve to it", () => {
    // VS Code declares .vscode/mcp.json and Code/User/mcp.json; both end in
    // mcp.json, so --config matched each and one server was reported as two.
    const dir = sandbox({
      ".vscode/mcp.json": JSON.stringify({
        servers: {
          superdocs: {
            type: "http",
            url: "http://api.superdocs.app/mcp",
            headers: { Authorization: "Bearer sk_fixture_once_00000000" },
          },
        },
      }),
    });
    try {
      const result = run(
        ["--json", "--client", "vscode", "--config", join(dir, ".vscode", "mcp.json")],
        { HOME: dir, MCP_DOCTOR_DETERMINISTIC: "1" },
        dir,
      );
      const report = JSON.parse(result.stdout);
      expect(report.summary.entries_found).toBe(1);
      expect(report.findings.filter((f: { id: string }) => f.id === "config.scheme-insecure")).toHaveLength(1);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
