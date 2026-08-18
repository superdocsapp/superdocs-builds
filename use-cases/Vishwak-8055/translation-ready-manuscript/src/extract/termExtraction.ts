import type { Chapter, ConfidenceLevel, ParsedManuscript, PronunciationNote, SourceLocation, StyleNote, TermCandidate, TermCategory, TranslationPolicy } from "../types.js";
import type { LlmProvider, RawStyleNoteSuggestion, RawTermSuggestion } from "./llmProvider.js";

/**
 * The LLM proposes; this module verifies before anything is even shown to a
 * human as a candidate. Every occurrence a provider claims must be checked
 * against the actual chapter text -- an evidence quote that doesn't appear
 * in the source is not evidence, it's a hallucination, and the candidate is
 * dropped (or downgraded) rather than passed through. This is what "AI
 * suggestion" means structurally in this codebase, not just by convention.
 */

const VALID_CATEGORIES = new Set<TermCategory>([
  "character", "place", "organization", "object", "invented_word", "coined_phrase", "title", "other",
]);
const VALID_POLICIES = new Set<TranslationPolicy>(["do_not_translate", "preserve_consistently", "translate_normally"]);
const VALID_CONFIDENCE = new Set<ConfidenceLevel>(["high", "medium", "low"]);

const COMMON_NON_TERMS = new Set([
  "the", "this", "that", "these", "those", "there", "their", "they", "either", "first", "well", "which", "down", "would",
  "please", "however", "what", "just", "after", "with", "everything", "said", "such", "come", "mine", "everybody", "improve",
  "presently", "suddenly", "poor", "english", "chapter", "part", "book", "volume", "contents", "author", "preface", "introduction",
  "she", "he", "it", "and", "but", "at", "in", "on", "a", "an", "by", "for", "from", "to", "of", "as", "or", "if",
  "when", "where", "who", "why", "how", "can", "could", "will", "have", "has", "had", "do", "did", "does", "is", "was", "were",
  "i’ll", "i’ve", "i’m", "i’d", "you’re", "we’re", "they’re",
]);

