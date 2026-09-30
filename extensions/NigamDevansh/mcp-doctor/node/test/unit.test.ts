// Properties the read-only step must already get right, because step 3 builds
// its span edits directly on top of them.

import { describe, expect, it } from "vitest";

import { loadContract } from "../src/contract.js";
import { hostOf, isCanonicalHost, render } from "../src/diagnose.js";
import { parseByFormat, parseJsonLike, parseTomlText } from "../src/parsers.js";
import { currentOs, resolveBase, resolveLocation } from "../src/paths.js";
import type { Location } from "../src/types.js";

const contract = loadContract();

describe("parsers: spans point at the exact bytes", () => {
  it("a value's span selects that value and nothing else", () => {
    const text = '{\n  "url": "http://x/mcp"\n}\n';
    const parsed = parseJsonLike(text);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    const span = parsed.root.children!.get("url")!.span;
    expect(text.slice(span.offset, span.offset + span.length)).toBe('"http://x/mcp"');
  });

  it("spans survive a BOM, so a repair does not strip it", () => {
    const text = '\uFEFF{\n  "url": "http://x/mcp"\n}\n';
    const parsed = parseJsonLike(text);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    expect(parsed.bom).toBe(true);
    const span = parsed.root.children!.get("url")!.span;
    // Offsets are relative to the ORIGINAL text, BOM included.
    expect(text.slice(span.offset, span.offset + span.length)).toBe('"http://x/mcp"');
  });

  it("spans are correct with CRLF line endings", () => {
    const text = '{\r\n  "url": "http://x/mcp"\r\n}\r\n';
    const parsed = parseJsonLike(text);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    const span = parsed.root.children!.get("url")!.span;
    expect(text.slice(span.offset, span.offset + span.length)).toBe('"http://x/mcp"');
  });

  it("JSONC comments and trailing commas parse, and spans skip them", () => {
    const text = '{\n  // note\n  "url": /* inline */ "http://x/mcp",\n}\n';
    const parsed = parseJsonLike(text);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    const span = parsed.root.children!.get("url")!.span;
    // The block comment sits between key and value; the span must land on the
    // value alone, or a repair would swallow the comment.
    expect(text.slice(span.offset, span.offset + span.length)).toBe('"http://x/mcp"');
  });

  it("accepts comments and trailing commas only for JSONC locations", () => {
    const text = '{ // comment\n  "url": "https://api.superdocs.app/mcp",\n}';
    expect(parseByFormat(text, "json").ok).toBe(false);
    expect(parseByFormat(text, "jsonc").ok).toBe(true);
  });

  it("an empty file is reported as empty, never as invalid", () => {
    for (const format of ["json", "jsonc", "toml"] as const) {
      const parsed = parseByFormat("", format);
      expect(parsed.ok).toBe(false);
      if (parsed.ok) continue;
      expect(parsed.empty).toBe(true);
    }
  });

  it("invalid input reports a position rather than throwing", () => {
    const parsed = parseJsonLike('{ "a": }');
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.empty).toBeUndefined();
    expect(parsed.line).toBeGreaterThan(0);
  });

  it("real-world TOML with many tables parses", () => {
    const parsed = parseTomlText(
      'model = "x"\n\n[mcp_servers.a]\ncommand = "c"\nargs = []\n\n' +
        '[mcp_servers.a.env]\nK = "v"\n\n[projects."/some/path"]\ntrust_level = "trusted"\n',
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    const servers = (parsed.root.value as Record<string, unknown>).mcp_servers;
    expect(Object.keys(servers as object)).toEqual(["a"]);
  });
});

describe("host matching is exact", () => {
  it("strips userinfo so a credential never reaches a message", () => {
    expect(hostOf("https://sk_secret@gw.example/mcp")).toBe("gw.example");
  });

  it("rejects a lookalike suffix", () => {
    const p = contract.profile;
    expect(isCanonicalHost(hostOf("https://api.superdocs.app/mcp"), p)).toBe(true);
    expect(isCanonicalHost(hostOf("https://api.superdocs.app.evil.example/mcp"), p)).toBe(false);
    expect(isCanonicalHost(hostOf("https://evil-api.superdocs.app.co/mcp"), p)).toBe(false);
  });

  it("treats an unparseable URL as not canonical", () => {
    expect(hostOf("not a url")).toBeNull();
    expect(isCanonicalHost(null, contract.profile)).toBe(false);
  });
});

describe("path bases come from data", () => {
  it("prefers an environment variable over the fallback", () => {
    const got = resolveBase("codex_home", contract.bases, {
      os: "darwin",
      cwd: "/tmp",
      env: { CODEX_HOME: "/custom/codex", HOME: "/home/u" },
    });
    expect(got.path).toBe("/custom/codex");
  });

  it("falls back when the variable is unset", () => {
    const got = resolveBase("codex_home", contract.bases, {
      os: "darwin",
      cwd: "/tmp",
      env: { HOME: "/home/u" },
    });
    expect(got.path).toBe("/home/u/.codex");
  });

  it("reports unresolvable rather than guessing", () => {
    // codex_home has no Windows fallback: without APPDATA-style state there is
    // no honest answer, so it must say so.
    const got = resolveBase("codex_home", contract.bases, {
      os: "win32",
      cwd: "C:\\tmp",
      env: {},
    });
    expect(got.path).toBeNull();
    expect(got.unresolvable).toContain("CODEX_HOME");
  });

  it("skips a location not configured for this OS", () => {
    const location: Location = {
      scope: "user",
      precedence: 1,
      format: "json",
      os: ["linux"],
      base: "home",
      path: "x.json",
    };
    const got = resolveLocation(location, contract.bases, {
      os: "darwin",
      cwd: "/tmp",
      env: { HOME: "/home/u" },
    });
    expect(got.path).toBeNull();
  });

  it("knows this platform", () => {
    expect(currentOs("darwin")).toBe("darwin");
    expect(currentOs("sunos")).toBeNull();
  });
});

describe("templates", () => {
  it("substitutes only what it is given", () => {
    expect(render("{client}: {found} != {expected}", {
      client: "X",
      found: "a",
      expected: "b",
    })).toBe("X: a != b");
  });

  it("leaves an unknown placeholder alone rather than printing undefined", () => {
    expect(render("{client}: {mystery}", { client: "X" })).toBe("X: {mystery}");
  });
});

describe("the contract loads", () => {
  it("has every client and a defect lookup that fails loudly", () => {
    expect(contract.clients.map((c) => c.id)).toEqual([
      "antigravity",
      "claude-code",
      "codex",
      "vscode",
    ]);
    expect(contract.defect("config.scheme-insecure").severity).toBe("error");
    expect(() => contract.defect("config.invented")).toThrow(/not in the shared catalogue/);
  });
});
