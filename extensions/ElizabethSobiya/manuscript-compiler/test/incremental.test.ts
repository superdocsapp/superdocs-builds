/**
 * The claim under test: "recompiling after editing one chapter changes only what
 * should change."
 *
 * These tests are the reason the compiler renders chapters into tokenised HTML and
 * resolves numbering at assembly. They assert the property directly — byte
 * equality of the chapters that should not have moved — rather than asserting that
 * a cache was consulted.
 */

import { describe, expect, it } from "vitest";
import { compile } from "../src/core/compile";
import { summariseChanges } from "../src/core/cache";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions } from "../src/core/types";
import { MemoryVault } from "./helpers";
import { smallVault } from "./fixtures/vault";

const options: CompileOptions = {
  ...DEFAULT_COMPILE_OPTIONS,
  spinePath: "Manuscript.md",
  bibliographyPath: "refs.bib",
};

async function build(vault: MemoryVault, manifestJson: string | null) {
  return compile({ vault, options, manifestJson });
}

/** Split the assembled HTML into its chapter sections, keyed by source path. */
function chapterSections(html: string): Map<string, string> {
  const out = new Map<string, string>();
  const re = /<section class="chapter[^"]*" data-chapter-path="([^"]+)">([\s\S]*?)<\/section>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) out.set(m[1]!, m[2]!);
  return out;
}

