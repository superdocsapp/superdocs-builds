// The shared corpus, run against this implementation.
//
// These cases were written before any code existed, so they are a
// specification rather than a description of what this build happens to do.
// Python will run the identical file in step 4 and must produce identical
// output; that is what the conformance suite compares.
//
// `expect.fix` is skipped here: step 2 is read-only and no client is
// write-capable yet. Every case's SCAN expectation must hold.

import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

import { loadContract } from "../src/contract.js";
import { scan, type ScanOptions } from "../src/scan.js";
import type { Report } from "../src/types.js";

interface ExpectedFinding {
  id: string;
  severity?: string;
  auto_fixable?: boolean;
}

interface Case {
  name: string;
  description: string;
  raw_files: Record<string, string>;
  env?: Record<string, string | null>;
  expect: {
    scan: {
      exit_code: number;
      findings: ExpectedFinding[];
      must_not_contain_findings?: string[];
      no_network_to?: string[];
    };
    fix?: unknown;
  };
}

const contract = loadContract();

function loadCases(clientId: string): Case[] {
  const path = join(contract.root, "fixtures", `${clientId}.cases.json`);
  return (JSON.parse(readFileSync(path, "utf8")) as { cases: Case[] }).cases;
}

/** Materialise a case into a throwaway tree and scan it. */
function runCase(clientId: string, testCase: Case): Report {
  const dir = mkdtempSync(join(tmpdir(), "mcp-doctor-"));
  try {
    for (const [relative, content] of Object.entries(testCase.raw_files)) {
      const full = join(dir, relative);
      mkdirSync(dirname(full), { recursive: true });
      writeFileSync(full, content, "utf8");
    }

    // A hermetic environment: HOME points at the sandbox so `home`-based
    // locations resolve inside it, and nothing reads the real machine.
    const env: NodeJS.ProcessEnv = {
      HOME: dir,
      USERPROFILE: dir,
      CODEX_HOME: join(dir, ".codex"),
      XDG_CONFIG_HOME: join(dir, ".config"),
      MCP_DOCTOR_DETERMINISTIC: "1",
    };
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
      deterministic: true,
    };
    return scan(contract, opts);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

for (const clientId of ["claude-code", "vscode", "codex", "antigravity"]) {
  describe(`${clientId} fixtures`, () => {
    const cases = loadCases(clientId);

    it("has cases", () => {
      expect(cases.length).toBeGreaterThan(0);
    });

    for (const testCase of cases) {
      it(`${testCase.name}: ${testCase.description.slice(0, 70)}`, () => {
        const report = runCase(clientId, testCase);
        const ids = report.findings.map((f) => f.id);
        const expected = testCase.expect.scan;

        for (const want of expected.findings) {
          expect(ids, `missing ${want.id}; got [${ids.join(", ")}]`).toContain(want.id);
          const got = report.findings.find((f) => f.id === want.id)!;
          if (want.severity) expect(got.severity).toBe(want.severity);
          if (want.auto_fixable !== undefined) expect(got.auto_fixable).toBe(want.auto_fixable);
        }

        for (const forbidden of expected.must_not_contain_findings ?? []) {
          expect(ids, `${forbidden} must not be reported here`).not.toContain(forbidden);
        }

        expect(report.exit_code, `findings: [${ids.join(", ")}]`).toBe(expected.exit_code);
      });
    }
  });
}

describe("credential redaction", () => {
  it("no fixture key ever reaches any rendered output", async () => {
    const { renderJson, renderReport, renderText } = await import("../src/render.js");
    const pattern = /\b(?:sk_|lce_|gw_)[A-Za-z0-9_-]{8,}/g;

    for (const clientId of ["claude-code", "vscode", "codex", "antigravity"]) {
      for (const testCase of loadCases(clientId)) {
        const secrets = new Set<string>();
        for (const content of Object.values(testCase.raw_files)) {
          for (const m of content.match(pattern) ?? []) secrets.add(m);
        }
        if (secrets.size === 0) continue;

        const report = runCase(clientId, testCase);
        const rendered = [
          renderText(report, false),
          renderJson(report),
          renderReport(report),
        ].join("\n");

        for (const secret of secrets) {
          expect(rendered, `${clientId}/${testCase.name} leaked ${secret}`).not.toContain(secret);
        }
      }
    }
  });

  it("a credential in a URL's userinfo never reaches output", () => {
    const [testCase] = loadCases("claude-code").filter(
      (c) => c.name === "host-rule-userinfo-not-printed",
    );
    expect(testCase).toBeDefined();
    const report = runCase("claude-code", testCase!);
    const everything = JSON.stringify(report);
    expect(everything).not.toContain("sk_fixture_inurl_secret_00");
    // The host IS reported — that is the useful, safe half of the URL.
    expect(everything).toContain("internal-gateway.example");
  });
});
