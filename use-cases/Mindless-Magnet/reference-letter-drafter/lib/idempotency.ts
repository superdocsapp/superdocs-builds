import "server-only";

/**
 * Idempotency for the one operation in this app that costs money.
 *
 * Starting a draft spends a SuperDocs operation. A double-clicked button, a
 * React strict-mode double render, or a user hitting refresh mid-request will
 * otherwise buy two letters and show one.
 *
 * The client sends a key derived from the intake content. The first request
 * with a given key does the work and its result is remembered; every later
 * request with that key gets the same answer back without touching SuperDocs.
 * In-flight duplicates await the original promise rather than racing it, which
 * is the case a naive "check then set" cache misses entirely.
 *
 * LIMITATION, stated plainly: this is process-local memory. One Next.js server,
 * one map. Behind two instances, or after a restart, a duplicate request can
 * still get through. That is the honest trade for a build with no database, and
 * it is the right one at this size: a Redis dependency to protect a demo from a
 * double-click is the kind of infrastructure that makes a project impossible to
 * run from a fresh clone. If this app ever ran for real users it would move to
 * a shared store keyed the same way, and nothing else about the design changes.
 */

interface Entry<T> {
  promise: Promise<T>;
  createdAt: number;
}

const TTL_MS = 10 * 60 * 1000;
const MAX_ENTRIES = 500;

const store = new Map<string, Entry<unknown>>();

function evictExpired(now: number): void {
  for (const [key, entry] of store) {
    if (now - entry.createdAt > TTL_MS) store.delete(key);
  }
  // Hard cap so a long-lived process cannot grow this without bound.
  while (store.size > MAX_ENTRIES) {
    const oldest = store.keys().next();
    if (oldest.done) break;
    store.delete(oldest.value);
  }
}

export async function once<T>(key: string, work: () => Promise<T>): Promise<{ value: T; replayed: boolean }> {
  const now = Date.now();
  evictExpired(now);

  const existing = store.get(key) as Entry<T> | undefined;
  if (existing) {
    return { value: await existing.promise, replayed: true };
  }

  const promise = work();
  store.set(key, { promise: promise as Promise<unknown>, createdAt: now });

  try {
    return { value: await promise, replayed: false };
  } catch (err) {
    // A failed attempt must not be cached: the user should be able to retry
    // after fixing whatever broke. Only successes are idempotent.
    store.delete(key);
    throw err;
  }
}

/** Test seam. */
export function _resetIdempotencyStore(): void {
  store.clear();
}
