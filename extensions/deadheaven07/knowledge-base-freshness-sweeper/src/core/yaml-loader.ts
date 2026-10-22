import fs from 'fs';
import YAML from 'yaml';
import { GroundTruthEntry } from './types.js';

export interface ExpectedYamlStructure {
  version: string;
  corpus_size: number;
  created_at: string;
  protocol: string;
  summary_expectations: {
    total_articles: number;
    affected_articles: number;
    unchanged_articles: number;
    could_not_assess_articles: number;
    screenshots_requiring_replacement: number;
    adversarial_trap_count: number;
    ambiguous_context_count: number;
  };
  articles: GroundTruthEntry[];
}

export function loadExpectedYaml(filePath: string): ExpectedYamlStructure {
  const content = fs.readFileSync(filePath, 'utf-8');
  const parsed = YAML.parse(content) as ExpectedYamlStructure;
  return parsed;
}

export function loadGroundTruthFromYaml(filePath: string): GroundTruthEntry[] {
  const structured = loadExpectedYaml(filePath);
  return structured.articles;
}
