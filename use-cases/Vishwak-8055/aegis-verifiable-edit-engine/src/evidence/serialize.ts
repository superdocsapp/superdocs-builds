import { contentFingerprint } from './hash.js';

/**
 * Stringifies a value with recursively sorted object keys, so the same
 * logical EditProof always serializes to the exact same bytes regardless of
 * property insertion order. This is what makes `proof_hash` meaningful and
 * what makes two proofs diffable/comparable in tests and the benchmark.
 *
 * Arrays keep their given order — order inside an array is meaningful data
 * (e.g. `changed_regions`), not incidental like object key order is.
 */
export function canonicalStringify(value: unknown): string {
  return JSON.stringify(sortKeysDeep(value));
}

function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortKeysDeep);
  }
  if (value !== null && typeof value === 'object') {
    if (value instanceof Date) return value.toISOString();
    const sortedKeys = Object.keys(value as Record<string, unknown>).sort();
    const out: Record<string, unknown> = {};
    for (const key of sortedKeys) {
      out[key] = sortKeysDeep((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

/**
 * Computes the content fingerprint of a value using canonical serialization.
 * Used for `evidence.proof_hash` — hash everything in the proof except the
 * hash field itself (callers pass the proof with that field already stripped
 * or set to a placeholder that is excluded before hashing).
 */
export function stableHash(value: unknown): string {
  return contentFingerprint(canonicalStringify(value));
}
