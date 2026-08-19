import { isNoOpChange } from "./diff";
import { textFromHtml } from "./textFromHtml";
import type { PendingChange } from "./types";

/**
 * SuperDocs sometimes proposes the same edit once per chunk instead of once
 * for the document — a document-wide styling instruction ("add space between
 * paragraphs") lands as N chunk-level edits with identical explanations, each
 * a no-op in the text diff (a CSS-only change has no text difference to show).
 * Reviewing four identical cards one at a time is not four decisions, so
 * changes are grouped: same explanation and no visible text difference
 * collapses into one reviewable unit whose decision applies to every
 * change_id in the group.
 *
 * A change that *does* have a visible text difference is never grouped, even
 * if its explanation matches another change's — two edits that both say
 * "tightened the phrasing" but touch different paragraphs are two decisions.
 */
export interface ChangeGroup {
  key: string;
  explanation: string;
  changeIds: string[];
  sample: PendingChange;
}

export function groupChanges(changes: PendingChange[]): ChangeGroup[] {
  const noOpGroups = new Map<string, ChangeGroup>();
  const result: ChangeGroup[] = [];

  for (const change of changes) {
    const before = textFromHtml(change.old_html);
    const after = textFromHtml(change.new_html);

    if (isNoOpChange(before, after)) {
      const key = `noop:${change.ai_explanation}`;
      const existing = noOpGroups.get(key);
      if (existing) {
        existing.changeIds.push(change.change_id);
        continue;
      }
      const group: ChangeGroup = {
        key,
        explanation: change.ai_explanation,
        changeIds: [change.change_id],
        sample: change,
      };
      noOpGroups.set(key, group);
      result.push(group);
      continue;
    }

    result.push({
      key: change.change_id,
      explanation: change.ai_explanation,
      changeIds: [change.change_id],
      sample: change,
    });
  }

  return result;
}
