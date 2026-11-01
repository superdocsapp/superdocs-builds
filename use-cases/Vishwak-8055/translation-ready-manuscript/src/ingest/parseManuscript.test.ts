import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parseManuscript, sourceHashOf } from "./parseManuscript.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const aliceText = readFileSync(path.join(__dirname, "../../tests/fixtures/alice.txt"), "utf8");

describe("parseManuscript on the real Alice fixture", () => {
  const parsed = parseManuscript(aliceText);

  it("extracts title and author from the front matter, not by asking the user", () => {
    expect(parsed.metadata.title).toBe("Alice’s Adventures in Wonderland");
    expect(parsed.metadata.author).toBe("Lewis Carroll");
    expect(parsed.metadata.provenance.title?.evidenceQuote).toContain("Alice");
    expect(parsed.metadata.provenance.author?.evidenceQuote).toContain("Lewis Carroll");
  });

  it("infers source language from the text itself, with provenance, not a user prompt", () => {
    expect(parsed.metadata.sourceLanguage).toBe("English");
    expect(parsed.metadata.provenance.sourceLanguage).toBeDefined();
  });

  it("splits into the 10 chapters present in this fixture, in order", () => {
    expect(parsed.chapters).toHaveLength(10);
    expect(parsed.chapters[0]?.title).toBe("Down the Rabbit-Hole");
    expect(parsed.chapters[0]?.index).toBe(1);
    expect(parsed.chapters[9]?.title).toBe("The Lobster Quadrille");
    expect(parsed.chapters[9]?.index).toBe(10);
  });

  it("gives every chapter a stable, unique id", () => {
    const ids = parsed.chapters.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(parsed.chapters[0]?.id).toBe("ch01-down-the-rabbit-hole");
  });

  it("detects italic emphasis marked with underscores and strips the markup from plain text", () => {
    const ch1 = parsed.chapters[0]!;
    const emphasized = ch1.blocks.find((b) => b.hasEmphasis && b.text.includes("very"));
    expect(emphasized).toBeDefined();
    expect(emphasized!.text).not.toContain("_");
    const italicSpan = emphasized!.spans.find((s) => s.emphasis === "italic");
    expect(italicSpan?.text).toBe("very");
  });

  it("classifies the Father William verse as verse, not paragraph, preserving line breaks", () => {
    const ch5 = parsed.chapters.find((c) => c.title === "Advice from a Caterpillar")!;
    const verseBlock = ch5.blocks.find((b) => b.text.includes("Father William"));
    expect(verseBlock?.kind).toBe("verse");
    expect(verseBlock?.text).toContain("\n");
  });

  it("classifies the Lobster Quadrille song as verse", () => {
    const ch10 = parsed.chapters.find((c) => c.title === "The Lobster Quadrille")!;
    const verseBlock = ch10.blocks.find((b) => b.text.includes("Will you, won't you") || b.text.includes("Will you, won’t you"));
    expect(verseBlock?.kind).toBe("verse");
  });

  it("classifies quote-dense exchanges as dialogue", () => {
    const ch6 = parsed.chapters.find((c) => c.title === "Pig and Pepper")!;
    const dialogueBlock = ch6.blocks.find((b) => b.text.includes("Cheshire cat"));
    expect(dialogueBlock?.kind).toBe("dialogue");
  });

  it("classifies narration with only a short embedded quote as paragraph, not dialogue", () => {
    // "The Hatter opened his eyes very wide... but all he said was, 'Why is a
    // raven like a writing-desk?'" is narration that happens to end on a
    // quote -- most of the block is narration, so it should NOT be tagged
    // dialogue just because it contains quotation marks.
    const ch7 = parsed.chapters.find((c) => c.title === "A Mad Tea-Party")!;
    const narrationBlock = ch7.blocks.find((b) => b.text.includes("Why is a raven"));
    expect(narrationBlock?.kind).toBe("paragraph");
  });

  it("never mutates the raw source while parsing", () => {
    expect(parsed.rawSource).toBe(aliceText);
  });

  it("produces a stable content hash for the same input", () => {
    const again = parseManuscript(aliceText);
    expect(again.sourceHash).toBe(parsed.sourceHash);
    expect(parsed.sourceHash).toBe(sourceHashOf(aliceText));
  });

  it("produces a different hash for different content (sanity check, not a real collision test)", () => {
    const otherHash = sourceHashOf(aliceText + " ");
    expect(otherHash).not.toBe(parsed.sourceHash);
  });
});
