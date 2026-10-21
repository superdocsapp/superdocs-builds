import { describe, expect, it } from "vitest";
import type { Chapter, TermCandidate } from "../types.js";
import type { ChapterAlignmentResult } from "../align/alignTranslation.js";
import { buildDoNotTranslateRules, confirmTerm, countOccurrences, levenshteinDistance, rejectTerm, verifyProtectedTerms } from "./protectedTerms.js";

function makeTerm(overrides: Partial<TermCandidate> & Pick<TermCandidate, "id" | "canonicalForm">): TermCandidate {
  return {
    category: "invented_word",
    occurrences: [],
    meaning: "A magical event specific to this world.",
    pronunciation: { value: null, confidence: null, note: "Not confidently inferable from source." },
    suggestedPolicy: "do_not_translate",
    confidence: "high",
    status: "suggested",
    ...overrides,
  };
}

function chapter(id: string, title: string, blocks: Array<{ id: string; text: string }>): Chapter {
  return {
    id,
    index: 1,
    title,
    blocks: blocks.map((b) => ({ id: b.id, kind: "paragraph", text: b.text, spans: [{ text: b.text }], hasEmphasis: false })),
  };
}

function identityAlignment(sourceChapter: Chapter, translatedChapter: Chapter): ChapterAlignmentResult {
  return {
    sourceChapterId: sourceChapter.id,
    translatedChapterId: translatedChapter.id,
    blockAlignments: sourceChapter.blocks.map((b, i) => ({
      sourceChapterId: sourceChapter.id,
      sourceBlockId: b.id,
      translatedBlockId: translatedChapter.blocks[i]?.id ?? null,
      confidence: "high",
      reviewRequired: false,
    })),
  };
}

describe("term lifecycle: confirmTerm / rejectTerm", () => {
  it("confirms a suggested term, stamping reviewer and timestamp", () => {
    const term = makeTerm({ id: "t1", canonicalForm: "Aetherfall" });
    const confirmed = confirmTerm(term, "rights-manager@example.com");
    expect(confirmed.status).toBe("confirmed");
    expect(confirmed.reviewedBy).toBe("rights-manager@example.com");
    expect(confirmed.reviewedAt).toBeDefined();
  });

  it("refuses to confirm a term that is not currently suggested", () => {
    const term = makeTerm({ id: "t1", canonicalForm: "Aetherfall", status: "confirmed" });
    expect(() => confirmTerm(term, "someone")).toThrow(/not "suggested"/);
  });

  it("refuses to confirm an already-rejected term (no silent resurrection)", () => {
    const term = makeTerm({ id: "t1", canonicalForm: "Aetherfall", status: "rejected" });
    expect(() => confirmTerm(term, "someone")).toThrow();
  });

  it("rejects a suggested term and records who/when", () => {
    const term = makeTerm({ id: "t1", canonicalForm: "Xylora" });
    const rejected = rejectTerm(term, "reviewer@example.com");
    expect(rejected.status).toBe("rejected");
    expect(rejected.reviewedBy).toBe("reviewer@example.com");
  });

  it("an edited canonical form on confirmation is recorded as an override, not silently applied", () => {
    const term = makeTerm({ id: "t1", canonicalForm: "Aetherfal" }); // typo in the AI suggestion
    const confirmed = confirmTerm(term, "reviewer", { canonicalForm: "Aetherfall" });
    expect(confirmed.canonicalForm).toBe("Aetherfal"); // original suggestion preserved for audit
    expect(confirmed.confirmedOverride?.canonicalForm).toBe("Aetherfall"); // correction is explicit
  });
});

