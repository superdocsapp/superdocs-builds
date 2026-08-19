import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { request, requestJson, UpstreamError } from "@/lib/http";
import { once, _resetIdempotencyStore } from "@/lib/idempotency";

/**
 * These run against a real HTTP server on localhost, not a stubbed `fetch`.
 *
 * The distinction matters. Stubbing `fetch` proves the code calls the stub the
 * way the test expects, which is a tautology. A real socket exercises the
 * actual retry loop, the actual abort signal, and the actual response parsing,
 * and it is the only way to test a timeout without faking time.
 *
 * No key, no network, no cost. `npm test` runs this on a fresh clone.
 */

let server: Server;
let base: string;

/** Per-path request counters, so a test can assert how many attempts happened. */
const hits: Record<string, number> = {};

beforeAll(async () => {
  server = createServer((req, res) => {
    const path = req.url ?? "/";
    hits[path] = (hits[path] ?? 0) + 1;

    if (path === "/ok") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ hello: "world" }));
      return;
    }

    if (path === "/flaky") {
      // Fails twice, then succeeds: the shape of a real transient outage.
      if (hits[path] < 3) {
        res.writeHead(503);
        res.end("service unavailable");
        return;
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ recovered: true, attempts: hits[path] }));
      return;
    }

    if (path === "/bad-request") {
      res.writeHead(400);
      res.end("missing field: session_id");
      return;
    }

    if (path === "/unauthorized") {
      res.writeHead(401);
      res.end("invalid key");
      return;
    }

    if (path === "/rate-limited") {
      res.writeHead(429);
      res.end("operation limit reached");
      return;
    }

    if (path === "/slow") {
      // Never responds. The client's deadline is the only thing that ends this.
      return;
    }

    if (path === "/not-json") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end("<html><body>502 Bad Gateway</body></html>");
      return;
    }

    res.writeHead(404);
    res.end("nope");
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

const instant = async () => {};

describe("request", () => {
  it("returns the response on success", async () => {
    const res = await request(`${base}/ok`, { operation: "test" });
    expect(res.status).toBe(200);
  });

  it("retries a 503 and succeeds once the server recovers", async () => {
    const data = await requestJson<{ recovered: boolean; attempts: number }>(`${base}/flaky`, {
      operation: "test",
      retries: 3,
      sleep: instant,
    });
    expect(data.recovered).toBe(true);
    expect(data.attempts).toBe(3);
  });

  it("does NOT retry a 400: retrying a malformed request just spends the budget again", async () => {
    hits["/bad-request"] = 0;
    await expect(request(`${base}/bad-request`, { operation: "start draft", retries: 3, sleep: instant })).rejects.toThrow(
      UpstreamError,
    );
    expect(hits["/bad-request"]).toBe(1);
  });

  it("does not retry a 401", async () => {
    hits["/unauthorized"] = 0;
    await expect(request(`${base}/unauthorized`, { operation: "test", retries: 3, sleep: instant })).rejects.toThrow();
    expect(hits["/unauthorized"]).toBe(1);
  });

  it("names the fix for an auth failure instead of just the status", async () => {
    try {
      await request(`${base}/unauthorized`, { operation: "start draft", retries: 0 });
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(UpstreamError);
      expect((err as UpstreamError).fix).toMatch(/SUPERDOCS_API_KEY/);
    }
  });

  it("names the operation budget for a 429", async () => {
    try {
      await request(`${base}/rate-limited`, { operation: "start draft", retries: 0 });
      expect.unreachable("should have thrown");
    } catch (err) {
      expect((err as UpstreamError).fix).toMatch(/operation limit/i);
    }
  });

  it("aborts a hanging request at the deadline rather than waiting forever", async () => {
    const started = Date.now();
    try {
      await request(`${base}/slow`, { operation: "export", timeoutMs: 300, retries: 0 });
      expect.unreachable("should have timed out");
    } catch (err) {
      expect(Date.now() - started).toBeLessThan(3000);
      expect((err as UpstreamError).fix).toMatch(/did not respond within 300ms/);
    }
  });

  it("gives up after the retry budget rather than looping", async () => {
    hits["/rate-limited"] = 0;
    await expect(
      request(`${base}/rate-limited`, { operation: "test", retries: 2, sleep: instant }),
    ).rejects.toThrow();
    expect(hits["/rate-limited"]).toBe(3); // first attempt + 2 retries
  });

  it("never leaks the API key into the client-facing error", async () => {
    try {
      await request(`${base}/unauthorized`, {
        operation: "test",
        retries: 0,
        headers: { Authorization: "Bearer sk-secret-value" },
      });
      expect.unreachable("should have thrown");
    } catch (err) {
      const client = JSON.stringify((err as UpstreamError).toClient());
      expect(client).not.toContain("sk-secret-value");
      expect(client).not.toContain("invalid key");
    }
  });
});

describe("requestJson", () => {
  it("parses a JSON body", async () => {
    expect(await requestJson<{ hello: string }>(`${base}/ok`, { operation: "test" })).toEqual({ hello: "world" });
  });

  it("reports a non-JSON body clearly instead of throwing a raw SyntaxError", async () => {
    try {
      await requestJson(`${base}/not-json`, { operation: "job status" });
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(UpstreamError);
      expect((err as UpstreamError).fix).toMatch(/non-JSON body/);
    }
  });
});

describe("idempotency", () => {
  it("runs the work once for a repeated key", async () => {
    _resetIdempotencyStore();
    let calls = 0;
    const work = async () => {
      calls++;
      return { job_id: "j1" };
    };

    const first = await once("k1", work);
    const second = await once("k1", work);

    expect(calls).toBe(1);
    expect(first.replayed).toBe(false);
    expect(second.replayed).toBe(true);
    expect(second.value).toEqual({ job_id: "j1" });
  });

  it("collapses concurrent duplicates instead of racing them", async () => {
    _resetIdempotencyStore();
    let calls = 0;
    const work = async () => {
      calls++;
      await new Promise((r) => setTimeout(r, 50));
      return { job_id: "j2" };
    };

    // The double-click case: both requests arrive before either finishes.
    const [a, b] = await Promise.all([once("k2", work), once("k2", work)]);

    expect(calls).toBe(1);
    expect(a.value).toEqual(b.value);
  });

  it("keeps different keys independent", async () => {
    _resetIdempotencyStore();
    let calls = 0;
    const work = async () => {
      calls++;
      return calls;
    };
    await once("a", work);
    await once("b", work);
    expect(calls).toBe(2);
  });

  it("does not cache a failure, so the user can retry after fixing it", async () => {
    _resetIdempotencyStore();
    let calls = 0;
    const failing = async () => {
      calls++;
      throw new Error("upstream down");
    };

    await expect(once("k3", failing)).rejects.toThrow("upstream down");
    await expect(once("k3", failing)).rejects.toThrow("upstream down");
    expect(calls).toBe(2);
  });
});
