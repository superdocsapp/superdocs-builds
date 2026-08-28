import { describe, expect, it, vi } from "vitest";
import { SuperDocsClient, parseExportWarnings, extractBatches } from "../src/core/client";
import { ProposedChange, JobStatus } from "../src/core/types";
import * as fs from "fs";
import * as path from "path";

const FIX = path.join(__dirname, "fixtures");

function fixture(name: string): string {
  return fs.readFileSync(path.join(FIX, name), "utf8");
}

function mockClient(handler: (path: string, init: RequestInit) => Response): SuperDocsClient {
  const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url as string);
    return handler(u.pathname, init ?? {});
  }) as unknown as typeof fetch;
  return new SuperDocsClient("sk_test", {
    baseUrl: "https://api.superdocs.app",
    pollIntervalMs: 5,
    maxPollSeconds: 30,
    fetchImpl,
  });
}

describe("parseExportWarnings", () => {
  it("parses JSON array header", () => {
    const header = JSON.stringify([{ code: "math_partial_fidelity", message: "eq kept as LaTeX" }]);
    const w = parseExportWarnings(header);
    expect(w[0].code).toBe("math_partial_fidelity");
  });

  it("handles percent-encoded JSON", () => {
    const header = encodeURIComponent(JSON.stringify([{ code: "X", message: "y" }]));
    const w = parseExportWarnings(header);
    expect(w[0].code).toBe("X");
  });

  it("returns [] for absent header", () => {
    expect(parseExportWarnings(null)).toEqual([]);
  });

  it("wraps unparsable headers", () => {
    const w = parseExportWarnings("garbage{");
    expect(w[0].code).toBe("UNPARSED");
  });
});

describe("extractBatches", () => {
  it("parses JSON-stringified batches from intermediate responses", () => {
    const job = JSON.parse(fixture("job-done.json")) as JobStatus;
    const batches = extractBatches(job);
    expect(batches.length).toBeGreaterThanOrEqual(1);
    const b = batches[0];
    expect(["batch_approval", "single_approval"]).toContain(b.type);
    expect(Array.isArray(b.changes)).toBe(true);
    expect(b.changes[0].change_id).toBeTruthy();
    expect(b.changes[0].old_html).toContain("data-chunk-id");
  });
});

describe("client upload flow", () => {
  it("requestUploadUrl -> put -> process returns parsed doc metadata", async () => {
    const calls: string[] = [];
    const client = mockClient((p, init) => {
      calls.push(p);
      if (p === "/v1/uploads") {
        return new Response(
          JSON.stringify({ upload_id: "up1", upload_url: "https://bucket.example/up1", expires_at: "x", expires_in_seconds: 300, max_size_bytes: 104857600, curl_example: "curl" }),
          { status: 200 }
        );
      }
      if (p === "/up1" && init?.method === "PUT") {
        return new Response(null, { status: 200 });
      }
      if (p === "/v1/uploads/up1/process") {
        return new Response(
          JSON.stringify({
            session_id: "s1",
            filename: "proj.zip",
            chunks_count: 48,
            version_id: "v1",
            status: "completed",
            parse_mode: "document",
            warnings: [{ code: "TEX_PICTURE_PLACEHOLDER", message: "TikZ placeholder" }],
          }),
          { status: 200 }
        );
      }
      throw new Error("unexpected " + p);
    });
    const up = await client.requestUploadUrl({ filename: "proj.zip", content_type: "application/zip", size_bytes: 10 });
    expect(up.upload_id).toBe("up1");
    await client.putBytes("https://bucket.example/up1", new Uint8Array([1, 2]), "application/zip");
    const proc = await client.processUpload("up1", { session_id: "s1", filename: "proj.zip" });
    expect(proc.chunks_count).toBe(48);
    expect(proc.warnings?.[0]?.code).toBe("TEX_PICTURE_PLACEHOLDER");
    expect(calls).toEqual(["/v1/uploads", "/up1", "/v1/uploads/up1/process"]);
  });

  it("throws ApiError on 422", async () => {
    const client = mockClient(() => {
      return new Response(JSON.stringify({ detail: "bad" }), { status: 422 });
    });
    await expect(client.chatAsync({ message: "x", session_id: "s" })).rejects.toThrow(/422/);
  });
});

describe("client HITL poll", () => {
  it("fires onAwaitingApproval and completes", async () => {
    const awaiting = JSON.parse(fixture("job-awaiting.json")) as JobStatus;
    const done = JSON.parse(fixture("job-done.json")) as JobStatus;
    const states = [awaiting, done];
    const client = mockClient((p) => {
      if (p.startsWith("/v1/jobs/")) return new Response(JSON.stringify(states.shift()), { status: 200 });
      if (p.endsWith("/approve")) {
        return new Response(JSON.stringify({ status: "ok", batch_complete: true }), { status: 200 });
      }
      throw new Error("unexpected " + p);
    });
    const seen: ProposedChange[][] = [];
    const job = await client.poll("j1", {
      onAwaitingApproval: async (_job, changes) => {
        seen.push(changes);
        await client.approve("s1", {
          job_id: "j1",
          approved: true,
          changes: changes.map((c) => ({ change_id: c.change_id, approved: true })),
        });
      },
    });
    expect(job.status).toBe("completed");
    expect(seen.length).toBeGreaterThanOrEqual(1);
    expect(seen[0][0].chunk_id).toBeTruthy();
  });
});

describe("export", () => {
  it("parses X-Export-Warnings header from binary response", async () => {
    const warn = JSON.stringify([{ code: "math_partial_fidelity", message: "kept as latex" }]);
    const client = mockClient((p) => {
      if (p === "/v1/documents/export") {
        return new Response("not a real docx", {
          status: 200,
          headers: { "X-Export-Warnings": warn },
        });
      }
      throw new Error("unexpected " + p);
    });
    const r = await client.exportDocx("s1");
    expect(r.warnings[0].code).toBe("math_partial_fidelity");
  });
});
