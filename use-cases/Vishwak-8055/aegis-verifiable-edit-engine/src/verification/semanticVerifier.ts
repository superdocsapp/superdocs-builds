import { diffArrays } from 'diff';
import type { VerificationContext } from '../types/context.js';
import type { CheckerOutcome, Finding } from '../types/verification.js';
import { findBlock, type BlockAlignment } from './normalize.js';
import { blockPlainText } from '../types/document.js';

type ModalityCategory = 'obligation' | 'permission' | 'prohibition' | 'none';

const PROHIBITION_PATTERNS = [/\bshall not\b/i, /\bmust not\b/i, /\bmay not\b/i, /\bis prohibited from\b/i, /\bis not permitted to\b/i, /\bwill not\b/i];
const OBLIGATION_PATTERNS = [/\bshall\b/i, /\bmust\b/i, /\bis required to\b/i, /\bis obligated to\b/i, /\bwill be required to\b/i];
const PERMISSION_PATTERNS = [/\bmay\b/i, /\bcan\b/i, /\bis permitted to\b/i, /\bis allowed to\b/i, /\bis entitled to\b/i];
const CONDITION_EXCEPTION_PATTERN = /\b(unless|except|provided that|other than|in the event that|excluding)\b/i;
const ACTOR_PATTERN = /\b(?:The\s+)?([A-Z][a-zA-Z]*)\s+(?=(?:shall|must|may|can|will|is)\b)/;

interface SentencePair {
  kind: 'unchanged' | 'modified' | 'removed' | 'added';
  before?: string;
  after?: string;
}

export function runSemanticVerifier(ctx: VerificationContext): CheckerOutcome {
  const start = performance.now();
  const findings: Finding[] = [];

  if (!ctx.intent.protectSemantics) {
    return { checker: 'semantic', findings, durationMs: performance.now() - start };
  }

  let counter = 0;
  const nextId = () => `semantic:${++counter}`;

  for (const entry of ctx.alignment) {
    if (entry.kind === 'modified') {
      findings.push(...compareBlock(ctx, entry, nextId));
    }
  }

  return { checker: 'semantic', findings, durationMs: performance.now() - start };
}

function compareBlock(ctx: VerificationContext, entry: Extract<BlockAlignment, { kind: 'modified' }>, nextId: () => string): Finding[] {
  const findings: Finding[] = [];
  const beforeBlock = findBlock(ctx.before, entry.beforeId);
  const afterBlock = findBlock(ctx.after, entry.afterId);
  if (!beforeBlock || !afterBlock) return findings;

  const location = { beforeBlockId: entry.beforeId, afterBlockId: entry.afterId };
  const pairs = pairSentences(splitSentences(blockPlainText(beforeBlock)), splitSentences(blockPlainText(afterBlock)));

  for (const pair of pairs) {
    if (pair.kind === 'unchanged') continue;

    const beforeCat = pair.before ? detectModality(pair.before) : 'none';
    const afterCat = pair.after ? detectModality(pair.after) : 'none';
    const transitionKind = classifyModalityTransition(beforeCat, afterCat);
    if (transitionKind) {
      findings.push({
        id: nextId(),
        checker: 'semantic',
        kind: transitionKind,
        confidence: 0.85,
        message: describeModalityTransition(transitionKind, beforeCat, afterCat, pair),
        before: pair.before,
        after: pair.after,
        location,
      });
    }

    // Fires whether the whole sentence vanished ('removed') or the sentence
    // survived but lost its conditional/exception clause in the rewrite
    // ('modified') — both are "this carve-out used to exist and now it
    // doesn't", which is the thing worth flagging.
    const hadConditionBefore = Boolean(pair.before && CONDITION_EXCEPTION_PATTERN.test(pair.before));
    const hasConditionAfter = Boolean(pair.after && CONDITION_EXCEPTION_PATTERN.test(pair.after));
    if ((pair.kind === 'removed' || pair.kind === 'modified') && hadConditionBefore && !hasConditionAfter) {
      findings.push({
        id: nextId(),
        checker: 'semantic',
        kind: 'SEMANTIC_CONDITION_OR_EXCEPTION_REMOVED',
        confidence: 0.75,
        message: `A conditional/exception clause present before the edit is gone afterward: "${pair.before}" → "${pair.after ?? '(removed)'}"`,
        before: pair.before,
        after: pair.after,
        location,
      });
    }

    if (pair.kind === 'modified' && pair.before && pair.after) {
      const beforeActor = ACTOR_PATTERN.exec(pair.before)?.[1];
      const afterActor = ACTOR_PATTERN.exec(pair.after)?.[1];
      if (beforeActor && afterActor && beforeActor.toLowerCase() !== afterActor.toLowerCase()) {
        findings.push({
          id: nextId(),
          checker: 'semantic',
          kind: 'SEMANTIC_ACTOR_CHANGED',
          confidence: 0.6,
          message: `The party bound by this sentence changed from "${beforeActor}" to "${afterActor}".`,
          before: pair.before,
          after: pair.after,
          location,
        });
      }
    }
  }

  return findings;
}

