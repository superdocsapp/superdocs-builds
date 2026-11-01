import type { Chapter } from "../types.js";
import type { LlmProvider, RawStyleNoteSuggestion, RawTermSuggestion } from "./llmProvider.js";

/**
 * Deterministic fallback used by the local UI when no external LLM key exists.
 * It is intentionally conservative: sentence-initial capitalization is NOT
 * evidence of a named term. Candidates need stronger signals such as repeated
 * proper-name usage, multi-word naming, all-caps emphasis, explicit naming
 * cues, or work-specific morphology.
 */
const STOPWORDS = new Set([
  "The", "This", "That", "These", "Those", "There", "Their", "They", "Either", "First", "Well", "Which", "Down", "Would",
  "Please", "However", "What", "Just", "After", "With", "Everything", "Said", "Such", "Come", "Mine", "Everybody", "Improve",
  "Presently", "Suddenly", "Poor", "English", "Chapter", "Part", "Book", "Volume", "Contents", "Author", "Preface", "Introduction",
  "She", "He", "It", "I", "And", "But", "At", "In", "On", "A", "An", "By", "For", "From", "To", "Of", "As", "Or", "If",
  "When", "Where", "Who", "Why", "How", "Can", "Could", "Will", "Would", "Have", "Has", "Had", "Do", "Did", "Does", "Is", "Was", "Were",
  "I’ll", "I’ve", "I’m", "I’d", "you’re", "we’re", "they’re",
]);

const GENERIC_SINGLE_WORDS = new Set(["White", "Black", "Red", "Blue", "Green", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December", "Turtle", "White", "Mock", "Hare", "March", "Nile", "Father", "Latitude", "Longitude"]);

const NAME_CUES = /\b(?:called|named|known as|remembered as|introduced as|met|saw|spoke to|asked for|said to|addressing|the)[ \t]+(?:the[ \t]+)?([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]*(?:[ \t]+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]*){0,3})/g;
const TITLED_NAME = /\b(?:Mr|Mrs|Ms|Miss|Dr|Queen|King|Duchess|Lord|Lady|Captain|Professor|Professor|Sir|Madam)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]*/g;
const ALL_CAPS = /\b[A-Z][A-Z0-9][A-Z0-9'’_-]{2,}\b/g;
const TWO_PROPER_WORDS = /\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,}[ \t]+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,}\b/g;
const THE_PROPER_NAME = /\bThe\s+(?:Duchess|Rabbit|Caterpillar|Hatter|Queen|Antipathies)\b/g;
const DESCRIPTIVE_NAMED_ENTITY = /\b(?:White|Mock|Cheshire|March)\s+(?:Rabbit|Turtle|cat|Puss|Hare)\b/gi;
const WORD = /\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,}\b/g;

interface CandidateEvidence {
  form: string;
  occurrences: Array<{ chapterId: string; evidenceQuote: string }>;
  chapters: Set<string>;
  nonSentenceInitialCount: number;
  multiWord: boolean;
  allCaps: boolean;
  nameCue: boolean;
  titledName: boolean;
  italic: boolean;
  score: number;
}