function termLooksLikeOrdinaryVocabulary(term: string): boolean {
  const normalized = term.trim().toLocaleLowerCase();
  if (COMMON_NON_TERMS.has(normalized)) return true;
  return normalized.split(/\s+/).length === 1 && /^[a-z][a-z'-]+$/i.test(term) && term.length < 4;
}

function hasStrongSourceSignal(term: string, manuscript: ParsedManuscript, category: TermCategory): string[] {
  const signals: string[] = [];
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(?<![\\p{L}\\p{N}_’'])${escaped}(?![\\p{L}\\p{N}_’'])`, "gu");
  let occurrences = 0;
  let nonSentenceInitial = 0;
  let italic = false;
  let allCaps = term.length >= 3 && term === term.toUpperCase() && /[A-Z]/.test(term);
  for (const chapter of manuscript.chapters) {
    for (const block of chapter.blocks) {
      for (const match of block.text.matchAll(re)) {
        occurrences += 1;
        const prefix = block.text.slice(0, match.index ?? 0).trimEnd();
        const sentenceInitial = !prefix || /[.!?]$/.test(prefix);
        if (!sentenceInitial) nonSentenceInitial += 1;
      }
      if (block.spans.some((span) => span.emphasis === "italic" && span.text.toLocaleLowerCase().includes(term.toLocaleLowerCase()))) italic = true;
    }
  }
  if (term.includes(" ")) signals.push("multi-word expression");
  if (nonSentenceInitial > 0) signals.push("used away from sentence-initial position");
  if (occurrences >= 2) signals.push("repeated in source");
  if (allCaps) signals.push("intentional capitalization");
  if (italic) signals.push("emphasis formatting");
  if (category === "invented_word" || category === "coined_phrase") signals.push("provider classified as work-specific language");
  return signals;
}

function shouldKeepSuggestion(suggestion: RawTermSuggestion, manuscript: ParsedManuscript): { keep: boolean; signals: string[] } {
  const form = suggestion.canonicalForm.trim();
  if (termLooksLikeOrdinaryVocabulary(form)) return { keep: false, signals: [] };
  const signals = hasStrongSourceSignal(form, manuscript, suggestion.category);
  const multiWord = form.includes(" ");
  const providerIntent = suggestion.category !== "other" && suggestion.suggestedPolicy !== "translate_normally";
  const keep = multiWord || signals.includes("used away from sentence-initial position") || signals.includes("repeated in source") || signals.includes("intentional capitalization") || signals.includes("emphasis formatting") || providerIntent;
  return { keep, signals };
}

export interface ExtractionWarning {
  canonicalForm: string;
  reason: string;
}

export interface ExtractionResult {
  terms: TermCandidate[];
  warnings: ExtractionWarning[];
}

function normalizeForMatch(s: string): string {
  return s.toLowerCase().replace(/\s+/g, " ").trim();
}

function verifyOccurrence(claim: { chapterId: string; evidenceQuote: string }, chaptersById: Map<string, Chapter>): SourceLocation | null {
  const chapter = chaptersById.get(claim.chapterId);
  if (!chapter) return null;
  const needle = normalizeForMatch(claim.evidenceQuote);
  if (needle.length === 0) return null;
  for (let i = 0; i < chapter.blocks.length; i++) {
    const block = chapter.blocks[i]!;
    if (normalizeForMatch(block.text).includes(needle)) {
      return { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: i, evidenceQuote: claim.evidenceQuote };
    }
  }
  return null;
}

function downgrade(c: ConfidenceLevel): ConfidenceLevel {
  return c === "high" ? "medium" : "low";
}

function isValidRawSuggestion(raw: unknown): raw is RawTermSuggestion {
  if (typeof raw !== "object" || raw === null) return false;
  const r = raw as Record<string, unknown>;
  return (
    typeof r.canonicalForm === "string" &&
    r.canonicalForm.trim().length > 0 &&
    VALID_CATEGORIES.has(r.category as TermCategory) &&
    VALID_POLICIES.has(r.suggestedPolicy as TranslationPolicy) &&
    VALID_CONFIDENCE.has(r.confidence as ConfidenceLevel) &&
    Array.isArray(r.occurrences)
  );
}

export async function extractTermCandidates(provider: LlmProvider, manuscript: ParsedManuscript): Promise<ExtractionResult> {
  const raw = await provider.extractTerms(manuscript.chapters);
  const chaptersById = new Map(manuscript.chapters.map((c) => [c.id, c]));
  const terms: TermCandidate[] = [];
  const warnings: ExtractionWarning[] = [];
  let seq = 0;

  for (const suggestion of raw) {
    if (!isValidRawSuggestion(suggestion)) {
      warnings.push({
        canonicalForm: typeof (suggestion as { canonicalForm?: unknown })?.canonicalForm === "string" ? (suggestion as RawTermSuggestion).canonicalForm : "(malformed)",
        reason: "Malformed suggestion from provider (missing/invalid required field) -- dropped.",
      });
      continue;
    }

    const quality = shouldKeepSuggestion(suggestion, manuscript);
    if (!quality.keep) {
      warnings.push({ canonicalForm: suggestion.canonicalForm, reason: "Candidate rejected by the manuscript-specific lexical quality gate: the evidence was consistent with ordinary sentence vocabulary rather than a translation-relevant term." });
      continue;
    }

    const claimedCount = suggestion.occurrences.length;
    const verified = suggestion.occurrences.map((o) => verifyOccurrence(o, chaptersById)).filter((loc): loc is SourceLocation => loc !== null);

    if (verified.length === 0) {
      warnings.push({
        canonicalForm: suggestion.canonicalForm,
        reason: `None of the ${claimedCount} claimed source quote(s) could be found verbatim in the manuscript text -- candidate dropped rather than presented unverified.`,
      });
      continue;
    }

    let confidence = suggestion.confidence;
    if (verified.length < claimedCount) {
      confidence = downgrade(confidence);
      warnings.push({
        canonicalForm: suggestion.canonicalForm,
        reason: `Only ${verified.length} of ${claimedCount} claimed occurrences verified against the source text; confidence downgraded to "${confidence}" and unverified occurrences were dropped.`,
      });
    }

    const pronunciation: PronunciationNote =
      suggestion.pronunciation && suggestion.pronunciationConfidence
        ? { value: suggestion.pronunciation, confidence: suggestion.pronunciationConfidence, note: "Suggested by extraction model from manuscript context." }
        : { value: null, confidence: null, note: "Not confidently inferable from source." };

    terms.push({
      id: `term-${seq++}-${suggestion.canonicalForm.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 30)}`,
      canonicalForm: suggestion.canonicalForm,
      category: suggestion.category,
      occurrences: verified,
      meaning: suggestion.meaning ?? "",
      pronunciation,
      suggestedPolicy: suggestion.suggestedPolicy,
      confidence,
      status: "suggested", // always -- see rules/protectedTerms.ts confirmTerm for the only legitimate path out of this state
      evidenceSignals: quality.signals,
    });
  }

  const merged = new Map<string, TermCandidate>();
  for (const term of terms) {
    const key = (term.confirmedOverride?.canonicalForm ?? term.canonicalForm).toLocaleLowerCase();
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, term);
      continue;
    }
    const occurrences = [...existing.occurrences];
    for (const occurrence of term.occurrences) {
      if (!occurrences.some((o) => o.chapterId === occurrence.chapterId && o.blockIndex === occurrence.blockIndex)) occurrences.push(occurrence);
    }
    merged.set(key, {
      ...existing,
      occurrences: occurrences.slice(0, 12),
      confidence: existing.confidence === "high" || term.confidence === "high" ? "high" : existing.confidence === "medium" || term.confidence === "medium" ? "medium" : "low",
      evidenceSignals: [...new Set([...(existing.evidenceSignals ?? []), ...(term.evidenceSignals ?? [])])],
    });
  }
  return { terms: [...merged.values()], warnings };
}

export async function generateStyleNote(provider: LlmProvider, manuscript: ParsedManuscript): Promise<StyleNote> {
  const raw: RawStyleNoteSuggestion = await provider.generateStyleNote(manuscript.chapters);
  const notDetermined = "(not determined for this manuscript)";
  return {
    register: raw.register?.trim() || notDetermined,
    narrativeVoice: raw.narrativeVoice?.trim() || notDetermined,
    dialogue: raw.dialogue?.trim() || notDetermined,
    tone: raw.tone?.trim() || notDetermined,
    wordplay: raw.wordplay?.trim() || notDetermined,
    verse: raw.verse?.trim() || notDetermined,
    formatting: raw.formatting?.trim() || notDetermined,
    translationConsiderations: raw.translationConsiderations?.trim() || notDetermined,
    additionalNotes: Array.isArray(raw.additionalNotes) ? raw.additionalNotes.filter((n) => n.trim().length > 0) : [],
    evidence: manuscript.chapters.slice(0, 3).map((c) => ({ chapterId: c.id, chapterTitle: c.title, blockIndex: 0, evidenceQuote: c.blocks[0]?.text.slice(0, 120) ?? "" })),
    status: "suggested",
  };
}
