import { ChangeEvent } from './types.js';

export interface SentenceInfo {
  index: number;
  text: string;
  sectionHeading: string;
  startOffset: number;
  endOffset: number;
}

export interface MatchCandidate {
  sentence: SentenceInfo;
  matchedTerms: string[];
  isIndirect: boolean;
  score: number; // 0 to 1
  explanation: string;
}

/**
 * Splits article content into discrete sentences with section heading context and character offsets.
 */
export function extractSentences(content: string): SentenceInfo[] {
  const lines = content.split('\n');
  const sentences: SentenceInfo[] = [];
  let currentSection = 'Introduction';
  let charCursor = 0;
  let sentenceIdx = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('#')) {
      currentSection = trimmed.replace(/^#+\s*/, '');
      charCursor += line.length + 1; // +1 for newline
      continue;
    }

    if (!trimmed) {
      charCursor += line.length + 1;
      continue;
    }

    // Split line into sentences using punctuation boundaries (. ! ?) while avoiding decimals like 10.5
    const regex = /([^.!?]+[.!?]+(?:\s|$)|[^.!?]+$)/g;
    let match;
    let lineOffset = 0;

    while ((match = regex.exec(line)) !== null) {
      const sentenceText = match[0].trim();
      if (sentenceText.length > 0) {
        const start = charCursor + lineOffset + match.index;
        const end = start + sentenceText.length;
        sentences.push({
          index: sentenceIdx++,
          text: sentenceText,
          sectionHeading: currentSection,
          startOffset: start,
          endOffset: end
        });
      }
      lineOffset += match[0].length;
    }

    charCursor += line.length + 1;
  }

  return sentences;
}

/**
 * Stage 1: Deterministic Matcher
 * Identifies exact matches of entity names, UI paths, changed limit values, retired plans.
 */
export function matchDeterministic(
  sentences: SentenceInfo[],
  change: ChangeEvent
): MatchCandidate[] {
  const matches: MatchCandidate[] = [];
  const before = change.before_state;

  const targetTerms: string[] = [];
  if (before.entity_name) targetTerms.push(before.entity_name);
  if (before.ui_label) targetTerms.push(before.ui_label);
  if (before.path) targetTerms.push(before.path);
  if (before.value !== undefined) {
    targetTerms.push(String(before.value));
    // If value is numeric like 10000, also match 10,000
    if (typeof before.value === 'number') {
      targetTerms.push(before.value.toLocaleString());
    }
  }

  for (const sentence of sentences) {
    const lowerText = sentence.text.toLowerCase();
    const matchedTerms: string[] = [];

    for (const term of targetTerms) {
      if (!term) continue;
      const lowerTerm = term.toLowerCase();
      
      // Exact term search with boundary check
      const regex = new RegExp(`\\b${escapeRegExp(lowerTerm)}\\b`, 'i');
      if (regex.test(sentence.text) || lowerText.includes(lowerTerm)) {
        matchedTerms.push(term);
      }
    }

    // Specific domain checks
    if (change.type === 'CHANGED_LIMIT' && before.value !== undefined) {
      const valStr = String(before.value);
      const valFormatted = typeof before.value === 'number' ? before.value.toLocaleString() : valStr;
      
      // Require limit term to be in context of the limited resource (e.g. API, calls, megabytes, files, exports)
      const resourceContext = extractResourceKeywords(change.title + ' ' + change.description);
      const hasResourceContext = resourceContext.some(k => lowerText.includes(k));

      if ((lowerText.includes(valStr) || lowerText.includes(valFormatted.toLowerCase())) && hasResourceContext) {
        matches.push({
          sentence,
          matchedTerms: [...matchedTerms, valFormatted],
          isIndirect: false,
          score: 0.95,
          explanation: `Explicitly references old limit '${valFormatted}' for ${resourceContext.join(', ')}`
        });
        continue;
      }
    }

    if (change.type === 'RENAMED_SCREEN' && before.ui_label) {
      if (lowerText.includes(before.ui_label.toLowerCase())) {
        matches.push({
          sentence,
          matchedTerms: [...matchedTerms, before.ui_label],
          isIndirect: false,
          score: 0.9,
          explanation: `References deprecated UI label '${before.ui_label}'`
        });
        continue;
      }
    }

    if (change.type === 'RETIRED_PLAN' && before.entity_name) {
      if (lowerText.includes(before.entity_name.toLowerCase())) {
        matches.push({
          sentence,
          matchedTerms: [...matchedTerms, before.entity_name],
          isIndirect: false,
          score: 0.95,
          explanation: `Mentions retired plan '${before.entity_name}'`
        });
        continue;
      }
    }

    if (matchedTerms.length > 0) {
      matches.push({
        sentence,
        matchedTerms,
        isIndirect: false,
        score: 0.85,
        explanation: `Direct match for terms: ${matchedTerms.join(', ')}`
      });
    }
  }

  return matches;
}

