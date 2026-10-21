/**
 * Cancellation and request coalescing.
 *
 * These two behaviours are what make the compiler safe to attach to a live editor
 * rather than run as a batch job, and both were missing. They are covered here at
 * the level where the logic actually lives — `compile()` for aborting, and the
 * request-merge policy for coalescing — so they need no Obsidian app to test.
 */

import { describe, expect, it } from "vitest";
import { compile } from "../src/core/compile";
import { mergeRequests } from "../src/core/requests";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions } from "../src/core/types";
import { MemoryVault } from "./helpers";

const options: CompileOptions = {
  ...DEFAULT_COMPILE_OPTIONS,
  spinePath: "Manuscript.md",
  bibliographyPath: "refs.bib",
};

function vaultOf(chapters: number): MemoryVault {
  const spine = ["---", "title: Cancellable", "author: T. Tester", "---", ""];
  const vault = new MemoryVault({});
  for (let c = 1; c <= chapters; c += 1) {
    spine.push(`${c}. [[Ch/${c}]]`);
    vault.set(`Ch/${c}.md`, `# Chapter ${c}\n\nSome prose for chapter ${c}.\n`);
  }
  vault.set("Manuscript.md", spine.join("\n"));
  return vault;
}

describe("cancelling a compile", () => {
  it("stops at the first stage boundary when the signal is already aborted", async () => {
    const signal = { aborted: true };
    await expect(
      compile({ vault: vaultOf(5), options, manifestJson: null, signal }),
    ).rejects.toThrow(/abort/i);
  });

  it("stops partway through, rather than only between whole compiles", async () => {
    // Abort once the render stage has started. A compile that only checked its
    // signal at the very end would still run to completion and waste the work.
    const signal = { aborted: false };
    const seen: string[] = [];

    await expect(
      compile({
        vault: vaultOf(40),
        options,
        manifestJson: null,
        signal,
        onProgress: (stage, detail) => {
          seen.push(stage);
          if (stage === "render" && detail?.includes("Ch/3.md")) signal.aborted = true;
        },
      }),
    ).rejects.toThrow(/abort/i);

    // It got as far as rendering, and stopped well short of all forty chapters.
    expect(seen).toContain("render");
    expect(seen.filter((s) => s === "render").length).toBeLessThan(40);
  });

  it("leaves no partial output behind — the failure is a throw, not a half-built book", async () => {
    const signal = { aborted: false };
    let result: unknown = "not assigned";
    try {
      result = await compile({
        vault: vaultOf(20),
        options,
        manifestJson: null,
        signal,
        onProgress: (stage) => {
          if (stage === "render") signal.aborted = true;
        },
      });
    } catch {
      /* expected */
    }
    expect(result).toBe("not assigned");
  });

  it("an un-aborted signal compiles normally", async () => {
    const out = await compile({
      vault: vaultOf(5),
      options,
      manifestJson: null,
      signal: { aborted: false },
    });
    expect(out.stats.chapters).toBe(5);
  });

  it("accepts a real AbortSignal, which is what the plugin passes", async () => {
    const controller = new AbortController();
    const out = await compile({
      vault: vaultOf(3),
      options,
      manifestJson: null,
      signal: controller.signal,
    });
    expect(out.stats.chapters).toBe(3);

    controller.abort();
    await expect(
      compile({ vault: vaultOf(3), options, manifestJson: null, signal: controller.signal }),
    ).rejects.toThrow(/abort/i);
  });
});

describe("coalescing compiles requested while one is running", () => {
  it("keeps a lone request as it is", () => {
    expect(mergeRequests(null, { quiet: true })).toEqual({ quiet: true });
  });

  it("folds many saves into one trailing run", () => {
    let queued = mergeRequests(null, { quiet: true });
    for (let i = 0; i < 9; i += 1) queued = mergeRequests(queued, { quiet: true });
    expect(queued).toEqual({ quiet: true });
  });

  it("does not lose an export request behind a background save", () => {
    const queued = mergeRequests({ quiet: true }, { exportFormats: ["pdf"] });
    expect(queued.exportFormats).toEqual(["pdf"]);
  });

  it("keeps every requested format when two exports coalesce", () => {
    const queued = mergeRequests({ exportFormats: ["pdf"] }, { exportFormats: ["docx"] });
    expect(new Set(queued.exportFormats)).toEqual(new Set(["pdf", "docx"]));
  });

  it("does not repeat a format that was asked for twice", () => {
    const queued = mergeRequests({ exportFormats: ["pdf"] }, { exportFormats: ["pdf"] });
    expect(queued.exportFormats).toEqual(["pdf"]);
  });

  it("stays loud if any folded-in request was deliberate", () => {
    // A background save must never silence a compile the user asked for by hand.
    expect(mergeRequests({ quiet: true }, { quiet: false }).quiet).toBe(false);
    expect(mergeRequests({ quiet: false }, { quiet: true }).quiet).toBe(false);
    expect(mergeRequests({ quiet: true }, { quiet: true }).quiet).toBe(true);
  });

  it("never mutates the request it was given", () => {
    const existing = { exportFormats: ["pdf" as const], quiet: true };
    const frozen = JSON.stringify(existing);
    mergeRequests(existing, { exportFormats: ["docx"], quiet: false });
    expect(JSON.stringify(existing)).toBe(frozen);
  });
});
