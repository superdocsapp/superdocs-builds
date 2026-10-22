import { describe, it, expect } from 'vitest';
import { verifyASTInvariance } from '../../src/core/ast-verifier.js';
import { KnowledgeBaseConsistencyChecker } from '../../src/core/consistency-checker.js';
import { Article } from '../../src/core/types.js';

describe('AST Byte-Level Invariance & Multi-Document Consistency', () => {
  const originalDoc = `# Billing Limits\n\n| Plan | Rate Quota |\n|---|---|\n| Free | 1,000 |\n| Pro | 10,000 |\n\nThe Pro plan includes 10,000 API calls per month.\n\n\`\`\`typescript\nconst client = new SuperDocsClient({ maxCalls: 10000 });\n\`\`\`\n\nRefer to [API Docs](https://docs.superdocs.io/api) for details.`;
  const proposedDoc = `# Billing Limits\n\n| Plan | Rate Quota |\n|---|---|\n| Free | 1,000 |\n| Pro | 10,000 |\n\nThe Pro plan includes 25,000 API calls per month.\n\n\`\`\`typescript\nconst client = new SuperDocsClient({ maxCalls: 10000 });\n\`\`\`\n\nRefer to [API Docs](https://docs.superdocs.io/api) for details.`;

  it('proves 100% byte invariance for untouched markdown headers, code, tables, and links', () => {
    const proof = verifyASTInvariance(
      originalDoc,
      proposedDoc,
      'The Pro plan includes 10,000 API calls per month.',
      'The Pro plan includes 25,000 API calls per month.'
    );

    expect(proof.headingsPreserved).toBe(true);
    expect(proof.codeBlocksPreserved).toBe(true);
    expect(proof.tablesPreserved).toBe(true);
    expect(proof.linksPreserved).toBe(true);
    expect(proof.nonTargetBytesPreserved).toBe(true);
    expect(proof.preservationRatio).toBeGreaterThanOrEqual(0.989);
    expect(proof.isProofValid).toBe(true);
  });

  it('scans multi-document portfolio and detects cross-document limit contradictions', () => {
    const docA: Article = {
      id: 'doc-01',
      title: 'Doc A',
      content: 'The attachment file size limit is 5 MB per document.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-08-27'
    };

    const docB: Article = {
      id: 'doc-02',
      title: 'Doc B',
      content: 'The attachment file size limit is 25 MB per document.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-08-27'
    };

    const checker = new KnowledgeBaseConsistencyChecker([docA, docB]);
    const report = checker.checkConsistency();

    expect(report.violations.length).toBeGreaterThan(0);
    expect(report.violations[0].rule).toBe('CONTRADICTING_LIMITS');
    expect(report.violations[0].articles).toContain('doc-01');
    expect(report.violations[0].articles).toContain('doc-02');
  });
});
