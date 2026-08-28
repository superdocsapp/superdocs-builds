import { describe, it, expect } from 'vitest';
import { canonicalStringify, stableHash } from '../../src/evidence/serialize.js';
import { fnv1a, contentFingerprint } from '../../src/evidence/hash.js';

describe('canonicalStringify', () => {
  it('produces identical output regardless of object key insertion order', () => {
    const a = { z: 1, a: 2, m: { y: 1, x: 2 } };
    const b = { a: 2, z: 1, m: { x: 2, y: 1 } };
    expect(canonicalStringify(a)).toBe(canonicalStringify(b));
  });

  it('preserves array order, since order inside an array is meaningful data', () => {
    expect(canonicalStringify([1, 2, 3])).not.toBe(canonicalStringify([3, 2, 1]));
  });
});

describe('stableHash', () => {
  it('is deterministic for the same logical value', () => {
    const value = { changed_regions: [{ id: 'p1' }], decision: 'VERIFIED' };
    expect(stableHash(value)).toBe(stableHash(JSON.parse(JSON.stringify(value))));
  });

  it('differs when the content differs', () => {
    expect(stableHash({ decision: 'VERIFIED' })).not.toBe(stableHash({ decision: 'BLOCKED' }));
  });
});

describe('hash primitives', () => {
  it('fnv1a is deterministic and produces 8 hex characters', () => {
    const h1 = fnv1a('hello world');
    const h2 = fnv1a('hello world');
    expect(h1).toBe(h2);
    expect(h1).toMatch(/^[0-9a-f]{8}$/);
  });

  it('contentFingerprint distinguishes near-identical strings', () => {
    expect(contentFingerprint('shall')).not.toBe(contentFingerprint('may'));
  });
});
