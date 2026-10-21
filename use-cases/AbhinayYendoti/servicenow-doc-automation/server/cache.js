/**
 * Two small caching primitives, kept here so they can be tested on their own
 * rather than inferred from the behaviour of a route.
 *
 * Both exist for the same reason: this server sits in front of a metered,
 * ~400ms-per-call upstream, and the naive shape of "every caller asks" turns
 * one piece of information into N round trips.
 */

/**
 * One in-flight call per key, shared by everyone who asks for it meanwhile.
 *
 * A run is watched by an SSE connection with its own safety poll, by a watchdog
 * poll in the browser, and possibly by a second tab. Those land within
 * milliseconds of each other wanting the identical job, so without this each is
 * a separate round trip returning the same bytes.
 *
 * Only *concurrent* calls are shared: once a call settles its entry is dropped,
 * so this never serves a stale value.
 */
export function singleFlight() {
  const inFlight = new Map();

  const run = (key, load) => {
    const existing = inFlight.get(key);
    if (existing) return existing;

    const pending = (async () => load())().finally(() => inFlight.delete(key));

    inFlight.set(key, pending);
    return pending;
  };

  run.size = () => inFlight.size;
  return run;
}

/**
 * Serve the cached value immediately and refresh in the background.
 *
 * For things that are read constantly, change rarely, and cost a round trip to
 * learn — upstream health, the account's remaining quota. Only the very first
 * read waits; every one after it is free, and a refresh already in flight is
 * shared rather than duplicated.
 *
 * A failed refresh keeps serving the last good value and retries sooner than a
 * full TTL, so a brief upstream blip does not blank the value out.
 */
export function staleWhileRevalidate({ ttlMs, load, onError, now = Date.now }) {
  const entry = { at: 0, value: null, pending: null };

  const refresh = () => {
    entry.pending ??= Promise.resolve()
      .then(load)
      .then((value) => {
        entry.value = value;
        entry.at = now();
        return value;
      })
      .catch((error) => {
        onError?.(error);
        entry.at = now() - ttlMs / 2;
        return entry.value;
      })
      .finally(() => {
        entry.pending = null;
      });

    return entry.pending;
  };

  const read = () => {
    const primed = entry.at !== 0;

    if (primed && now() - entry.at < ttlMs) return Promise.resolve(entry.value);

    const pending = refresh();
    // Nothing cached yet, so this caller has to wait. Everyone after it does not.
    return primed ? Promise.resolve(entry.value) : pending;
  };

  read.peek = () => entry.value;
  read.prime = () => refresh();
  return read;
}
