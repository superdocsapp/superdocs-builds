import { describe, expect, it } from "vitest";
import {
  SigmaSuperDocsClient,
  type WriterRequest,
} from "../src/api";

const recorder = () => {
  const requests: WriterRequest[] = [];
  const client = new SigmaSuperDocsClient(async (request) => {
    requests.push(request);
    return request.responseType === "blob" ? new Blob(["docx"]) : { ok: true };
  });
  return { client, requests };
};

describe("Sigma request contracts", () => {
  it("sends upload and async chat through the named connection without credentials", async () => {
    const { client, requests } = recorder();
    await client.upload("<p>Selected</p>", "session-1");
    await client.startChat("session-1", "Tighten this");

    expect(requests[0]).toMatchObject({
      url: "https://api.superdocs.app/v1/documents/upload",
      type: "POST",
      connectionLinkName: "superdocsapi",
      sendAsFile: true,
      postBody: { session_id: "session-1", open_mode: "replace" },
      data: { index: "true" },
    });
    expect(requests[0]?.fileObj?.[0]).toBeInstanceOf(File);
    expect(requests[1]).toMatchObject({
      url: "https://api.superdocs.app/v1/chat/async",
      connectionLinkName: "superdocsapi",
      postBody: {
        session_id: "session-1",
        message: "Tighten this",
        approval_mode: "ask_every_time",
        response_mode: "full",
        async_mode: true,
      },
    });
    expect(JSON.stringify(requests)).not.toContain("Authorization");
    expect(JSON.stringify(requests)).not.toMatch(/\bsk_[A-Za-z0-9_-]{12,}/);
  });

  it("uses exact approval and continue request shapes", async () => {
    const { client, requests } = recorder();
    await client.approve("session-1", {
      job_id: "job-1",
      approved: false,
      changes: [
        { change_id: "c1", approved: true },
        { change_id: "c2", approved: false },
      ],
    });
    await client.continueChat("session-1", "job-1", true);

    expect(requests[0]).toMatchObject({
      url: "https://api.superdocs.app/v1/chat/session-1/approve",
      type: "POST",
      postBody: {
        job_id: "job-1",
        approved: false,
        changes: [
          { change_id: "c1", approved: true },
          { change_id: "c2", approved: false },
        ],
      },
    });
    expect(requests[1]).toMatchObject({
      url: "https://api.superdocs.app/v1/chat/session-1/continue",
      type: "POST",
      postBody: { job_id: "job-1", continue: true },
    });
  });

  it("encodes malicious path values instead of changing request structure", async () => {
    const { client, requests } = recorder();
    const malicious = "../../x?<script>alert(1)</script>";
    await client.getJob(malicious);
    await client.continueChat(malicious, "job-1", false);

    expect(requests[0]?.url).toBe(
      "https://api.superdocs.app/v1/jobs/..%2F..%2Fx%3F%3Cscript%3Ealert(1)%3C%2Fscript%3E",
    );
    expect(requests[1]?.url).toBe(
      "https://api.superdocs.app/v1/chat/..%2F..%2Fx%3F%3Cscript%3Ealert(1)%3C%2Fscript%3E/continue",
    );
  });
});
