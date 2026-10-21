import { describe, expect, it } from "vitest";
import { compile } from "../src/core/compile";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions } from "../src/core/types";
import { MemoryVault } from "./helpers";
import { smallVault } from "./fixtures/vault";

const options: CompileOptions = {
  ...DEFAULT_COMPILE_OPTIONS,
  spinePath: "Manuscript.md",
  bibliographyPath: "refs.bib",
};

async function build(vault: MemoryVault, manifestJson: string | null = null, over: Partial<CompileOptions> = {}) {
  return compile({ vault, options: { ...options, ...over }, manifestJson });
}

describe("compile: the book comes out in the right order", () => {
  it("places chapters in spine order, with front and back matter around them", async () => {
    const result = await build(smallVault());
    const titles = [...result.html.matchAll(/class="chapter-title"[^>]*>([^<]+)</g)].map((m) => m[1]);
    expect(titles).toEqual(["Preface", "Chapter One", "Chapter Two", "Colophon"]);
  });

  it("generates the front matter it was asked for", async () => {
    const result = await build(smallVault());
    expect(result.html).toContain('class="front-matter title-page"');
    expect(result.html).toContain("A Small Book");
    expect(result.html).toContain("T. Tester");
    expect(result.html).toContain('class="front-matter copyright-page"');
    expect(result.html).toContain('id="mc-toc"');
  });

  it("emits a part title page for a named part", async () => {
    const result = await build(smallVault());
    expect(result.html).toContain('class="part-heading"');
    expect(result.html).toContain("Part One");
  });

  it("uses real page breaks rather than blank paragraphs", async () => {
    const result = await build(smallVault());
    // The marker verified against the live exporter as producing a true Word break.
    expect(result.html).toContain('<hr data-page-break="true">');
    expect(result.html).not.toMatch(/page-break-before:\s*always/);
  });

  it("is byte-for-byte deterministic across two cold compiles", async () => {
    const a = await build(smallVault());
    const b = await build(smallVault());
    expect(a.html).toBe(b.html);
  });
});

describe("compile: heading normalisation", () => {
  it("maps a note's heading levels onto consecutive levels under the chapter", async () => {
    const vault = smallVault();
    // One.md uses "###" for its only subheading; it must not stay at h3.
    const result = await build(vault);
    const chapterOne = result.html.slice(
      result.html.indexOf('data-chapter-path="Ch/One.md"'),
      result.html.indexOf('data-chapter-path="Ch/Two.md"'),
    );
    expect(chapterOne).toMatch(/<h2 id="[^"]*a-deep-heading">A deep heading<\/h2>/);
    expect(chapterOne).not.toContain("<h3");
  });

  it("gives two notes with different heading conventions the same output shape", async () => {
    const a = new MemoryVault({
      "Manuscript.md": "---\ntitle: X\n---\n\n- [[A]]\n",
      "A.md": "# A\n\n## Sub\n\n### Deeper\n",
    });
    const b = new MemoryVault({
      "Manuscript.md": "---\ntitle: X\n---\n\n- [[A]]\n",
      "A.md": "# A\n\n### Sub\n\n##### Deeper\n",
    });
    const ra = await compile({ vault: a, options: { ...options, bibliographyPath: null }, manifestJson: null });
    const rb = await compile({ vault: b, options: { ...options, bibliographyPath: null }, manifestJson: null });
    expect(ra.html).toBe(rb.html);
  });
});

describe("compile: numbering is continuous across chapters", () => {
  it("numbers figures by chapter and keeps the sequence across chapter boundaries", async () => {
    const result = await build(smallVault());
    const labels = [...result.html.matchAll(/class="figure-label">([^<]*)</g)].map((m) => m[1]);
    expect(labels).toEqual(["Figure 1.1", "Figure 2.1"]);
  });

  it("numbers footnotes continuously across chapters", async () => {
    const result = await build(smallVault());
    const markers = [...result.html.matchAll(/role="doc-noteref">(\d+)<\/sup>/g)].map((m) =>
      Number(m[1]),
    );
    expect(markers).toEqual([1, 2]);
    expect(result.stats.footnotes).toBe(2);
  });

  it("switches to a single continuous figure series when asked", async () => {
    const result = await build(smallVault(), null, { figureNumbering: "continuous" });
    const labels = [...result.html.matchAll(/class="figure-label">([^<]*)</g)].map((m) => m[1]);
    expect(labels).toEqual(["Figure 1", "Figure 2"]);
  });

  it("resolves a cross-reference to a figure placed in a later chapter", async () => {
    const result = await build(smallVault());
    expect(result.html).toMatch(/class="xref xref-figure" href="#fig-second">Figure 2\.1<\/a>/);
  });
});

