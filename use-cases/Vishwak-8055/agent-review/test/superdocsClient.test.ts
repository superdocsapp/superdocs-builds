import { describe, expect, it, vi } from "vitest";
import { SuperDocsApiError, SuperDocsClient } from "../src/superdocsClient";

function fakeFetch(handler: (url: string, init: RequestInit) => Response) {
  return vi.fn(async (url: string, init: RequestInit) => handler(url, init)) as unknown as typeof fetch;
}

describe("SuperDocsClient", () => {
  it("sends the Authorization header and correct path for listSessions", async () => {
    let capturedUrl = "";
    let capturedHeaders: unknown;
    const fetchImpl = fakeFetch((url, init) => {
      capturedUrl = url;
      capturedHeaders = init.headers;
      return new Response(JSON.stringify([{ session_id: "s1", message_count: 2, last_activity: "t" }]), {
        status: 200,
      });
    });
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl });
    const sessions = await client.listSessions();

    expect(capturedUrl).toBe("https://api.superdocs.app/v1/sessions");
    expect((capturedHeaders as Record<string, string>).Authorization).toBe("Bearer sk_test");
    expect(sessions).toHaveLength(1);
    expect(sessions[0]?.session_id).toBe("s1");
  });

  it("throws SuperDocsApiError with status, detail, and Retry-After on a non-2xx response", async () => {
    const fetchImpl = fakeFetch(
      () =>
        new Response(JSON.stringify({ detail: "Your monthly operation quota is exhausted." }), {
          status: 429,
          headers: { "Retry-After": "30" },
        })
    );
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl });

    await expect(client.listSessions()).rejects.toMatchObject({
      status: 429,
      detail: "Your monthly operation quota is exhausted.",
      retryAfterSeconds: 30,
    });
    await expect(client.listSessions()).rejects.toBeInstanceOf(SuperDocsApiError);
  });

  it("falls back to statusText when the error body isn't JSON", async () => {
    const fetchImpl = fakeFetch(
      () => new Response("<html>gateway error</html>", { status: 502, statusText: "Bad Gateway" })
    );
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl });
    await expect(client.listSessions()).rejects.toMatchObject({ status: 502, detail: "Bad Gateway" });
  });

  it("shapes a single-change approve request correctly", async () => {
    let capturedBody: unknown;
    const fetchImpl = fakeFetch((_url, init) => {
      capturedBody = JSON.parse(init.body as string);
      return new Response(JSON.stringify({ job_id: "j1", status: "completed" }), { status: 200 });
    });
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl });
    await client.approveChange("sess1", "job1", { changeId: "ch_1", approved: true });

    expect(capturedBody).toEqual({
      job_id: "job1",
      change_id: "ch_1",
      approved: true,
      feedback: undefined,
    });
  });

  it("shapes a batch approve request correctly", async () => {
    let capturedBody: unknown;
    const fetchImpl = fakeFetch((_url, init) => {
      capturedBody = JSON.parse(init.body as string);
      return new Response(JSON.stringify({ job_id: "j1", status: "completed" }), { status: 200 });
    });
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl });
    await client.approveChange("sess1", "job1", {
      approved: true,
      changes: [
        { change_id: "ch_1", approved: true },
        { change_id: "ch_2", approved: false },
      ],
    });

    expect(capturedBody).toEqual({
      job_id: "job1",
      approved: true,
      changes: [
        { change_id: "ch_1", approved: true },
        { change_id: "ch_2", approved: false },
      ],
    });
  });
});
