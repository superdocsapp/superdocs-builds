/** Unit tests for the pieces the rest of the system trusts to be right. */

import { describe, expect, it } from "vitest";
import { sha256Hex } from "../src/core/sha256";
import { parseAuthors, parseBibtex } from "../src/core/bibtex";
import { formatAuthorNames, renderBibEntry, replaceCitations } from "../src/core/citations";
import { normaliseHeadings, transformCallouts, replaceAsync } from "../src/core/render";
import { parseSpine, splitFrontmatter } from "../src/core/spine";
import { slugify, stripTags, uniqueSlug, wordCount } from "../src/core/util";
import { toText, wordDiff } from "../src/core/diff";
import { MemoryVault } from "./helpers";

describe("sha256", () => {
  // FIPS 180-4 test vectors. The cache and the image de-duplication both rest on this.
  it("matches the published vectors", () => {
    expect(sha256Hex("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
    expect(sha256Hex("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")).toBe(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    );
  });

  it("handles multi-byte text and long input", () => {
    expect(sha256Hex("café — naïve 日本語")).toHaveLength(64);
    expect(sha256Hex("a".repeat(1_000))).toBe(
      "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3",
    );
  });

  it("hashes bytes and the equivalent string identically", () => {
    expect(sha256Hex(new TextEncoder().encode("abc"))).toBe(sha256Hex("abc"));
  });
});

describe("bibtex", () => {
  it("reads the entry shapes a working .bib file actually contains", () => {
    const db = parseBibtex(
      `
@string{pub = {Press One}}
@comment{ignore me}
@book{a2001,
  author = {Alpha, Ada and Beta, Bo},
  title = {A {Braced} Title},
  year = {2001},
  publisher = pub,
}
@article{b1999,
  author  = "Gamma, Gus",
  title   = "Quoted Title",
  journal = "Journal",
  year    = 1999,
}
`,
      "refs.bib",
    );
    expect([...db.entries.keys()]).toEqual(["a2001", "b1999"]);
    expect(db.entries.get("a2001")!.fields.publisher).toBe("Press One");
    expect(db.entries.get("a2001")!.title).toBe("A Braced Title");
    expect(db.entries.get("b1999")!.year).toBe("1999");
    expect(db.diagnostics).toHaveLength(0);
  });

  it("decodes the common LaTeX escapes", () => {
    const db = parseBibtex(`@book{x, author = {Tavares, Lu\\'{i}s}, title = {A--B \\& C}, year = {2000}}`, "r.bib");
    const entry = db.entries.get("x")!;
    expect(entry.authors[0]!.first.normalize("NFC")).toBe("Luís");
    expect(entry.title).toBe("A–B & C");
  });

  it("reports a duplicate key instead of silently keeping one", () => {
    const db = parseBibtex(`@book{x, title={One}, year={2000}}\n@book{x, title={Two}, year={2001}}`, "r.bib");
    expect(db.entries.get("x")!.title).toBe("One");
    expect(db.diagnostics.some((d) => d.code === "bibtex.duplicate_key")).toBe(true);
  });

  it("survives a truncated file and says so", () => {
    const db = parseBibtex(`@book{x, title = {Unclosed`, "r.bib");
    expect(db.diagnostics.some((d) => d.code.startsWith("bibtex."))).toBe(true);
  });

  it("parses author lists in both orders, and 'and others'", () => {
    expect(parseAuthors("Alpha, Ada and Bo Beta and others")).toEqual([
      { last: "Alpha", first: "Ada", isOthers: false },
      { last: "Beta", first: "Bo", isOthers: false },
      { last: "others", first: "", isOthers: true },
    ]);
  });
});

describe("citation rendering", () => {
  const entry = (over: Record<string, unknown> = {}) =>
    ({
      key: "k",
      type: "book",
      fields: {},
      authors: [{ last: "Alpha", first: "Ada", isOthers: false }],
      year: "2001",
      title: "T",
      line: 1,
      ...over,
    }) as never;

  it("names one, two, three authors and then et al.", () => {
    expect(formatAuthorNames(entry())).toBe("Alpha");
    expect(
      formatAuthorNames(
        entry({ authors: [{ last: "Alpha" }, { last: "Beta" }] }),
      ),
    ).toBe("Alpha and Beta");
    expect(
      formatAuthorNames(entry({ authors: [{ last: "A" }, { last: "B" }, { last: "C" }, { last: "D" }] })),
    ).toBe("A et al.");
    expect(
      formatAuthorNames(entry({ authors: [{ last: "A" }, { last: "others", isOthers: true }] })),
    ).toBe("A et al.");
  });

  it("does not double a full stop after et al.", () => {
    const html = renderBibEntry(
      entry({ authors: [{ last: "Tavares", first: "Luís" }, { last: "others", isOthers: true }] }),
      "author-date",
      1,
    );
    expect(html).not.toContain("..");
  });

  it("finds every citation form", () => {
    const seen: string[] = [];
    replaceCitations(
      "Text [@a2001], more [@b1999, p. 4; -@c2000], and @d1998 said so. Not an email: x@y.com",
      (refs) => {
        seen.push(...refs.map((r) => `${r.citeKey}${r.locator ? `/${r.locator}` : ""}${r.suppressAuthor ? "-" : ""}`));
        return "[CITE]";
      },
    );
    expect(seen).toEqual(["a2001", "b1999/p. 4", "c2000-", "d1998"]);
  });
});

describe("heading normalisation", () => {
  it("shifts a note's levels to sit under its chapter level", () => {
    expect(normaliseHeadings("## A\n\n### B\n", 1)).toBe("## A\n\n### B\n");
    expect(normaliseHeadings("# A\n\n## B\n", 1)).toBe("## A\n\n### B\n");
  });

  it("closes gaps so no level is skipped", () => {
    expect(normaliseHeadings("## A\n\n##### B\n", 1)).toBe("## A\n\n### B\n");
  });

  it("clamps at h6 rather than emitting h7", () => {
    expect(normaliseHeadings("# A\n\n## B\n\n### C\n", 5)).toBe("###### A\n\n###### B\n\n###### C\n");
  });

  it("leaves a note with no headings alone", () => {
    expect(normaliseHeadings("Just prose.\n", 1)).toBe("Just prose.\n");
  });

  it("ignores a bare hash that is not a heading", () => {
    expect(normaliseHeadings("#hashtag\n\n# Real\n", 1)).toBe("#hashtag\n\n## Real\n");
  });
});

describe("callouts", () => {
  it("turns an Obsidian callout header into a titled blockquote", () => {
    expect(transformCallouts("> [!note] A Title\n> Body")).toBe(
      '> <strong class="callout-title callout-note">A Title</strong>\n> Body',
    );
  });

  it("defaults the title to the callout type", () => {
    expect(transformCallouts("> [!warning]")).toContain(">Warning<");
  });

  it("leaves an unknown type as a note rather than dropping it", () => {
    expect(transformCallouts("> [!nonsense] Hi")).toContain("callout-note");
  });
});

describe("spine parsing", () => {
  const vault = () =>
    new MemoryVault({
      "Manuscript.md": "",
      "A.md": "",
      "B.md": "",
      "C.md": "",
    });

  it("reads regions, parts, order and nesting", async () => {
    const src = `---
title: T
---

## Front Matter
- [[A]]

## Part One
1. [[B]]
   - [[C]]
`;
    const parsed = await parseSpine(vault(), "Manuscript.md", src);
    expect(parsed.entries.map((e) => [e.path, e.region, e.part, e.nested])).toEqual([
      ["A.md", "front", null, false],
      ["B.md", "body", "Part One", false],
      ["C.md", "body", "Part One", true],
    ]);
  });

  it("takes the alias as the chapter title", async () => {
    const parsed = await parseSpine(vault(), "Manuscript.md", "- [[A|A Better Title]]\n");
    expect(parsed.entries[0]!.title).toBe("A Better Title");
  });

  it("reports a broken link rather than skipping it quietly", async () => {
    const parsed = await parseSpine(vault(), "Manuscript.md", "- [[Nope]]\n");
    expect(parsed.diagnostics[0]!.code).toBe("spine.broken_link");
    expect(parsed.diagnostics[0]!.line).toBe(1);
  });

  it("refuses to list the same note twice", async () => {
    const parsed = await parseSpine(vault(), "Manuscript.md", "- [[A]]\n- [[A]]\n");
    expect(parsed.entries).toHaveLength(1);
    expect(parsed.diagnostics.some((d) => d.code === "spine.duplicate_entry")).toBe(true);
  });

  it("ignores links inside a fenced code block", async () => {
    const parsed = await parseSpine(vault(), "Manuscript.md", "```\n- [[A]]\n```\n- [[B]]\n");
    expect(parsed.entries.map((e) => e.path)).toEqual(["B.md"]);
  });

  it("says plainly when there is no spine to read", async () => {
    const parsed = await parseSpine(vault(), "Manuscript.md", "Just some prose.\n");
    expect(parsed.diagnostics[0]!.code).toBe("spine.empty");
    expect(parsed.diagnostics[0]!.message).toContain("[[wikilinks]]");
  });

  it("splits frontmatter without eating a horizontal rule", () => {
    expect(splitFrontmatter("---\na: 1\n---\nBody\n").frontmatter).toBe("a: 1");
    expect(splitFrontmatter("Body\n\n---\n\nMore\n").frontmatter).toBeNull();
  });
});

describe("utilities", () => {
  it("makes stable, collision-free anchors", () => {
    expect(slugify("The Cartographer's Dilemma")).toBe("the-cartographer-s-dilemma");
    expect(slugify("Café Naïve")).toBe("cafe-naive");
    expect(slugify("!!!")).toBe("x");
    const taken = new Set<string>();
    expect(uniqueSlug("a", taken)).toBe("a");
    expect(uniqueSlug("a", taken)).toBe("a-2");
    expect(uniqueSlug("a", taken)).toBe("a-3");
  });

  it("counts words without counting markup", () => {
    expect(wordCount("<p>one two</p><p>three</p>")).toBe(3);
    expect(stripTags("<p>a</p><p>b</p>")).toBe("a b");
    expect(wordCount("")).toBe(0);
  });
});

describe("the review diff", () => {
  it("marks only what changed", () => {
    const parts = wordDiff("the quick brown fox", "the slow brown fox");
    expect(parts.filter((p) => p.kind === "del").map((p) => p.text.trim())).toEqual(["quick"]);
    expect(parts.filter((p) => p.kind === "add").map((p) => p.text.trim())).toEqual(["slow"]);
    expect(parts.filter((p) => p.kind === "same").map((p) => p.text).join("")).toContain("brown fox");
  });

  it("handles an empty side", () => {
    expect(wordDiff("", "new text").every((p) => p.kind === "add")).toBe(true);
    expect(wordDiff("old text", "").every((p) => p.kind === "del")).toBe(true);
  });

  it("shows prose, not tags", () => {
    expect(toText("<p>Hello <em>there</em></p><p>Second</p>")).toBe("Hello there\nSecond");
    expect(toText("<p>a &amp; b</p>")).toBe("a & b");
  });
});

describe("replaceAsync", () => {
  it("keeps matches in order and rebuilds the string exactly", async () => {
    const out = await replaceAsync("a1b2c3", /\d/g, async (m) => `[${m}]`);
    expect(out).toBe("a[1]b[2]c[3]");
  });

  it("returns the input untouched when nothing matches", async () => {
    expect(await replaceAsync("abc", /\d/g, async () => "x")).toBe("abc");
  });
});
