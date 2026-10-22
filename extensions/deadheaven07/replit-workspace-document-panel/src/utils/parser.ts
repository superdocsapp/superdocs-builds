import { ProposedChangeBatch, ProposedChange } from '../types/superdocs';

export function parseProposedChangeBatch(content: string): ProposedChangeBatch {
  try {
    const outer = JSON.parse(content);
    if (!outer || typeof outer !== 'object') {
      throw new Error('Outer JSON is not an object');
    }

    if (!('content' in outer)) {
      throw new Error("Missing 'content' field in proposed_change_batch");
    }

    const innerContent = outer.content;
    let batchData: Record<string, unknown>;

    if (typeof innerContent === 'string') {
      batchData = JSON.parse(innerContent);
    } else if (typeof innerContent === 'object' && innerContent !== null) {
      batchData = innerContent as Record<string, unknown>;
    } else {
      throw new Error("'content' field is not a string or object");
    }

    if (!batchData || typeof batchData !== 'object') {
      throw new Error('Inner JSON is not an object');
    }

    const changes: ProposedChange[] = [];
    const changesArray = batchData.changes as unknown[] | undefined;

    if (Array.isArray(changesArray)) {
      for (const changeData of changesArray) {
        if (changeData && typeof changeData === 'object') {
          const c = changeData as Record<string, unknown>;
          changes.push({
            change_id: String(c.change_id ?? ''),
            operation: String(c.operation ?? ''),
            chunk_id: c.chunk_id ? String(c.chunk_id) : undefined,
            old_html: c.old_html ? String(c.old_html) : undefined,
            new_html: c.new_html ? String(c.new_html) : undefined,
            ai_explanation: String(c.ai_explanation ?? ''),
            insert_after_chunk_id: c.insert_after_chunk_id ? String(c.insert_after_chunk_id) : undefined,
            document_id: c.document_id ? String(c.document_id) : undefined,
          });
        }
      }
    }

    return {
      batch_id: String(batchData.batch_id ?? ''),
      batch_total: Number(batchData.batch_total ?? changes.length),
      changes,
      awaiting_kind: String(batchData.awaiting_kind ?? 'approval'),
      continue_prompt: batchData.continue_prompt as Record<string, unknown> | undefined,
    };
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error(`JSON parse error: ${error.message}`);
    }
    throw error;
  }
}