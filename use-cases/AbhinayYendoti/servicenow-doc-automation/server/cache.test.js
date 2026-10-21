import { describe, expect, it, vi } from "vitest";

import { singleFlight, staleWhileRevalidate } from "./cache.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));

describe("singleFlight", () => {
  /**
   * The saving this exists for: an SSE connection, its safety poll and a
   * browser watchdog all reading the same job at the same moment used to be
   * three separate ~400ms calls to SuperDocs for identical bytes.
   */
  it("collapses concurrent calls for the same key into one", async () => {
    const load = vi.fn(async () => "job");
    const run = singleFlight();

    const results = await Promise.all([run("a", load), run("a", load), run("a", load)]);

    expect(load).toHaveBeenCalledTimes(1);
    expect(results).toEqual(["job", "job", "job"]);
  });

  it("keeps different keys independent", async () => {
    const load = vi.fn(async (key) => key);
    const run = singleFlight();

    await Promise.all([run("a", () => load("a")), run("b", () => load("b"))]);

    expect(load).toHaveBeenCalledTimes(2);
  });

  /** Sharing must be limited to concurrency, or it becomes a stale cache. */
  it("does not reuse a settled call", async () => {
    const load = vi.fn(async () => "job");
    const run = singleFlight();

    await run("a", load);
    await run("a", load);

    expect(load).toHaveBeenCalledTimes(2);
    expect(run.size()).toBe(0);
  });

  it("shares a rejection with every waiter and then clears it", async () => {
    const load = vi.fn(async () => {
      throw new Error("upstream down");
    });
    const run = singleFlight();

    const [first, second] = await Promise.allSettled([run("a", load), run("a", load)]);

    expect(load).toHaveBeenCalledTimes(1);
    expect(first.status).toBe("rejected");
    expect(second.status).toBe("rejected");
    expect(run.size()).toBe(0);
  });

  it("survives a loader that throws synchronously", async () => {
    const run = singleFlight();
    await expect(
      run("a", () => {
        throw new Error("boom");
      })
    ).rejects.toThrow("boom");
    expect(run.size()).toBe(0);
  });
});

describe("staleWhileRevalidate", () => {
  it("makes the first caller wait and everyone after it free", async () => {
    const load = vi.fn(async () => "healthy");
    let clock = 1000;
    const read = staleWhileRevalidate({ ttlMs: 100, load, now: () => clock });

    expect(await read()).toBe("healthy");
    expect(await read()).toBe("healthy");
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("serves the stale value immediately and refreshes behind it", async () => {
    let value = "first";
    const load = vi.fn(async () => value);
    let clock = 1000;
    const read = staleWhileRevalidate({ ttlMs: 100, load, now: () => clock });

    expect(await read()).toBe("first");

    value = "second";
    clock += 500; // now stale

    // The stale value comes back without waiting on the refresh.
    expect(await read()).toBe("first");
    expect(load).toHaveBeenCalledTimes(2);

    await tick();
    expect(await read()).toBe("second");
  });

  it("shares one refresh between simultaneous readers", async () => {
    const load = vi.fn(async () => "value");
    let clock = 1000;
    const read = staleWhileRevalidate({ ttlMs: 100, load, now: () => clock });

    await Promise.all([read(), read(), read()]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  /** A blip upstream must not blank out a value the UI is showing. */
  it("keeps serving the last good value when a refresh fails", async () => {
    let fail = false;
    const load = vi.fn(async () => {
      if (fail) throw new Error("upstream down");
      return "healthy";
    });

    let clock = 1000;
    const onError = vi.fn();
    const read = staleWhileRevalidate({ ttlMs: 100, load, onError, now: () => clock });

    expect(await read()).toBe("healthy");

    fail = true;
    clock += 500;
    await read();
    await tick();

    expect(onError).toHaveBeenCalled();
    expect(await read()).toBe("healthy");
  });

  it("retries sooner than a full TTL after a failure", async () => {
    const load = vi.fn(async () => {
      throw new Error("down");
    });

    let clock = 1000;
    const read = staleWhileRevalidate({ ttlMs: 100, load, onError: () => {}, now: () => clock });

    await read();
    await tick();
    expect(load).toHaveBeenCalledTimes(1);

    // Half a TTL later it is due again, rather than waiting a whole one.
    clock += 60;
    await read();
    await tick();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("primes without a caller waiting on it", async () => {
    const load = vi.fn(async () => "primed");
    let clock = 1000;
    const read = staleWhileRevalidate({ ttlMs: 100, load, now: () => clock });

    await read.prime();
    expect(read.peek()).toBe("primed");
    expect(load).toHaveBeenCalledTimes(1);
  });
});