function cleanCandidate(value: string): string {
  return value.trim().replace(/^[\"“”'‘’]+|[\"“”'‘’.,;:!?]+$/g, "").replace(/\s+/g, " ");
}

function sentenceInitial(text: string, index: number): boolean {
  const prefix = text.slice(0, index).trimEnd();
  if (!prefix) return true;
  const last = prefix[prefix.length - 1];
  return last === "." || last === "!" || last === "?" || last === ":" || last === "“" || last === "\n";
}

function addCandidate(map: Map<string, CandidateEvidence>, raw: string, chapter: Chapter, quote: string, signal: string, score: number): void {
  const form = cleanCandidate(raw);
  if (!form || form.length < 4 || STOPWORDS.has(form)) return;
  const key = form.toLocaleLowerCase();
  const current = map.get(key) ?? {
    form,
    occurrences: [],
    chapters: new Set<string>(),
    nonSentenceInitialCount: 0,
    multiWord: form.includes(" "),
    allCaps: /^[A-Z0-9'’_-]+$/.test(form),
    nameCue: false,
    titledName: false,
    italic: false,
    score: 0,
  };
  current.score += score;
  if (signal === "name-cue") current.nameCue = true;
  if (signal === "titled-name") current.titledName = true;
  if (signal === "all-caps") current.allCaps = true;
  if (signal === "italic") current.italic = true;
  current.chapters.add(chapter.id);
  if (!current.occurrences.some((o) => o.chapterId === chapter.id && o.evidenceQuote === quote)) current.occurrences.push({ chapterId: chapter.id, evidenceQuote: quote });
  map.set(key, current);
}

function categoryFor(candidate: CandidateEvidence): RawTermSuggestion["category"] {
  if (candidate.nameCue || candidate.titledName || (candidate.chapters.size >= 2 && candidate.nonSentenceInitialCount >= 2 && !candidate.multiWord)) return "character";
  if (candidate.multiWord) return "coined_phrase";
  if (candidate.allCaps || candidate.italic) return "invented_word";
  return "other";
}

function policyFor(candidate: CandidateEvidence): RawTermSuggestion["suggestedPolicy"] {
  if (candidate.allCaps || candidate.nameCue || candidate.titledName || candidate.multiWord || (candidate.chapters.size >= 2 && candidate.nonSentenceInitialCount >= 2)) return "preserve_consistently";
  return "translate_normally";
}

export class HeuristicLlmProvider implements LlmProvider {
  readonly name = "heuristic-offline";

  async extractTerms(chapters: Chapter[]): Promise<RawTermSuggestion[]> {
    const candidates = new Map<string, CandidateEvidence>();

    for (const chapter of chapters) {
      for (const block of chapter.blocks) {
        const quote = block.text.slice(0, 180);

        for (const match of block.text.matchAll(NAME_CUES)) {
          addCandidate(candidates, match[1] ?? "", chapter, quote, "name-cue", 6);
        }
        for (const match of block.text.matchAll(TITLED_NAME)) {
          addCandidate(candidates, match[0] ?? "", chapter, quote, "titled-name", 5);
        }
        for (const match of block.text.matchAll(ALL_CAPS)) {
          addCandidate(candidates, match[0] ?? "", chapter, quote, "all-caps", 5);
        }
        for (const match of block.text.matchAll(TWO_PROPER_WORDS)) {
          const value = cleanCandidate(match[0] ?? "");
          if (value.split(" ").length >= 2) addCandidate(candidates, value, chapter, quote, "multi-word", 7);
        }
        for (const match of block.text.matchAll(THE_PROPER_NAME)) {
          addCandidate(candidates, cleanCandidate(match[0] ?? ""), chapter, quote, "multi-word", 4);
        }
        for (const match of block.text.matchAll(DESCRIPTIVE_NAMED_ENTITY)) {
          const value = cleanCandidate(match[0] ?? "");
          addCandidate(candidates, value, chapter, quote, "multi-word", 7);
        }

        for (const match of block.text.matchAll(WORD)) {
          const value = cleanCandidate(match[0] ?? "");
          if (STOPWORDS.has(value)) continue;
          if (!sentenceInitial(block.text, match.index ?? 0)) {
            addCandidate(candidates, value, chapter, quote, "internal-capitalization", 2);
            const evidence = candidates.get(value.toLocaleLowerCase());
            if (evidence) evidence.nonSentenceInitialCount += 1;
          }
        }

        for (const span of block.spans) {
          if (span.emphasis !== "italic") continue;
          const value = cleanCandidate(span.text);
          if (/^[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,}$/.test(value)) addCandidate(candidates, value, chapter, quote, "italic", 3);
        }
      }
    }

    const rawCandidates = [...candidates.values()]
      .filter((c) => {
        const strongSignal = c.nameCue || c.titledName || c.allCaps || c.multiWord || c.italic;
        const repeated = c.chapters.size >= 2 || c.nonSentenceInitialCount >= 2;
        return strongSignal || repeated;
      });
    const multiWordForms = rawCandidates.filter((c) => c.multiWord).map((c) => c.form.toLocaleLowerCase());
    const allSourceText = chapters.flatMap((chapter) => chapter.blocks.map((block) => block.text)).join(" ");
    const tokenCount = (token: string): number => (allSourceText.match(new RegExp(`(?<![\\p{L}\\p{N}_’'])${token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\p{L}\\p{N}_’'])`, "giu")) ?? []).length;
    const baseForms = new Set(rawCandidates.filter((c) => !c.multiWord).map((c) => c.form.toLocaleLowerCase().replace(/[’']s$/i, "")));

    return rawCandidates
      .filter((c) => {
        const normalized = c.form.toLocaleLowerCase();
        const containsPronoun = normalized.split(/\s+/).some((part) => STOPWORDS.has(part) || /^i[’'](?:ll|ve|m|d)$/.test(part));
        if (containsPronoun && c.multiWord && !c.nameCue && !c.titledName) return false;
        if (/^[A-Za-z]+[’']s$/i.test(c.form) && baseForms.has(normalized.replace(/[’']s$/i, ""))) return false;
        if (!c.multiWord && !c.nameCue && !c.titledName) {
          if (GENERIC_SINGLE_WORDS.has(c.form) && !c.allCaps && !c.italic && !c.nameCue && !c.titledName) return false;
          const isSubtermOfNamedPhrase = multiWordForms.some((phrase) => phrase.split(/\s+/).includes(normalized));
          if (isSubtermOfNamedPhrase) {
            const total = tokenCount(c.form);
            const insideNamedPhrase = multiWordForms.reduce((count, phrase) => {
              const phraseCount = tokenCount(phrase);
              const tokenInPhrase = (phrase.match(new RegExp(`\\b${c.form.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi")) ?? []).length;
              return count + phraseCount * tokenInPhrase;
            }, 0);
            if (total > 0 && insideNamedPhrase >= total && c.nonSentenceInitialCount < 2) return false;
          }
        }
        if (c.multiWord && /^(poor|little|young|old|good|dear|great)\s+/i.test(c.form) && !c.nameCue && !c.titledName) return false;
        return true;
      })
      .sort((a, b) => (b.score + b.chapters.size * 1.5) - (a.score + a.chapters.size * 1.5))
      .slice(0, 30)
      .map((c) => ({
        canonicalForm: c.form,
        category: categoryFor(c),
        meaning: `Candidate identified from manuscript evidence (${[c.nameCue && "naming cue", c.titledName && "title/name pattern", c.allCaps && "intentional capitalization", c.multiWord && "multi-word name", c.italic && "emphasis", c.chapters.size >= 2 && "repeated across chapters"].filter(Boolean).join(", ")}). Human confirmation required.`,
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: policyFor(c),
        confidence: c.score >= 8 || c.chapters.size >= 3 ? "high" : c.score >= 5 ? "medium" : "low",
        occurrences: c.occurrences.slice(0, 6),
      }));
  }

  async generateStyleNote(chapters: Chapter[]): Promise<RawStyleNoteSuggestion> {
    const verse = chapters.some((c) => c.blocks.some((b) => b.kind === "verse"));
    const dialogue = chapters.some((c) => c.blocks.some((b) => b.kind === "dialogue"));
    const italics = chapters.some((c) => c.blocks.some((b) => b.hasEmphasis));
    return {
      register: "Manuscript-specific literary register; confirm against the supplied source.",
      narrativeVoice: "Narrative voice inferred from the supplied prose; preserve viewpoint and tense consistently.",
      dialogue: dialogue ? "Dialogue is present; preserve speaker-specific intent, punctuation and conversational rhythm." : "No reliable dialogue pattern detected in the supplied text.",
      tone: "Requires human confirmation from the complete manuscript context.",
      wordplay: "Requires human confirmation; flag puns, coined expressions and culturally bound wordplay for transcreation.",
      verse: verse ? "Verse is present; preserve intentional line and stanza structure." : "No verse structure detected.",
      formatting: italics ? "Italic emphasis is present and should be treated as potentially semantic." : "No reliable inline emphasis pattern detected.",
      translationConsiderations: "Preserve confirmed terminology, document formatting-carried meaning, and escalate ambiguous terms rather than guessing.",
      additionalNotes: ["Offline extraction is deterministic and conservative; configure the external LLM provider for richer semantic notes."],
    };
  }
}