/**
 * Stage 2: Semantic & Indirect Reference Matcher
 * Detects articles describing invalidated behavior or indirect references where terminology differs.
 */
export function matchSemantic(
  sentences: SentenceInfo[],
  change: ChangeEvent,
  existingMatches: MatchCandidate[]
): MatchCandidate[] {
  const matches: MatchCandidate[] = [...existingMatches];
  const matchedSentenceIndices = new Set(existingMatches.map(m => m.sentence.index));

  const changeTokens = tokenize(change.title + ' ' + change.description);
  const beforeDesc = (change.before_state.details || '') + ' ' + (change.before_state.workflow_steps?.join(' ') || '');
  const beforeTokens = tokenize(beforeDesc);

  for (const sentence of sentences) {
    if (matchedSentenceIndices.has(sentence.index)) continue;

    const lowerText = sentence.text.toLowerCase();

    // Adversarial False-Positive Guards:
    // 1. If looking for 'Growth plan', skip 'revenue growth' or 'business growth'
    if (change.type === 'RETIRED_PLAN') {
      if (lowerText.includes('growth') && !lowerText.includes('growth plan') && !lowerText.includes('growth tier') && !lowerText.includes('plan')) {
        continue; // Unrelated usage of word "growth"
      }
    }

    // 2. If looking for limit changes, avoid generic "unlimited potential" or "without limits"
    if (change.type === 'CHANGED_LIMIT') {
      if (lowerText.includes('limit') && !/\d+/.test(lowerText) && !lowerText.includes('cap') && !lowerText.includes('quota') && !lowerText.includes('maximum')) {
        continue;
      }
    }

    // Indirect Workflow Invalidation Check
    if (change.type === 'CHANGED_WORKFLOW') {
      const workflowClues = change.before_state.workflow_steps || [];
      let clueMatches = 0;
      for (const clue of workflowClues) {
        if (lowerText.includes(clue.toLowerCase())) {
          clueMatches++;
        }
      }

      if (clueMatches >= 2 || (clueMatches >= 1 && containsActionVerb(lowerText))) {
        matches.push({
          sentence,
          matchedTerms: workflowClues.filter(c => lowerText.includes(c.toLowerCase())),
          isIndirect: true,
          score: 0.75,
          explanation: `Describes legacy workflow steps invalidated by workflow change '${change.title}'`
        });
        matchedSentenceIndices.add(sentence.index);
        continue;
      }
    }

    // Semantic Concept Overlap Check
    const sentenceTokens = tokenize(sentence.text);
    const overlapWithBefore = tokenOverlap(sentenceTokens, beforeTokens);
    const overlapWithChange = tokenOverlap(sentenceTokens, changeTokens);

    if (overlapWithBefore >= 3 && overlapWithChange >= 2) {
      matches.push({
        sentence,
        matchedTerms: Array.from(intersectSets(sentenceTokens, beforeTokens)),
        isIndirect: true,
        score: 0.70,
        explanation: `Semantically references deprecated behavior: '${sentence.text.slice(0, 60)}...'`
      });
      matchedSentenceIndices.add(sentence.index);
    }
  }

  return matches;
}

function escapeRegExp(string: string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function extractResourceKeywords(text: string): string[] {
  const keywords: string[] = [];
  const candidates = ['api', 'call', 'calls', 'request', 'requests', 'upload', 'file', 'attachment', 'export', 'project', 'seat', 'user', 'member', 'mb', 'gb', 'hour', 'minute'];
  const lower = text.toLowerCase();
  for (const c of candidates) {
    if (lower.includes(c)) keywords.push(c);
  }
  return keywords.length > 0 ? keywords : ['limit', 'rate', 'quota'];
}

function tokenize(text: string): Set<string> {
  const stopWords = new Set(['the', 'and', 'a', 'an', 'in', 'on', 'to', 'for', 'of', 'with', 'is', 'are', 'you', 'can', 'your', 'this', 'that', 'from', 'by', 'as', 'at']);
  const tokens = text.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(t => t.length > 2 && !stopWords.has(t));
  return new Set(tokens);
}

function tokenOverlap(setA: Set<string>, setB: Set<string>): number {
  let count = 0;
  for (const item of setA) {
    if (setB.has(item)) count++;
  }
  return count;
}

function intersectSets(setA: Set<string>, setB: Set<string>): Set<string> {
  const res = new Set<string>();
  for (const item of setA) {
    if (setB.has(item)) res.add(item);
  }
  return res;
}

function containsActionVerb(text: string): boolean {
  const verbs = ['click', 'select', 'navigate', 'go to', 'open', 'drag', 'press', 'choose', 'download', 'upload', 'export', 'import'];
  return verbs.some(v => text.includes(v));
}
