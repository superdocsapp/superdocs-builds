import {describe, expect, it} from 'vitest';
import {initial} from './evidence';

describe('LineCard review evidence', () => {
  it('starts with safety, procedure, and exact specification evidence', () => {
    expect(initial.map(item => item.id)).toEqual(['SAFE-001', 'STEP-001', 'SPEC-001']);
    expect(initial.find(item => item.id === 'SPEC-001')?.quote).toBe('24 N·m ± 2 N·m');
  });
});
