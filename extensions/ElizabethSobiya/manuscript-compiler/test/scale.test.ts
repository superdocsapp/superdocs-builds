/**
 * "A 300-page compile is stable and repeatable."
 *
 * This builds a synthetic book of roughly 300 printed pages — 60 chapters, ~90k
 * words, 120 figures, 180 footnotes, 60 citations — and asserts the properties
 * that actually matter at that size:
 *
 *   - it finishes, and finishes fast enough to be used interactively
 *   - numbering is continuous and correct across all 60 chapters
 *   - a second identical compile is byte-identical
 *   - editing one chapter in the middle re-renders exactly one chapter
 *   - two compiles running at once do not corrupt each other
 */

import { describe, expect, it } from "vitest";
import { compile } from "../src/core/compile";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions } from "../src/core/types";
import { MemoryVault } from "./helpers";

const CHAPTERS = 60;
const PARAGRAPHS_PER_CHAPTER = 28;
const FIGURES_PER_CHAPTER = 2;
const FOOTNOTES_PER_CHAPTER = 3;

const options: CompileOptions = {
  ...DEFAULT_COMPILE_OPTIONS,
  spinePath: "Manuscript.md",
  bibliographyPath: "refs.bib",
};

/** Deterministic filler, so the fixture is stable across runs and machines. */
function paragraph(chapter: number, index: number): string {
  const words = [
    "survey", "ledger", "margin", "coastline", "revision", "interior", "chain",
    "bearing", "notebook", "estuary", "committee", "sheet", "traverse", "cairn",
    "boundary", "contour", "hedge", "gate", "spur", "plate",
  ];
  const out: string[] = [];
  for (let i = 0; i < 55; i += 1) {
    out.push(words[(chapter * 31 + index * 17 + i * 7) % words.length]!);
  }
  return `${out.join(" ")}.`;
}

function bigVault(): MemoryVault {
  const spine: string[] = [
    "---",
    "title: A Very Long Book",
    "author: T. Tester",
    "bibliography: refs.bib",
    "---",
    "",
  ];

  const bib: string[] = [];
  const vault = new MemoryVault({});

  for (let c = 1; c <= CHAPTERS; c += 1) {
    if (c % 20 === 1) spine.push("", `## Part ${Math.ceil(c / 20)}`, "");
    spine.push(`${c}. [[Ch/${String(c).padStart(3, "0")}]]`);

    bib.push(
      `@book{src${c}, author = {Author${c}, A.}, title = {Source Number ${c}}, year = {${1900 + c}}, publisher = {Press}}`,
    );

    const body: string[] = [`# Chapter ${c}`, ""];
    for (let p = 0; p < PARAGRAPHS_PER_CHAPTER; p += 1) {
      body.push(paragraph(c, p), "");
      if (p === 2) body.push(`## Section ${c}.1`, "");
      if (p === 7) body.push(`## Section ${c}.2`, "");
      if (p < FIGURES_PER_CHAPTER) {
        const name = `img/c${c}-${p}.png`;
        vault.setBinary(name, new Uint8Array([c, p, 1, 2]));
        body.push(`![[${name}|Plate ${p + 1} of chapter ${c}.]]`, "");
      }
      if (p < FOOTNOTES_PER_CHAPTER) {
        body[body.length - 2] += `^[A note on ${paragraph(c, p).slice(0, 30)}, citing [@src${c}].]`;
      }
    }
    vault.set(`Ch/${String(c).padStart(3, "0")}.md`, body.join("\n"));
  }

  vault.set("Manuscript.md", spine.join("\n"));
  vault.set("refs.bib", bib.join("\n"));
  return vault;
}