describe("buildDoNotTranslateRules", () => {
  it("builds a rule only for confirmed terms, skipping suggested and rejected", () => {
    const suggested = makeTerm({ id: "t1", canonicalForm: "Suggested" });
    const confirmed = confirmTerm(makeTerm({ id: "t2", canonicalForm: "Aetherfall" }), "reviewer");
    const rejected = rejectTerm(makeTerm({ id: "t3", canonicalForm: "Rejected" }), "reviewer");
    const rules = buildDoNotTranslateRules([suggested, confirmed, rejected]);
    expect(rules).toHaveLength(1);
    expect(rules[0]?.canonicalForm).toBe("Aetherfall");
    expect(rules[0]?.termId).toBe("t2");
  });

  it("applies a confirmation-time override to the built rule", () => {
    const confirmed = confirmTerm(makeTerm({ id: "t1", canonicalForm: "Aetherfal" }), "reviewer", { canonicalForm: "Aetherfall" });
    const rules = buildDoNotTranslateRules([confirmed]);
    expect(rules[0]?.canonicalForm).toBe("Aetherfall");
  });

  it("does not build a rule for a confirmed term whose policy is translate_normally", () => {
    const confirmed = confirmTerm(makeTerm({ id: "t1", canonicalForm: "ordinary word", suggestedPolicy: "translate_normally" }), "reviewer");
    expect(buildDoNotTranslateRules([confirmed])).toHaveLength(0);
  });
});

describe("countOccurrences", () => {
  it("counts whole-word matches only, not substrings", () => {
    expect(countOccurrences("Aetherfall struck the Aetherfallen village", "Aetherfall", true)).toBe(1);
  });

  it("respects case sensitivity", () => {
    expect(countOccurrences("aetherfall and Aetherfall", "Aetherfall", true)).toBe(1);
    expect(countOccurrences("aetherfall and Aetherfall", "Aetherfall", false)).toBe(2);
  });

  it("handles curly apostrophes as word characters, not boundaries", () => {
    expect(countOccurrences("the Mock Turtle’s story", "Turtle’s", true)).toBe(1);
  });
});

describe("levenshteinDistance", () => {
  it("is 0 for identical strings", () => {
    expect(levenshteinDistance("Aetherfall", "Aetherfall")).toBe(0);
  });

  it("is small (within the closest-word matching threshold) for the Aetherfall -> Etherfall corruption", () => {
    // Dropping the leading "A" from "Aetherfall" leaves "etherfall" (lowercase e);
    // getting to "Etherfall" needs that one substitution too, so distance is 2, not 1.
    // Still comfortably inside findClosestWord's threshold of 2 -- see the flagship
    // verifyProtectedTerms test below, which confirms this is actually surfaced as evidence.
    expect(levenshteinDistance("Aetherfall", "Etherfall")).toBe(2);
  });
});

