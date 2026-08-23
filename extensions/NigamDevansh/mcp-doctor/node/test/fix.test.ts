// The repair engine, proven against the exact bytes the shared corpus pins.
//
// The fixtures declare `expect.fix.files` as literal content, so passing here
// means the edit was minimal: comments, trailing commas, CRLF and a BOM all
// survived, and nothing outside the target moved. A field-level assertion
// could not tell the difference.
//
// The engine is exercised DIRECTLY rather than through the CLI, because the
// CLI's policy gate refuses every client today (none is write-capable). Those
// are separate claims and are tested separately.

import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

import { atomicReplace, backupName, gitRootFor, writeBackup } from "../src/backup.js";
import { assertCanonical, loadContract } from "../src/contract.js";
import { assertOnlySpansChanged, tomlValueEdit } from "../src/edits.js";
import { planFixes, repairPermitted, type FixContext } from "../src/fix.js";
import { parseByFormat } from "../src/parsers.js";
import { scan, type ScanOptions } from "../src/scan.js";
import type { Format } from "../src/types.js";

const contract = loadContract();

interface Case {
  name: string;
  description: string;
  raw_files: Record<string, string>;
  env?: Record<string, string | null>;
  expect: {
    scan: { findings: { id: string }[] };
    fix?: {
      exit_code: number;
      findings: { id: string; fixed?: boolean }[];
      files?: Record<string, string>;
      files_unchanged?: boolean;
      backup_expected?: boolean;
    };
  };
}

function loadCases(clientId: string): Case[] {
  const path = join(contract.root, "fixtures", `${clientId}.cases.json`);
  return (JSON.parse(readFileSync(path, "utf8")) as { cases: Case[] }).cases;
}

const FORMAT: Record<string, Format> = {
  "claude-code": "json",
  vscode: "jsonc",
  codex: "toml",
  antigravity: "json",
};

/**
 * Run the engine over one fixture, with the client's write gate lifted.
 *
 * `permit` grants exactly the fix kinds the client already PLANS, so this
 * tests the engine's edits — never a repair the registry has not sanctioned.
 */