describe("incremental compile", () => {
  it("reports every chapter as unchanged when nothing was edited", async () => {
    const vault = smallVault();
    const first = await build(vault, null);
    const second = await build(vault, JSON.stringify(first.manifest));

    expect(summariseChanges(second.changes)).toMatchObject({
      unchanged: 4,
      rewritten: 0,
      renumbered: 0,
      added: 0,
      removed: 0,
    });
    expect(second.reRendered).toEqual([]);
    expect(second.html).toBe(first.html);
  });

  it("re-renders only the edited chapter, and leaves the others byte-identical", async () => {
    const vault = smallVault();
    const first = await build(vault, null);

    // Prose only: the figure stays, so nothing chapter one points at moves.
    vault.set(
      "Ch/Two.md",
      "# Chapter Two\n\nCompletely different prose now[^ref].\n\n![[img/second.png|The second plate.]]\n\n[^ref]: A reference-form note that cites [@beta1999].\n",
    );
    const second = await build(vault, JSON.stringify(first.manifest));

    expect(second.reRendered).toEqual(["Ch/Two.md"]);

    const before = chapterSections(first.html);
    const after = chapterSections(second.html);
    for (const path of ["Front/Preface.md", "Ch/One.md", "Back/Colophon.md"]) {
      expect(after.get(path), `${path} should not have moved`).toBe(before.get(path));
    }
    expect(after.get("Ch/Two.md")).not.toBe(before.get("Ch/Two.md"));
  });

  it("renumbers later chapters without re-rendering them when an earlier chapter gains a figure", async () => {
    const vault = smallVault();
    // Give chapter one a second plate; chapter two's figure number must move.
    const first = await build(vault, null);
    vault.setBinary("img/extra.png", new Uint8Array([9, 9, 9]));
    vault.set(
      "Ch/One.md",
      `# Chapter One\n\n![[img/first.png|The first plate.]]\n\n![[img/extra.png|An added plate.]]\n\n![[img/second.png|placeholder]]\n`,
    );
    const second = await build(vault, JSON.stringify(first.manifest));

    // Only chapter one went through the markdown renderer.
    expect(second.reRendered).toEqual(["Ch/One.md"]);
    const verdicts = new Map(second.changes.map((c) => [c.path, c.kind]));
    expect(verdicts.get("Ch/One.md")).toBe("rewritten");
    expect(verdicts.get("Front/Preface.md")).toBe("unchanged");
  });

  it("renumbers, rather than re-renders, when a chapter is moved on the spine", async () => {
    const vault = smallVault();
    const first = await build(vault, null);

    vault.set(
      "Manuscript.md",
      vault.files.get("Manuscript.md")!.replace("1. [[Ch/One]]\n2. [[Ch/Two]]", "1. [[Ch/Two]]\n2. [[Ch/One]]"),
    );
    const second = await build(vault, JSON.stringify(first.manifest));

    // Moving a chapter must not force its prose through the renderer again.
    expect(second.reRendered).toEqual([]);
    const kinds = second.changes.map((c) => c.kind);
    expect(kinds).not.toContain("rewritten");
    // The figure numbers did move, though, and the report says so.
    expect(second.html).toMatch(
      /class="figure-label">Figure 1\.1<\/span> &#8212; The second plate\./,
    );
  });

  it("re-renders the chapters that transclude an edited shared note, and only those", async () => {
    const vault = smallVault();
    vault.set("Shared/Rights.md", "Original rights text.");
    vault.set("Ch/One.md", "# Chapter One\n\n![[Shared/Rights]]\n");
    const first = await build(vault, null);

    vault.set("Shared/Rights.md", "Revised rights text.");
    const second = await build(vault, JSON.stringify(first.manifest));

    expect(second.reRendered).toEqual(["Ch/One.md"]);
    expect(second.html).toContain("Revised rights text.");
    expect(second.html).not.toContain("Original rights text.");
  });

  it("reads and sanitizes each shared source only once per compile", async () => {
    const vault = smallVault();
    vault.set("Shared/Rights.md", "Shared rights text.");
    vault.set("Ch/One.md", "# Chapter One\n\n![[Shared/Rights]]\n");
    vault.set("Ch/Two.md", "# Chapter Two\n\n![[Shared/Rights]]\n");

    await build(vault, null);

    const count = (path: string) => vault.reads.filter((read) => read === path).length;
    expect(count("Manuscript.md")).toBe(1);
    expect(count("Ch/One.md")).toBe(1);
    expect(count("Ch/Two.md")).toBe(1);
    expect(count("Shared/Rights.md")).toBe(1);
  });

  it("treats a chapter added to the spine as added, and one removed as removed", async () => {
    const vault = smallVault();
    const first = await build(vault, null);

    vault.set("Ch/Three.md", "# Chapter Three\n\nNew.\n");
    vault.set(
      "Manuscript.md",
      vault.files.get("Manuscript.md")!.replace("2. [[Ch/Two]]", "2. [[Ch/Two]]\n3. [[Ch/Three]]"),
    );
    const second = await build(vault, JSON.stringify(first.manifest));
    expect(second.changes.find((c) => c.path === "Ch/Three.md")?.kind).toBe("added");

    vault.set(
      "Manuscript.md",
      vault.files.get("Manuscript.md")!.replace("2. [[Ch/Two]]\n", ""),
    );
    const third = await build(vault, JSON.stringify(second.manifest));
    expect(third.changes.find((c) => c.path === "Ch/Two.md")?.kind).toBe("removed");
  });

  it("falls back to a cold compile when the manifest is corrupt, rather than failing", async () => {
    const vault = smallVault();
    const result = await build(vault, "{not json at all");
    expect(result.reRendered).toHaveLength(4);
    expect(result.stats.chapters).toBe(4);
  });

  it("discards a manifest written by an older build", async () => {
    const vault = smallVault();
    const first = await build(vault, null);
    const stale = JSON.stringify({ ...first.manifest, version: 1 });
    const second = await build(vault, stale);
    expect(second.reRendered).toHaveLength(4);
  });

  /**
   * Resumability: a run killed part-way is a manifest that describes fewer
   * chapters than the spine. The next run must complete it, not start over.
   */
  it("completes a compile that was interrupted part-way through", async () => {
    const vault = smallVault();
    const full = await build(vault, null);

    const partial = structuredClone(full.manifest);
    delete partial.chapters["Ch/Two.md"];
    delete partial.renders["Ch/Two.md"];
    delete partial.chapters["Back/Colophon.md"];
    delete partial.renders["Back/Colophon.md"];

    const resumed = await build(vault, JSON.stringify(partial));
    expect(resumed.reRendered.sort()).toEqual(["Back/Colophon.md", "Ch/Two.md"]);
    expect(resumed.html).toBe(full.html);
  });

  it("stops cleanly when the caller aborts mid-render", async () => {
    const vault = smallVault();
    const signal = { aborted: false };
    let seen = 0;
    await expect(
      compile({
        vault,
        options,
        manifestJson: null,
        signal,
        onProgress: (stage) => {
          if (stage === "render" && ++seen === 2) signal.aborted = true;
        },
      }),
    ).rejects.toThrow(/aborted/i);
  });
});

describe("spine frontmatter", () => {
  it("lets the manuscript carry its own settings, overriding the plugin's", async () => {
    const vault = smallVault();
    vault.set(
      "Manuscript.md",
      vault.files.get("Manuscript.md")!.replace(
        "bibliography: refs.bib",
        "bibliography: refs.bib\ncitation_style: numeric\nfigure_numbering: continuous",
      ),
    );
    const result = await compile({
      vault,
      options: { ...options, citationStyle: "author-date", figureNumbering: "by-chapter" },
      manifestJson: null,
    });
    const labels = [...result.html.matchAll(/class="figure-label">([^<]*)</g)].map((m) => m[1]);
    expect(labels).toEqual(["Figure 1", "Figure 2"]);
    expect(result.html).toContain("bib-number");
  });

  it("keeps compiling with a clear warning when the frontmatter is not valid YAML", async () => {
    const vault = smallVault();
    vault.set("Manuscript.md", "---\ntitle: [unclosed\n---\n\n- [[Ch/One]]\n");
    const result = await compile({ vault, options, manifestJson: null });
    expect(result.diagnostics.some((d) => d.code === "spine.frontmatter_invalid")).toBe(true);
    expect(result.stats.chapters).toBe(1);
  });
});
