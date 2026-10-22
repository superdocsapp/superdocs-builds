import { describe, it, expect } from 'vitest';
import { generateSurgicalEdit } from '../../src/core/surgical-editor.js';
import { Article, ChangeEvent, EvidenceItem } from '../../src/core/types.js';

describe('Surgical Edit Generation (Test 6)', () => {
  const article: Article = {
    id: 'art-edit-sample',
    title: 'Storage Policy',
    content: '# Storage Policy\n\nAttachments can be uploaded to documents. The file size limit is 5 MB per document. Contact support for higher tiers.',
    version: 1,
    metadata: {},
    screenshots: [],
    last_updated: '2026-06-10'
  };

  const change: ChangeEvent = {
    id: 'change-size-up',
    type: 'CHANGED_LIMIT',
    title: 'Attachment limit raised',
    description: 'Raised from 5 MB to 25 MB',
    before_state: { value: '5 MB' },
    after_state: { value: '25 MB' },
    effective_date: '2026-08-22',
    source: 'Infra'
  };

  const evidence: EvidenceItem[] = [
    {
      sentence_index: 1,
      sentence_text: 'The file size limit is 5 MB per document.',
      matched_terms: ['5 MB'],
      explanation: 'Old file size limit',
      is_indirect: false,
      start_offset: 58,
      end_offset: 99
    }
  ];

  it('modifies only the affected sentence and retains exact surrounding content', () => {
    const proposal = generateSurgicalEdit(article, change, evidence);
    expect(proposal).not.toBeNull();
    expect(proposal?.proposed_content).toBe(
      '# Storage Policy\n\nAttachments can be uploaded to documents. The file size limit is 25 MB per document. Contact support for higher tiers.'
    );
    expect(proposal?.changed_spans).toHaveLength(1);
    expect(proposal?.changed_spans[0].original_text).toBe('The file size limit is 5 MB per document.');
    expect(proposal?.changed_spans[0].replacement_text).toBe('The file size limit is 25 MB per document.');
  });
});