function fixCase(clientId: string, testCase: Case) {
  const client = structuredClone(contract.clients.find((c) => c.id === clientId)!);
  client.write_capable = { darwin: true, linux: true, win32: true };
  client.repairs.allowed = client.repairs.planned ?? [];

  const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-fix-"));
  try {
    for (const [rel, content] of Object.entries(testCase.raw_files)) {
      const full = join(dir, rel);
      mkdirSync(dirname(full), { recursive: true });
      writeFileSync(full, content, "utf8");
    }

    const env: NodeJS.ProcessEnv = { HOME: dir, USERPROFILE: dir, CODEX_HOME: join(dir, ".codex") };
    for (const [k, v] of Object.entries(testCase.env ?? {})) {
      if (v === null) delete env[k];
      else env[k] = v;
    }

    const opts: ScanOptions = {
      cwd: dir,
      env,
      os: "darwin",
      clientFilter: clientId,
      keyEnvVar: "SUPERDOCS_API_KEY",
      deterministic: false,
    };
    const report = scan(contract, opts);

    const results: Record<string, { before: string; after: string }> = {};

    for (const [rel, before] of Object.entries(testCase.raw_files)) {
      const full = join(dir, rel);
      const format = FORMAT[clientId]!;
      const parsed = parseByFormat(before, format);
      if (!parsed.ok) {
        results[rel] = { before, after: before }; // unparseable: never rewritten
        continue;
      }

      // Locate the SuperDocs entry path the way the scanner did.
      const containerKey = client.server_map.container_key;
      const container = (parsed.root.value as Record<string, unknown>)[containerKey];
      const entryName =
        container && typeof container === "object"
          ? Object.keys(container as object).find((n) => /^superdocs/i.test(n))
          : undefined;

      if (!entryName) {
        results[rel] = { before, after: before };
        continue;
      }

      const entry = (container as Record<string, Record<string, unknown>>)[entryName]!;
      const ctx: FixContext = {
        contract,
        client,
        os: "darwin",
        format,
        entryPath: [containerKey, entryName],
        entry,
        key: env.SUPERDOCS_API_KEY,
      };

      const outcome = planFixes(report.findings, ctx, before);
      expect(outcome.error, `${testCase.name}: ${outcome.error}`).toBeUndefined();
      results[rel] = { before, after: outcome.text };
      writeFileSync(full, outcome.text, "utf8");
    }

    return { report, results, dir };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

for (const clientId of ["claude-code", "vscode", "codex", "antigravity"]) {
  describe(`${clientId}: repairs produce the exact expected bytes`, () => {
    for (const testCase of loadCases(clientId)) {
      const expected = testCase.expect.fix;
      if (!expected) continue;

      it(`${testCase.name}`, () => {
        const { results } = fixCase(clientId, testCase);

        if (expected.files) {
          for (const [rel, wanted] of Object.entries(expected.files)) {
            expect(results[rel]!.after, `${testCase.name} → ${rel}`).toBe(wanted);
          }
        }

        if (expected.files_unchanged) {
          for (const [rel, { before, after }] of Object.entries(results)) {
            expect(after, `${testCase.name} → ${rel} must be byte-identical`).toBe(before);
          }
        }
      });
    }
  });
}

describe("repairs are idempotent", () => {
  it("a second pass over fixed bytes changes nothing", () => {
    for (const clientId of ["claude-code", "vscode", "codex"]) {
      for (const testCase of loadCases(clientId)) {
        const expected = testCase.expect.fix;
        if (!expected?.files) continue;

        // Feed the ALREADY-FIXED bytes back in; nothing should move.
        const second = structuredClone(testCase);
        second.raw_files = { ...testCase.raw_files, ...expected.files };
        const { results } = fixCase(clientId, second);
        for (const [rel, { before, after }] of Object.entries(results)) {
          expect(after, `${clientId}/${testCase.name} → ${rel} moved on a second pass`).toBe(
            before,
          );
        }
      }
    }
  });
});

describe("the span assertion catches a non-minimal edit", () => {
  it("passes for a genuine splice", () => {
    const before = '{\n  "url": "http://x/mcp"\n}\n';
    const edits = [{ offset: 11, length: 16, content: '"https://x/mcp"' }];
    const after = before.slice(0, 11) + edits[0]!.content + before.slice(11 + 16);
    expect(assertOnlySpansChanged(before, after, edits).ok).toBe(true);
  });

  it("fails when a byte outside the span moved", () => {
    // A reformat: the edit claims one span, but the indentation changed too.
    const before = '{\n  "a": 1,\n  "url": "http://x"\n}\n';
    const after = '{\n"a": 1,\n"url": "https://x"\n}\n';
    const edits = [{ offset: 21, length: 10, content: '"https://x"' }];
    const verdict = assertOnlySpansChanged(before, after, edits);
    expect(verdict.ok).toBe(false);
    if (!verdict.ok) expect(verdict.reason).toContain("outside the edited spans");
  });

  it("never includes source text (or a key) in a failed assertion", () => {
    const secret = "sk_fixture_assertion_redaction_0000";
    const verdict = assertOnlySpansChanged(
      `Authorization: Bearer ${secret}`,
      `Authorization: Bearer ${secret} changed`,
      [],
    );
    expect(verdict.ok).toBe(false);
    if (!verdict.ok) expect(verdict.reason).not.toContain(secret);
  });

  it("rejects overlapping edits", () => {
    const verdict = assertOnlySpansChanged("abcdef", "xyz", [
      { offset: 0, length: 3, content: "x" },
      { offset: 1, length: 2, content: "y" },
    ]);
    expect(verdict.ok).toBe(false);
  });
});

describe("the write gate", () => {
  it("refuses every shipped client, because none is write-capable", () => {
    for (const client of contract.clients) {
      for (const kind of client.repairs.planned ?? []) {
        const verdict = repairPermitted(client, kind, "darwin");
        expect(verdict.ok, `${client.id}/${kind} should be refused`).toBe(false);
        if (!verdict.ok) expect(verdict.reason).toContain("not write-capable");
      }
    }
  });

  it("refuses a kind the client does not permit even when write-capable", () => {
    const client = structuredClone(contract.clients.find((c) => c.id === "claude-code")!);
    client.write_capable = { darwin: true, linux: true, win32: true };
    client.repairs.allowed = ["url-scheme"];
    expect(repairPermitted(client, "url-scheme", "darwin").ok).toBe(true);
    const denied = repairPermitted(client, "auth-header", "darwin");
    expect(denied.ok).toBe(false);
    if (!denied.ok) expect(denied.reason).toContain("does not permit");
  });

  it("is per-OS", () => {
    const client = structuredClone(contract.clients.find((c) => c.id === "claude-code")!);
    client.write_capable = { darwin: true, linux: false, win32: false };
    client.repairs.allowed = ["url-scheme"];
    expect(repairPermitted(client, "url-scheme", "darwin").ok).toBe(true);
    expect(repairPermitted(client, "url-scheme", "win32").ok).toBe(false);
  });
});

describe("backups", () => {
  it("is written 0600 before any content reaches it", () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-bak-"));
    try {
      const target = join(dir, "config.json");
      writeFileSync(target, '{"key":"sk_fixture_backup_000000"}', "utf8");
      const result = writeBackup(target, readFileSync(target, "utf8"));
      expect(existsSync(result.path)).toBe(true);
      expect(readFileSync(result.path, "utf8")).toContain("sk_fixture_backup_000000");
      if (process.platform !== "win32") {
        expect(statSync(result.path).mode & 0o777).toBe(0o600);
        expect(result.restricted).toBe(true);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("names itself with a timestamp", () => {
    const name = backupName("/x/config.json", new Date(2026, 7, 23, 9, 5, 3));
    expect(name).toBe("/x/config.json.mcp-doctor-20260823-090503.bak");
  });

  it("retries a colliding backup name without overwriting the earlier backup", () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-bak-collision-"));
    try {
      const target = join(dir, "config.json");
      writeFileSync(target, "{}", "utf8");
      const now = new Date(2026, 7, 23, 9, 5, 3);
      const first = writeBackup(target, "one", { now });
      const second = writeBackup(target, "two", { now });
      expect(first.path).not.toBe(second.path);
      expect(readFileSync(first.path, "utf8")).toBe("one");
      expect(readFileSync(second.path, "utf8")).toBe("two");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("warns when the backup lands inside a git repository", () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-git-"));
    try {
      mkdirSync(join(dir, ".git"));
      const target = join(dir, ".mcp.json");
      writeFileSync(target, "{}", "utf8");
      const result = writeBackup(target, "{}");
      expect(result.gitWarning).toBeDefined();
      expect(result.gitWarning).toContain(".gitignore");
      expect(result.gitWarning).toContain("*.mcp-doctor-*.bak");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("does not warn outside a repository", () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-nogit-"));
    try {
      const target = join(dir, "config.json");
      writeFileSync(target, "{}", "utf8");
      // tmpdir is not inside a git tree on any platform we test on.
      if (gitRootFor(target) === null) {
        expect(writeBackup(target, "{}").gitWarning).toBeUndefined();
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("atomically replaces the config without leaving a plaintext temp file", () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-atomic-"));
    try {
      const target = join(dir, "config.json");
      writeFileSync(target, '{"old":true}\n', "utf8");
      if (process.platform !== "win32") chmodSync(target, 0o640);
      atomicReplace(target, '{"Authorization":"Bearer sk_fixture_atomic_0000"}\n');
      expect(readFileSync(target, "utf8")).toContain("sk_fixture_atomic_0000");
      expect(readdirSync(dir).filter((name) => name.endsWith(".tmp"))).toEqual([]);
      if (process.platform !== "win32") expect(statSync(target).mode & 0o777).toBe(0o640);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("TOML value location", () => {
  const doc =
    'model = "x"\n\n[mcp_servers.superdocs]\nurl = "http://api.superdocs.app/mcp"\n\n' +
    '[projects."/some/path"]\ntrust_level = "trusted"\n';

  it("replaces only the target value", () => {
    const edit = tomlValueEdit(doc, { table: "mcp_servers.superdocs", key: "url" }, "https://y");
    expect(edit).not.toBeNull();
    expect(doc.slice(edit!.offset, edit!.offset + edit!.length)).toBe(
      '"http://api.superdocs.app/mcp"',
    );
  });

  it("returns null for a key in another table", () => {
    expect(tomlValueEdit(doc, { table: "mcp_servers.other", key: "url" }, "x")).toBeNull();
  });

  it("returns null rather than guessing between two occurrences", () => {
    const ambiguous = '[t]\nurl = "a"\nurl = "b"\n';
    expect(tomlValueEdit(ambiguous, { table: "t", key: "url" }, "c")).toBeNull();
  });
});

describe("the runtime re-checks the canonical endpoint", () => {
  it("refuses a contract pointing somewhere else", () => {
    // The validator pins this in CI, which says nothing about the bytes
    // actually loaded at run time. A substituted contract must not be able to
    // decide where an authenticated request goes.
    expect(() =>
      assertCanonical({
        canonical: {
          url: "https://evil.example/mcp",
          host: "evil.example",
          path: "/mcp",
          scheme: "https",
          follow_redirects: false,
        },
      } as never),
    ).toThrow(/refusing to run/);
  });

  it("refuses a contract that permits redirects", () => {
    expect(() =>
      assertCanonical({
        canonical: {
          url: "https://api.superdocs.app/mcp",
          host: "api.superdocs.app",
          path: "/mcp",
          scheme: "https",
          follow_redirects: true,
        },
      } as never),
    ).toThrow(/redirects/);
  });

  it("accepts the shipped contract", () => {
    expect(() => assertCanonical(contract.profile)).not.toThrow();
  });
});

describe("two fixes targeting the same field", () => {
  it("compose instead of clobbering each other", () => {
    // A wrong scheme AND a wrong path both live in `url`. Computing both from
    // the original parse meant the second write discarded the first — which
    // reported a successful repair that had not happened.
    const client = structuredClone(contract.clients.find((c) => c.id === "claude-code")!);
    client.write_capable = { darwin: true, linux: true, win32: true };
    client.repairs.allowed = client.repairs.planned ?? [];

    const before =
      '{\n  "mcpServers": {\n    "superdocs": {\n      "type": "http",\n' +
      '      "url": "http://api.superdocs.app/v1/mcp",\n' +
      '      "headers": { "Authorization": "Bearer sk_fixture_compose_0000" }\n' +
      "    }\n  }\n}\n";

    const parsed = parseByFormat(before, "json");
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    const entry = (
      (parsed.root.value as Record<string, Record<string, Record<string, unknown>>>).mcpServers
    ).superdocs!;

    const findings = [
      { id: "config.path-wrong" },
      { id: "config.scheme-insecure" },
    ] as never[];

    const outcome = planFixes(findings, {
      contract,
      client,
      os: "darwin",
      format: "json",
      entryPath: ["mcpServers", "superdocs"],
      entry,
    }, before);

    expect(outcome.applied).toHaveLength(2);
    // BOTH corrections must survive in the final bytes.
    expect(outcome.text).toContain('"url": "https://api.superdocs.app/mcp"');
    expect(outcome.text).not.toContain("/v1/mcp");
    expect(outcome.text).not.toContain("http://");
  });
});
