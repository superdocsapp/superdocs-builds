import { describe, it, expect } from 'vitest';
import { generateSurgicalEdit, verifyStructuralPreservation } from '../../src/core/surgical-editor.js';
import { Article, ChangeEvent, EvidenceItem } from '../../src/core/types.js';

describe('Article Structural Preservation (Test 7)', () => {
  const structuredArticle: Article = {
    id: 'art-structured',
    title: 'Developer Guide',
    content: `# Developer Integration Guide

Here is an introduction paragraph.

## Rate Limits

- Limit is strictly 10,000 API calls per month for Pro.
- Standard throttling applies at threshold.

\`\`\`typescript
const client = new SuperDocsClient({ apiKey: 'key' });
await client.sync();
\`\`\`

Visit the [Documentation Portal](https://docs.superdocs.app) for details.`,
    version: 1,
    metadata: {},
    screenshots: [],
    last_updated: '2026-06-01'
  };

  const change: ChangeEvent = {
    id: 'change-pro-limit',
    type: 'CHANGED_LIMIT',
    title: 'Pro limit bump',
    description: 'Pro limit increased from 10,000 to 25,000',
    before_state: { value: 10000 },
    after_state: { value: 25000 },
    effective_date: '2026-08-01',
    source: 'Release'
  };

  const evidence: EvidenceItem[] = [
    {
      sentence_index: 2,
      sentence_text: 'Limit is strictly 10,000 API calls per month for Pro.',
      matched_terms: ['10,000'],
      explanation: 'Old API limit',
      is_indirect: false,
      start_offset: 100,
      end_offset: 153
    }
  ];

  it('guarantees preservation of headings, code blocks, links, and list formatting', () => {
    const proposal = generateSurgicalEdit(structuredArticle, change, evidence);
    expect(proposal).not.toBeNull();

    const metrics = verifyStructuralPreservation(structuredArticle.content, proposal!.proposed_content);
    expect(metrics.headingsPreserved).toBe(true);
    expect(metrics.codeBlocksPreserved).toBe(true);
    expect(metrics.linkCountPreserved).toBe(true);
    expect(metrics.preservationRatio).toBeGreaterThan(0.95);
    expect(proposal!.proposed_content).toContain('Limit is strictly 25,000 API calls per month for Pro.');
    expect(proposal!.proposed_content).toContain('```typescript');
    expect(proposal!.proposed_content).toContain('[Documentation Portal](https://docs.superdocs.app)');
  });
});
