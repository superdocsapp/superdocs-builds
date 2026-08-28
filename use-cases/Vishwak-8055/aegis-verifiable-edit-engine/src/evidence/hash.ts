/**
 * Deterministic, dependency-free hashing.
 *
 * This is intentionally NOT a cryptographic hash. Aegis uses hashes for two
 * purposes only: (1) fingerprinting document blocks so the aligner can tell
 * "same paragraph, edited" from "different paragraph", and (2) giving an
 * EditProof a stable content fingerprint for evidence/audit purposes. Neither
 * use case needs collision-resistance against an adversary who can choose
 * document content, and a dependency-free implementation means the exact same
 * function runs in Node (CLI, tests, benchmark) and in the browser UI without
 * a bundler or a polyfill. If a deployment needs a cryptographic content hash
 * (e.g. for tamper-evidence of a stored proof), swap this module for one
 * backed by Web Crypto / Node's `crypto` — every caller goes through the two
 * functions exported here, so that is a one-file change.
 */

/** FNV-1a 32-bit, returned as an 8-character lowercase hex string. */
export function fnv1a(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  // Convert to unsigned 32-bit and pad to 8 hex chars.
  return (hash >>> 0).toString(16).padStart(8, '0');
}

/**
 * A slightly longer, lower-collision fingerprint for content identity
 * (document blocks, whole-document snapshots). Runs FNV-1a twice with
 * different seeds over the string and its reverse, which is enough entropy
 * to tell apart the small, structured strings Aegis hashes (block text,
 * canonical JSON) without needing a real cryptographic primitive.
 */
export function contentFingerprint(input: string): string {
  const forward = fnv1a(input);
  const backward = fnv1a(`${input.length}:${reverse(input)}`);
  return `${forward}${backward}`;
}

function reverse(s: string): string {
  let out = '';
  for (let i = s.length - 1; i >= 0; i--) out += s[i];
  return out;
}
