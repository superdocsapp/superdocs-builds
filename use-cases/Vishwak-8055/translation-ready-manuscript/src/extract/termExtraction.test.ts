import { describe, expect, it } from "vitest";
import type { ParsedManuscript } from "../types.js";
import { MockLlmProvider } from "./llmProvider.js";
import { extractTermCandidates, generateStyleNote } from "./termExtraction.js";

function manuscript(): ParsedManuscript {
  return {
    metadata: { title: "Test Manuscript", author: "Test Author", sourceLanguage: "English", provenance: {} },
    rawSource: "",
    sourceHash: "test",
    chapters: [
      {
        id: "ch01",
        index: 1,
        title: "Chapter One",
        blocks: [
          { id: "ch01-b0", kind: "paragraph", text: "The sky split open as Aetherfall began over the village.", spans: [], hasEmphasis: false },
          { id: "ch01-b1", kind: "paragraph", text: "Xylora rose slowly above the eastern hills that night.", spans: [], hasEmphasis: false },
        ],
      },
    ],
  };
}

describe("extractTermCandidates — evidence verification", () => {
  it("keeps a candidate whose claimed evidence genuinely appears in the source, unmodified confidence", async () => {
    const provider = new MockLlmProvider([
      {
        canonicalForm: "Aetherfall",
        category: "invented_word",
        meaning: "A magical sky-event.",
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: "do_not_translate",
        confidence: "high",
        occurrences: [{ chapterId: "ch01", evidenceQuote: "Aetherfall began over the village" }],
      },
    ]);
    const { terms, warnings } = await extractTermCandidates(provider, manuscript());
    expect(warnings).toHaveLength(0);
    expect(terms).toHaveLength(1);
    expect(terms[0]).toMatchObject({ canonicalForm: "Aetherfall", status: "suggested", confidence: "high" });
    expect(terms[0]?.occurrences).toHaveLength(1);
    expect(terms[0]?.occurrences[0]?.chapterId).toBe("ch01");
  });

  it("DROPS a candidate whose claimed evidence quote does not actually appear anywhere in the source — a hallucination, not evidence", async () => {
    const provider = new MockLlmProvider([
      {
        canonicalForm: "Glimmerwrath",
        category: "invented_word",
        meaning: "A term the model invented that isn't actually in the text.",
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: "do_not_translate",
        confidence: "high",
        occurrences: [{ chapterId: "ch01", evidenceQuote: "the Glimmerwrath consumed the kingdom" }],
      },
    ]);
    const { terms, warnings } = await extractTermCandidates(provider, manuscript());
    expect(terms).toHaveLength(0);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]?.canonicalForm).toBe("Glimmerwrath");
    expect(warnings[0]?.reason).toMatch(/could be found verbatim/);
  });

  it("keeps a candidate with partially-verified evidence but drops the unverified occurrence and downgrades confidence", async () => {
    const provider = new MockLlmProvider([
      {
        canonicalForm: "Xylora",
        category: "place",
        meaning: "A location.",
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: "preserve_consistently",
        confidence: "high",
        occurrences: [
          { chapterId: "ch01", evidenceQuote: "Xylora rose slowly above the eastern hills" }, // real
          { chapterId: "ch01", evidenceQuote: "Xylora burned brightly over the capital" }, // fabricated
        ],
      },
    ]);
    const { terms, warnings } = await extractTermCandidates(provider, manuscript());
    expect(terms).toHaveLength(1);
    expect(terms[0]?.occurrences).toHaveLength(1); // only the real one survives
    expect(terms[0]?.confidence).toBe("medium"); // downgraded from high
    expect(warnings).toHaveLength(1);
    expect(warnings[0]?.reason).toMatch(/Only 1 of 2 claimed occurrences verified/);
  });

  it("drops a malformed suggestion (invalid category) rather than crashing or silently coercing it", async () => {
    const provider = new MockLlmProvider([
      {
        canonicalForm: "Something",
        // @ts-expect-error -- deliberately invalid to test the guard
        category: "not-a-real-category",
        meaning: "x",
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: "do_not_translate",
        confidence: "high",
        occurrences: [],
      },
    ]);
    const { terms, warnings } = await extractTermCandidates(provider, manuscript());
    expect(terms).toHaveLength(0);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]?.reason).toMatch(/Malformed suggestion/);
  });

  it("never returns a candidate with status other than 'suggested', regardless of the provider's reported confidence", async () => {
    const provider = new MockLlmProvider([
      {
        canonicalForm: "Aetherfall",
        category: "invented_word",
        meaning: "x",
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: "do_not_translate",
        confidence: "high",
        occurrences: [{ chapterId: "ch01", evidenceQuote: "Aetherfall began" }],
      },
    ]);
    const { terms } = await extractTermCandidates(provider, manuscript());
    expect(terms[0]?.status).toBe("suggested");
  });
});

describe("generateStyleNote", () => {
  it("fills missing fields with an explicit placeholder rather than leaving them blank or fabricating content", async () => {
    const provider = new MockLlmProvider(
      [],
      {
        register: "",
        narrativeVoice: "Real value here.",
        dialogue: "",
        tone: "",
        wordplay: "",
        verse: "",
        formatting: "",
        translationConsiderations: "",
        additionalNotes: [],
      },
    );
    const note = await generateStyleNote(provider, manuscript());
    expect(note.register).toBe("(not determined for this manuscript)");
    expect(note.narrativeVoice).toBe("Real value here.");
    expect(note.status).toBe("suggested");
  });
});