describe("verifyProtectedTerms — the flagship Aetherfall / Etherfall scenario", () => {
  const sourceChapter = chapter("ch04", "Chapter Four", [
    { id: "s1", text: "The sky split open as Aetherfall began, and every villager looked up." },
  ]);

  it("flags a HIGH-severity mismatch, confirmed rule, when a confirmed protected term is mistranslated", () => {
    const confirmedTerm = confirmTerm(
      makeTerm({ id: "t-aetherfall", canonicalForm: "Aetherfall", category: "invented_word", suggestedPolicy: "do_not_translate" }),
      "rights-manager",
    );
    const rules = buildDoNotTranslateRules([confirmedTerm]);
    const translatedChapter = chapter("tch04", "Chapitre Quatre", [
      { id: "t1", text: "Le ciel s'est ouvert alors que Etherfall commençait, et chaque villageois a levé les yeux." },
    ]);
    const findings = verifyProtectedTerms({
      rules,
      allTerms: [confirmedTerm],
      sourceChapters: [sourceChapter],
      translatedChapters: [translatedChapter],
      chapterAlignments: [identityAlignment(sourceChapter, translatedChapter)],
    });

    expect(findings).toHaveLength(1);
    const finding = findings[0]!;
    expect(finding.severity).toBe("high");
    expect(finding.ruleStatus).toBe("confirmed");
    expect(finding.expected).toBe("Aetherfall");
    expect(finding.actual).toBe("Etherfall"); // the closest-word evidence search finds the actual mistranslation
    expect(finding.chapterTitle).toBe("Chapter Four");
    expect(finding.recommendedAction).toMatch(/Restore the approved canonical term/);
  });

  it("produces NO finding when the confirmed term survived translation intact", () => {
    const confirmedTerm = confirmTerm(makeTerm({ id: "t-aetherfall", canonicalForm: "Aetherfall" }), "rights-manager");
    const rules = buildDoNotTranslateRules([confirmedTerm]);
    const translatedChapter = chapter("tch04", "Chapitre Quatre", [
      { id: "t1", text: "Le ciel s'est ouvert alors que Aetherfall commençait." },
    ]);
    const findings = verifyProtectedTerms({
      rules,
      allTerms: [confirmedTerm],
      sourceChapters: [sourceChapter],
      translatedChapters: [translatedChapter],
      chapterAlignments: [identityAlignment(sourceChapter, translatedChapter)],
    });
    expect(findings).toHaveLength(0);
  });

  it("still surfaces a violation of an unconfirmed (suggested) term, but with low severity and a 'please decide' action, never the authority of an approved rule", () => {
    const suggestedTerm = makeTerm({ id: "t-xylora", canonicalForm: "Xylora", status: "suggested" });
    const sourceCh = chapter("ch05", "Chapter Five", [{ id: "s1", text: "Xylora rose above the horizon." }]);
    const translatedCh = chapter("tch05", "Chapitre Cinq", [{ id: "t1", text: "Xylore se leva au-dessus de l'horizon." }]);
    const findings = verifyProtectedTerms({
      rules: [], // never confirmed, so no enforceable rule exists
      allTerms: [suggestedTerm],
      sourceChapters: [sourceCh],
      translatedChapters: [translatedCh],
      chapterAlignments: [identityAlignment(sourceCh, translatedCh)],
    });
    expect(findings).toHaveLength(1);
    expect(findings[0]?.ruleStatus).toBe("suggested");
    expect(findings[0]?.severity).toBe("low");
    expect(findings[0]?.recommendedAction).toMatch(/has not been reviewed yet/);
  });

  it("produces NO finding for a rejected term even if it was changed in translation -- a human already decided not to protect it", () => {
    const rejectedTerm = rejectTerm(makeTerm({ id: "t-ordinary", canonicalForm: "Wonderland" }), "reviewer");
    const sourceCh = chapter("ch01", "Chapter One", [{ id: "s1", text: "Welcome to Wonderland." }]);
    const translatedCh = chapter("tch01", "Chapitre Un", [{ id: "t1", text: "Bienvenue au Pays des Merveilles." }]);
    const findings = verifyProtectedTerms({
      rules: [],
      allTerms: [rejectedTerm],
      sourceChapters: [sourceCh],
      translatedChapters: [translatedCh],
      chapterAlignments: [identityAlignment(sourceCh, translatedCh)],
    });
    expect(findings).toHaveLength(0);
  });

  it("flags a HIGH-severity finding when the entire chapter is missing from the returned translation", () => {
    const confirmedTerm = confirmTerm(makeTerm({ id: "t-aetherfall", canonicalForm: "Aetherfall" }), "rights-manager");
    const rules = buildDoNotTranslateRules([confirmedTerm]);
    const findings = verifyProtectedTerms({
      rules,
      allTerms: [confirmedTerm],
      sourceChapters: [sourceChapter],
      translatedChapters: [], // translator dropped the chapter entirely
      chapterAlignments: [{ sourceChapterId: sourceChapter.id, translatedChapterId: null, blockAlignments: [] }],
    });
    expect(findings).toHaveLength(1);
    expect(findings[0]?.actual).toMatch(/missing entirely/);
    expect(findings[0]?.severity).toBe("high");
  });
});
