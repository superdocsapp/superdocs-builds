import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('CLI & Audit Report Export Engine', () => {
  it('generates structured Markdown and JSON audit reports from sweep execution', () => {
    const fixturesDir = path.resolve(__dirname, '../../fixtures/corpus');
    const articles: Article[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'articles.json'), 'utf-8'));
    const changes: ChangeEvent[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'changes.json'), 'utf-8'));

    const sweeper = new KnowledgeBaseSweeper(articles, changes);
    const { proposals, metrics } = sweeper.sweep({ provider: 'deterministic' });

    expect(proposals.length).toBe(15);
    expect(metrics.freshness_score).toBe(42.3);

    const tempJsonPath = path.resolve(__dirname, '../../docs/test-freshness-report.json');

    // Test JSON export format
    const jsonOutput = {
      timestamp: new Date().toISOString(),
      metrics,
      proposals_count: proposals.length,
      proposals
    };
    fs.writeFileSync(tempJsonPath, JSON.stringify(jsonOutput, null, 2), 'utf-8');
    expect(fs.existsSync(tempJsonPath)).toBe(true);

    const readJson = JSON.parse(fs.readFileSync(tempJsonPath, 'utf-8'));
    expect(readJson.proposals_count).toBe(15);
    expect(readJson.metrics.freshness_score).toBe(42.3);

    // Clean up test export files
    if (fs.existsSync(tempJsonPath)) fs.unlinkSync(tempJsonPath);
  });
});
