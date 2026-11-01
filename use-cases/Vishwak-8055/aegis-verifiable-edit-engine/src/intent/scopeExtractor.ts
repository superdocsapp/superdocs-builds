import type { ScopeSpec } from '../types/instruction.js';

export interface ScopeExtraction {
  scope: ScopeSpec;
  confidence: number;
}

const PARAGRAPH_PATTERN = /\bpara(?:graph)?\.?\s*#?\s*(\d+)\b/i;
const WHOLE_DOC_PATTERN = /\b(whole|entire|full)\s+document\b|\bthroughout\s+(?:the\s+)?document\b/i;
const STYLE_KEYWORDS =
  /\b(grammar|punctuation|spelling|typo|wording|phrasing|rephrase|readability|clarity|clearer|easier to read|plain\s?english|tone|style)\b/i;
const HEADING_QUOTED_PATTERN = /["“]([A-Za-z0-9][A-Za-z0-9 ,.'&/-]{1,60})["”]\s+(section|heading|clause)/i;
const HEADING_TITLED_PATTERN = /\bsection\s+(?:on|about|titled)\s+["“]?([A-Za-z0-9][A-Za-z0-9 ,.'&/-]{1,60})["”]?/i;
const HEADING_UNDER_PATTERN = /\bunder\s+(?:the\s+)?["“]?([A-Z][A-Za-z0-9 ,.'&/-]{1,40})["”]?\s+(?:section|heading|clause)\b/i;

/**
 * Extracts the requested edit scope from free-text instructions. This is a
 * pragmatic pattern set, not an NLP parser — it is tuned against the phrasing
 * this repository's tests and benchmark cases use, which is itself
 * representative of how these instructions are usually written ("fix
 * grammar in paragraph 4", "simplify the Termination section"). Instructions
 * phrased very differently will fall through to `unscoped`, which is a safe
 * default (see docs/ARCHITECTURE.md "Known limitations" and
 * src/intent/aiProvider.ts for the extension point that would widen
 * coverage without weakening the deterministic fallback).
 */
export function extractScope(instructionText: string): ScopeExtraction {
  const paragraphMatch = PARAGRAPH_PATTERN.exec(instructionText);
  if (paragraphMatch) {
    return { scope: { kind: 'paragraph-index', index: Number(paragraphMatch[1]) }, confidence: 0.9 };
  }

  const heading =
    HEADING_QUOTED_PATTERN.exec(instructionText)?.[1] ??
    HEADING_TITLED_PATTERN.exec(instructionText)?.[1] ??
    HEADING_UNDER_PATTERN.exec(instructionText)?.[1];
  if (heading) {
    return { scope: { kind: 'heading', headingText: heading.trim() }, confidence: 0.75 };
  }

  if (WHOLE_DOC_PATTERN.test(instructionText)) {
    return { scope: { kind: 'whole-document' }, confidence: 0.85 };
  }

  if (STYLE_KEYWORDS.test(instructionText)) {
    return { scope: { kind: 'style-only' }, confidence: 0.7 };
  }

  return { scope: { kind: 'unscoped' }, confidence: 0.3 };
}
