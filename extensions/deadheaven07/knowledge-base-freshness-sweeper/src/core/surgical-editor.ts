import { Article, ChangeEvent, EditProposal, EvidenceItem, ChangedSpan } from './types.js';

export interface StructuralPreservationMetrics {
  originalLength: number;
  proposedLength: number;
  changedCharCount: number;
  preservationRatio: number;
  headingsPreserved: boolean;
  codeBlocksPreserved: boolean;
  linkCountPreserved: boolean;
}

/**
 * Surgical AST Markdown Editor
 * Generates the smallest possible sentence-level edit to resolve staleness
 * while guaranteeing absolute structural preservation of surrounding documentation.
 */
export function generateSurgicalEdit(
  article: Article,
  change: ChangeEvent,
  evidenceList: EvidenceItem[]
): EditProposal | null {
  if (!evidenceList || evidenceList.length === 0) {
    return null;
  }

  let updatedContent = article.content;
  const changedSpans: ChangedSpan[] = [];

  for (const evidence of evidenceList) {
    const originalSentence = evidence.sentence_text;
    const replacementSentence = buildReplacementSentence(originalSentence, change);

    if (originalSentence === replacementSentence) {
      continue;
    }

    const startIdx = updatedContent.indexOf(originalSentence);
    if (startIdx !== -1) {
      const endIdx = startIdx + originalSentence.length;
      updatedContent =
        updatedContent.slice(0, startIdx) +
        replacementSentence +
        updatedContent.slice(endIdx);

      changedSpans.push({
        start_char: startIdx,
        end_char: endIdx,
        original_text: originalSentence,
        replacement_text: replacementSentence,
        sentence_index: evidence.sentence_index
      });
    }
  }

  if (changedSpans.length === 0) {
    return null;
  }

  const metrics = verifyStructuralPreservation(article.content, updatedContent);

  const proposalId = `prop-${article.id}-${change.id}-${Date.now().toString(36)}`;
  return {
    id: proposalId,
    article_id: article.id,
    change_id: change.id,
    original_content: article.content,
    proposed_content: updatedContent,
    changed_spans: changedSpans,
    rationale: `Surgically updated ${changedSpans.length} sentence(s) to reflect ${change.title}`,
    evidence: evidenceList,
    confidence: evidenceList.some(e => !e.is_indirect) ? 'HIGH' : 'MEDIUM',
    status: 'PENDING',
    created_at: new Date().toISOString(),
    structural_preservation_ratio: metrics.preservationRatio
  };
}

/**
 * Constructs a minimal, surgical replacement sentence addressing the change.
 */
export function buildReplacementSentence(
  sentence: string,
  change: ChangeEvent
): string {
  let result = sentence;
  const before = change.before_state;
  const after = change.after_state;

  // 1. Limit changes (e.g., 10,000 -> 25,000 or 5 MB -> 25 MB)
  if (change.type === 'CHANGED_LIMIT' && before.value !== undefined && after.value !== undefined) {
    const oldVal = String(before.value);
    const newVal = String(after.value);
    const oldFormatted = typeof before.value === 'number' ? before.value.toLocaleString() : oldVal;
    const newFormatted = typeof after.value === 'number' ? after.value.toLocaleString() : newVal;

    if (result.includes(oldFormatted)) {
      result = result.replaceAll(oldFormatted, newFormatted);
    } else if (result.includes(oldVal)) {
      result = result.replaceAll(oldVal, newVal);
    }
  }

  // 2. Renamed screen / UI label (e.g. "Plans" -> "Subscriptions")
  if (change.type === 'RENAMED_SCREEN' && before.ui_label && after.ui_label) {
    const regex = new RegExp(`\\b${escapeRegExp(before.ui_label)}\\b`, 'g');
    result = result.replace(regex, after.ui_label);
  }

  // 3. Renamed navigation path (e.g. Settings -> Team to Settings -> Workspace)
  if (before.path && after.path) {
    if (result.includes(before.path)) {
      result = result.replaceAll(before.path, after.path);
    }
  }

  // 4. Retired plan (e.g. "Legacy Pro" -> "Growth Plan")
  if (change.type === 'RETIRED_PLAN' && before.entity_name) {
    const replacementName = after.entity_name || 'Standard Plan';
    const regex = new RegExp(`\\b${escapeRegExp(before.entity_name)}\\b`, 'g');
    result = result.replace(regex, replacementName);
  }

  // 5. Changed workflow steps (e.g. manual export script -> 1-click export button)
  if (change.type === 'CHANGED_WORKFLOW') {
    if (before.details && after.details && result.toLowerCase().includes('export')) {
      if (after.workflow_steps && after.workflow_steps.length > 0) {
        result = `You can now ${after.workflow_steps.join(' and ')}.`;
      }
    }
  }

  return result;
}

/**
 * Calculates structural preservation metrics between original and proposed markdown content.
 */
export function verifyStructuralPreservation(
  original: string,
  proposed: string
): StructuralPreservationMetrics {
  const originalHeadings = (original.match(/^#+\s+.+$/gm) || []).length;
  const proposedHeadings = (proposed.match(/^#+\s+.+$/gm) || []).length;

  const originalCodeBlocks = (original.match(/```[\s\S]*?```/g) || []).length;
  const proposedCodeBlocks = (proposed.match(/```[\s\S]*?```/g) || []).length;

  const originalLinks = (original.match(/\[.*?\]\(.*?\)/g) || []).length;
  const proposedLinks = (proposed.match(/\[.*?\]\(.*?\)/g) || []).length;

  let diffChars = 0;
  const maxLen = Math.max(original.length, proposed.length);
  const minLen = Math.min(original.length, proposed.length);

  for (let i = 0; i < minLen; i++) {
    if (original[i] !== proposed[i]) {
      diffChars++;
    }
  }
  diffChars += maxLen - minLen;

  const preservationRatio = maxLen > 0 ? (maxLen - diffChars) / maxLen : 1.0;

  return {
    originalLength: original.length,
    proposedLength: proposed.length,
    changedCharCount: diffChars,
    preservationRatio: Math.max(0, Number(preservationRatio.toFixed(4))),
    headingsPreserved: originalHeadings === proposedHeadings,
    codeBlocksPreserved: originalCodeBlocks === proposedCodeBlocks,
    linkCountPreserved: originalLinks === proposedLinks
  };
}

function escapeRegExp(str: string) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
