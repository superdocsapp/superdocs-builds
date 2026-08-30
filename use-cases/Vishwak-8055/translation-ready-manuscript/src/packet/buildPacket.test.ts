import { describe, expect, it } from "vitest";
import type { ParsedManuscript, StyleNote, TermCandidate } from "../types.js";
import { buildTranslationPacket } from "./buildPacket.js";

function manuscript(): ParsedManuscript {
  return {
    metadata: { title: "Alice's Adventures in Wonderland", author: "Lewis Carroll", sourceLanguage: "English", provenance: {} },
    rawSource: "",
    sourceHash: "abc123",
    chapters: [
      {
        id: "ch01",
        index: 1,
        title: "Down the Rabbit-Hole",
        blocks: [
          {
            id: "ch01-b0",
            kind: "paragraph",
            text: "There was nothing so very remarkable in that.",
            spans: [{ text: "There was nothing so " }, { text: "very", emphasis: "italic" }, { text: " remarkable in that." }],
            hasEmphasis: true,
          },
          {
            id: "ch01-b1",
            kind: "verse",
            text: "How doth the little crocodile\nImprove his shining tail",
            spans: [{ text: "How doth the little crocodile\nImprove his shining tail" }],
            hasEmphasis: false,
          },
        ],
      },
    ],
  };
}

const styleNote: StyleNote = {
  register: "Literary",
  narrativeVoice: "Ironic third person",
  dialogue: "Argumentative",
  tone: "Whimsical",
  wordplay: "Frequent",
  verse: "Parody poems",
  formatting: "Italics for emphasis",
  translationConsiderations: "Needs transcreation for puns",
  additionalNotes: [],
  status: "suggested",
};

describe("buildTranslationPacket", () => {
  it("carries manuscript title/target language through and stamps a source hash for later integrity checks", () => {
    const packet = buildTranslationPacket({
      manuscript: manuscript(),
      allTerms: [],
      confirmedRules: [],
      styleNote,
      targetLanguage: "Spanish",
      targetLocale: "Spain",
    });
    expect(packet.manuscriptTitle).toBe("Alice's Adventures in Wonderland");
    expect(packet.targetLanguage).toBe("Spanish");
    expect(packet.targetLocale).toBe("Spain");
    expect(packet.sourceHash).toBe("abc123");
  });

  it("renders clean source HTML with chunk ids on the title, chapter headings, and every block", () => {
    const packet = buildTranslationPacket({
      manuscript: manuscript(),
      allTerms: [],
      confirmedRules: [],
      styleNote,
      targetLanguage: "Spanish",
    });
    expect(packet.cleanSourceHtml).toContain('data-chunk-id="title"');
    expect(packet.cleanSourceHtml).toContain('data-chunk-id="ch01-heading"');
    expect(packet.cleanSourceHtml).toContain('data-chunk-id="ch01-b0"');
    expect(packet.cleanSourceHtml).toContain("<em>very</em>");
  });

  it("escapes HTML-significant characters in source text rather than injecting them raw", () => {
    const ms = manuscript();
    ms.chapters[0]!.blocks[0]!.text = "Alice said <b>hello</b> & goodbye";
    ms.chapters[0]!.blocks[0]!.spans = [{ text: "Alice said <b>hello</b> & goodbye" }];
    const packet = buildTranslationPacket({ manuscript: ms, allTerms: [], confirmedRules: [], styleNote, targetLanguage: "Spanish" });
    expect(packet.cleanSourceHtml).toContain("&lt;b&gt;hello&lt;/b&gt;");
    expect(packet.cleanSourceHtml).not.toContain("<b>hello</b>");
  });

  it("generates a formatting guidance rule for the emphasized block, referencing the emphasized text", () => {
    const packet = buildTranslationPacket({ manuscript: manuscript(), allTerms: [], confirmedRules: [], styleNote, targetLanguage: "Spanish" });
    const italicRule = packet.formattingGuidance.find((r) => r.formatting === "italic");
    expect(italicRule?.meaning).toContain("very");
    expect(italicRule?.translationRequirement).toMatch(/Preserve italic/);
  });

  it("generates a formatting guidance rule for the verse block", () => {
    const packet = buildTranslationPacket({ manuscript: manuscript(), allTerms: [], confirmedRules: [], styleNote, targetLanguage: "Spanish" });
    const verseRule = packet.formattingGuidance.find((r) => r.formatting === "verse_structure");
    expect(verseRule).toBeDefined();
    expect(verseRule?.translationRequirement).toMatch(/remain verse/);
  });

  it("includes the full term base (any status) so a translator sees suggested terms too, not only confirmed ones", () => {
    const terms: TermCandidate[] = [
      {
        id: "t1",
        canonicalForm: "White Rabbit",
        category: "character",
        occurrences: [],
        meaning: "A recurring character.",
        pronunciation: { value: null, confidence: null, note: "n/a" },
        suggestedPolicy: "preserve_consistently",
        confidence: "high",
        status: "suggested",
      },
    ];
    const packet = buildTranslationPacket({ manuscript: manuscript(), allTerms: terms, confirmedRules: [], styleNote, targetLanguage: "Spanish" });
    expect(packet.termBase).toHaveLength(1);
    expect(packet.termBase[0]?.status).toBe("suggested");
  });
});