describe("a book-sized compile", () => {
  it("compiles ~300 pages, with correct continuous numbering throughout", async () => {
    const vault = bigVault();
    const started = performance.now();
    const result = await compile({ vault, options, manifestJson: null });
    const elapsed = performance.now() - started;

    expect(result.stats.chapters).toBe(CHAPTERS);
    expect(result.stats.figures).toBe(CHAPTERS * FIGURES_PER_CHAPTER);
    expect(result.stats.footnotes).toBe(CHAPTERS * FOOTNOTES_PER_CHAPTER);
    // ~300 printed pages at the 300-words-per-page convention.
    expect(result.stats.estimatedPages).toBeGreaterThan(280);

    // Footnote numbering must run 1..N with no gap and no repeat, across every
    // chapter boundary. This is the property a 300-page book fails at first.
    const markers = [...result.html.matchAll(/role="doc-noteref">(\d+)<\/sup>/g)].map((m) =>
      Number(m[1]),
    );
    expect(markers).toEqual(
      Array.from({ length: CHAPTERS * FOOTNOTES_PER_CHAPTER }, (_, i) => i + 1),
    );

    // Figure numbering restarts inside each chapter and the chapter part is right.
    const labels = [...result.html.matchAll(/class="figure-label">Figure ([\d.]+)</g)].map(
      (m) => m[1],
    );
    expect(labels).toHaveLength(CHAPTERS * FIGURES_PER_CHAPTER);
    expect(labels[0]).toBe("1.1");
    expect(labels[1]).toBe("1.2");
    expect(labels[labels.length - 1]).toBe(`${CHAPTERS}.2`);

    // Every citation resolved; nothing was invented and nothing was dropped.
    expect(result.html).not.toContain("citation-unresolved");
    expect(result.stats.citations).toBe(CHAPTERS);

    // Interactive means interactive. This is generous for CI on a slow machine.
    expect(elapsed).toBeLessThan(20_000);
  }, 60_000);

  it("produces byte-identical output on a second cold compile", async () => {
    const a = await compile({ vault: bigVault(), options, manifestJson: null });
    const b = await compile({ vault: bigVault(), options, manifestJson: null });
    expect(a.html).toBe(b.html);
    expect(a.stats).toEqual(b.stats);
  }, 60_000);

  it("re-renders one chapter out of sixty when one chapter is edited", async () => {
    const vault = bigVault();
    const first = await compile({ vault, options, manifestJson: null });

    const target = "Ch/030.md";
    vault.set(target, "# Chapter 30\n\nA single rewritten paragraph.\n");
    const started = performance.now();
    const second = await compile({ vault, options, manifestJson: JSON.stringify(first.manifest) });
    const elapsed = performance.now() - started;

    expect(second.reRendered).toEqual([target]);

    const kinds = second.changes.reduce<Record<string, number>>((acc, c) => {
      acc[c.kind] = (acc[c.kind] ?? 0) + 1;
      return acc;
    }, {});
    expect(kinds.rewritten).toBe(1);
    // Chapter 30 lost its figures and footnotes, so everything after it renumbers.
    // Everything BEFORE it must be untouched.
    expect(kinds.unchanged).toBeGreaterThanOrEqual(29);

    // An update should cost like an update.
    expect(elapsed).toBeLessThan(10_000);
  }, 60_000);

  it("keeps two concurrent compiles of the same vault independent", async () => {
    const vault = bigVault();
    const [a, b] = await Promise.all([
      compile({ vault, options, manifestJson: null }),
      compile({ vault, options, manifestJson: null }),
    ]);
    expect(a.html).toBe(b.html);
    expect(a.manifest.outputHash).toBe(b.manifest.outputHash);
    // No shared mutable state leaked between the runs: anchor allocation, figure
    // numbering and footnote numbering are per-compile, not module-level.
    expect(a.stats).toEqual(b.stats);

    // Anchors are allocated per compile. If the two runs had shared that state,
    // the second would have collided and started emitting deduplication suffixes,
    // and the document would contain a repeated id.
    const ids = [...a.html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]!);
    expect(new Set(ids).size).toBe(ids.length);
  }, 60_000);
});
