import { describe, it, expect } from 'vitest';
import { classifyFindings, assessRisk, decide } from '../../src/risk/decisionEngine.js';
import { loadPolicy } from '../../src/risk/severityPolicy.js';
import type { Finding } from '../../src/types/verification.js';

function finding(kind: string): Finding {
  return { id: `f:${kind}`, checker: 'structural', kind, confidence: 1, message: 'test' };
}

describe('decision engine', () => {
  const policy = loadPolicy();

  it('maps no findings to VERIFIED', () => {
    const classified = classifyFindings([], policy);
    const risk = assessRisk(classified);
    expect(decide(risk, policy)).toBe('VERIFIED');
  });

  it('maps a LOW-only finding to VERIFIED', () => {
    const classified = classifyFindings([finding('FORMATTING_ONLY_CHANGE')], policy);
    expect(decide(assessRisk(classified), policy)).toBe('VERIFIED');
  });

  it('maps a MEDIUM finding to VERIFIED_WITH_WARNINGS', () => {
    const classified = classifyFindings([finding('STRUCTURAL_BLOCK_INSERTED')], policy);
    expect(decide(assessRisk(classified), policy)).toBe('VERIFIED_WITH_WARNINGS');
  });

  it('maps a HIGH finding to REQUIRES_REVIEW', () => {
    const classified = classifyFindings([finding('PROTECTED_VALUE_CURRENCY_CHANGED')], policy);
    expect(decide(assessRisk(classified), policy)).toBe('REQUIRES_REVIEW');
  });

  it('maps a CRITICAL finding to BLOCKED even alongside lower-severity findings', () => {
    const classified = classifyFindings(
      [finding('FORMATTING_ONLY_CHANGE'), finding('STRUCTURAL_BLOCK_INSERTED'), finding('SEMANTIC_OBLIGATION_TO_PERMISSION')],
      policy,
    );
    const risk = assessRisk(classified);
    expect(risk.highestSeverity).toBe('CRITICAL');
    expect(decide(risk, policy)).toBe('BLOCKED');
  });

  it('never returns success for an unrecognized decision threshold (fails closed)', () => {
    const brokenPolicy = { ...policy, decisionThresholds: { ...policy.decisionThresholds, CRITICAL: 'NOT_A_REAL_DECISION' } };
    const classified = classifyFindings([finding('SEMANTIC_OBLIGATION_TO_PERMISSION')], policy);
    const risk = assessRisk(classified);
    expect(decide(risk, brokenPolicy)).toBe('REQUIRES_REVIEW');
  });
});