describe("compile: footnotes", () => {
  it("converts inline notes into real footnote parts", async () => {
    const result = await build(smallVault());
    expect(result.html).toContain('data-part-type="footnote"');
    expect(result.html).toMatch(/<sup data-footnote-ref="fn-[^"]+" role="doc-noteref">/);
  });

  it("does not print its own number in the footnote body", async () => {
    // Word numbers footnotes itself; a manual "1." prefix prints twice.
    const result = await build(smallVault());
    const bodies = [...result.html.matchAll(/<aside data-part-type="footnote"[^>]*>([\s\S]*?)<\/aside>/g)];
    expect(bodies.length).toBeGreaterThan(0);
    for (const [, body] of bodies) {
      expect(body).not.toMatch(/^\s*<p>\s*\d+\.\s/);
    }
  });

  it("resolves citations that live inside a footnote", async () => {
    const result = await build(smallVault());
    const bodies = result.html.slice(result.html.indexOf('data-part-type="footnote"'));
    expect(bodies).toContain("Beta and Gamma 1999");
    expect(result.html).toContain('id="bib-beta1999"');
  });

  it("reports a referenced footnote that was never defined, and invents nothing", async () => {
    const vault = new MemoryVault({
      "Manuscript.md": "---\ntitle: X\n---\n\n- [[A]]\n",
      "A.md": "# A\n\nText[^missing].\n",
    });
    const result = await compile({ vault, options: { ...options, bibliographyPath: null }, manifestJson: null });
    expect(result.ok).toBe(false);
    expect(result.diagnostics.some((d) => d.code === "footnote.undefined")).toBe(true);
    expect(result.html).toContain("mc-missing-footnote");
  });
});

describe("compile: citations", () => {
  it("resolves keys against the bibliography and prints only cited entries", async () => {
    const result = await build(smallVault());
    expect(result.html).toContain("Alpha 2001, p. 3");
    expect(result.html).toContain('id="bib-alpha2001"');
    expect(result.html).not.toContain('id="bib-never2020"');
    expect(result.diagnostics.some((d) => d.code === "bibliography.uncited_entries")).toBe(true);
  });

  it("marks an unresolved key visibly and fails the compile rather than inventing a source", async () => {
    const vault = smallVault();
    vault.set("Ch/One.md", "# Chapter One\n\nA claim [@nosuchkey].\n");
    const result = await build(vault);
    expect(result.ok).toBe(false);
    expect(result.html).toContain("citation-unresolved");
    expect(result.html).toContain("nosuchkey");
    const diag = result.diagnostics.find((d) => d.code === "citation.unresolved");
    expect(diag?.message).toContain("nosuchkey");
  });

  it("numbers citations in order of first appearance in numeric style", async () => {
    const result = await build(smallVault(), null, { citationStyle: "numeric" });
    expect(result.html).toMatch(/>1, p\. 3</);
    expect(result.html).toContain("bib-number");
  });
});

describe("compile: honest failure", () => {
  it("does not report success when a spine link is broken", async () => {
    const vault = smallVault();
    vault.delete("Ch/Two.md");
    const result = await build(vault);
    expect(result.ok).toBe(false);
    expect(result.diagnostics.some((d) => d.code === "spine.broken_link")).toBe(true);
    expect(result.html).not.toContain("Chapter Two");
  });

  it("does not report success when a figure file is missing", async () => {
    const vault = smallVault();
    vault.set("Ch/One.md", "# Chapter One\n\n![[img/ghost.png|A plate that is not there.]]\n");
    const result = await build(vault);
    expect(result.ok).toBe(false);
    expect(result.diagnostics.some((d) => d.code === "figure.missing_file")).toBe(true);
    expect(result.html).toContain("mc-missing-figure");
  });

  it("refuses to guess a figure number for a reference with no figure", async () => {
    const vault = smallVault();
    vault.set("Ch/Two.md", "# Chapter Two\n\nSee [[img/second.png]].\n");
    const result = await build(vault);
    expect(result.html).toContain("[? figure second]");
    expect(result.diagnostics.some((d) => d.code === "figure.unresolved_reference")).toBe(true);
  });

  it("throws a message a human can act on when the spine is missing", async () => {
    const vault = new MemoryVault({});
    await expect(build(vault)).rejects.toThrow(/Spine note not found/);
  });

  it("treats warnings as failures in strict mode only", async () => {
    const vault = smallVault();
    vault.set("Ch/One.md", "# Chapter One\n\n![[img/first.png]]\n"); // no caption -> warning
    const lenient = await build(vault);
    const strict = await build(vault, null, { strict: true });
    expect(lenient.ok).toBe(true);
    expect(strict.ok).toBe(false);
  });
});

describe("compile: transclusion", () => {
  it("pulls in a note that is not on the spine and records the dependency", async () => {
    const vault = smallVault();
    vault.set("Shared/Boilerplate.md", "A shared paragraph.");
    vault.set("Ch/One.md", "# Chapter One\n\n![[Shared/Boilerplate]]\n");
    const result = await build(vault);
    expect(result.html).toContain("A shared paragraph.");
    expect(result.manifest.chapters["Ch/One.md"]!.dependencies).toContain("Shared/Boilerplate.md");
  });

  it("refuses to transclude a note that is already a chapter", async () => {
    const vault = smallVault();
    vault.set("Ch/One.md", "# Chapter One\n\n![[Ch/Two]]\n");
    const result = await build(vault);
    expect(result.diagnostics.some((d) => d.code === "embed.spine_note")).toBe(true);
    const occurrences = result.html.split("Chapter Two").length - 1;
    expect(occurrences).toBeLessThanOrEqual(2); // the chapter itself and its ToC entry
  });
});