function pairSentences(before: string[], after: string[]): SentencePair[] {
  const changes = diffArrays(before, after);
  const pairs: SentencePair[] = [];
  let i = 0;
  while (i < changes.length) {
    const change = changes[i];
    if (!change.added && !change.removed) {
      for (const value of change.value) pairs.push({ kind: 'unchanged', before: value, after: value });
      i++;
      continue;
    }
    const removed: string[] = [];
    const added: string[] = [];
    while (i < changes.length && (changes[i].added || changes[i].removed)) {
      if (changes[i].removed) removed.push(...changes[i].value);
      if (changes[i].added) added.push(...changes[i].value);
      i++;
    }
    const pairCount = Math.min(removed.length, added.length);
    for (let k = 0; k < pairCount; k++) pairs.push({ kind: 'modified', before: removed[k], after: added[k] });
    for (let k = pairCount; k < removed.length; k++) pairs.push({ kind: 'removed', before: removed[k] });
    for (let k = pairCount; k < added.length; k++) pairs.push({ kind: 'added', after: added[k] });
  }
  return pairs;
}

function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+(?=[A-Z(])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function detectModality(sentence: string): ModalityCategory {
  if (PROHIBITION_PATTERNS.some((p) => p.test(sentence))) return 'prohibition';
  if (OBLIGATION_PATTERNS.some((p) => p.test(sentence))) return 'obligation';
  if (PERMISSION_PATTERNS.some((p) => p.test(sentence))) return 'permission';
  return 'none';
}

function bindingStrength(category: ModalityCategory): 0 | 1 {
  return category === 'obligation' || category === 'prohibition' ? 1 : 0;
}

/**
 * Classifies a modality transition into one of four buckets. See
 * docs/ARCHITECTURE.md "Risk model rationale" for why obligation/prohibition
 * are treated as a single "binding" tier for this purpose: this repository's
 * severity policy cares most about whether a party's binding duty silently
 * disappeared, which `SEMANTIC_OBLIGATION_TO_PERMISSION` captures whether the
 * duty was a "shall" or a "shall not".
 */
function classifyModalityTransition(before: ModalityCategory, after: ModalityCategory): string | null {
  if (before === after) return null;
  if (before === 'obligation' && after === 'prohibition') return 'SEMANTIC_MODALITY_INVERTED';
  if (before === 'prohibition' && after === 'obligation') return 'SEMANTIC_MODALITY_INVERTED';
  const beforeBinding = bindingStrength(before);
  const afterBinding = bindingStrength(after);
  if (beforeBinding === 1 && afterBinding === 0) return 'SEMANTIC_OBLIGATION_TO_PERMISSION';
  if (beforeBinding === 0 && afterBinding === 1) return 'SEMANTIC_MODALITY_TIGHTENED';
  return 'SEMANTIC_MODALITY_CHANGED';
}

function describeModalityTransition(kind: string, before: ModalityCategory, after: ModalityCategory, pair: SentencePair): string {
  switch (kind) {
    case 'SEMANTIC_MODALITY_INVERTED':
      return `Modality inverted from ${before} to ${after}: "${pair.before ?? '(none)'}" → "${pair.after ?? '(none)'}"`;
    case 'SEMANTIC_OBLIGATION_TO_PERMISSION':
      return `A binding ${before} became non-binding (${after}): "${pair.before ?? '(none)'}" → "${pair.after ?? '(removed)'}"`;
    case 'SEMANTIC_MODALITY_TIGHTENED':
      return `A non-binding statement (${before}) became binding (${after}): "${pair.before ?? '(new sentence)'}" → "${pair.after ?? '(none)'}"`;
    default:
      return `Modality changed from ${before} to ${after}: "${pair.before ?? '(none)'}" → "${pair.after ?? '(none)'}"`;
  }
}
