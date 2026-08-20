import { describe, expect, it, vi } from "vitest";
import { HttpSuperDocsClient } from "../src/superdocs/client.js";

describe("HttpSuperDocsClient", () => {
  it("sends the rendered document with an idempotency key", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: { "content-type": "application/pdf" }
      })
    );
    const client = new HttpSuperDocsClient({
      apiKey: "secret",
      baseUrl: "https://example.test/",
      fetchImpl
    });

    const result = await client.exportDocument({
      html: "<h1>Docs</h1>",
      title: "Docs",
      format: "pdf",
      idempotencyKey: "preview:abc"
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://example.test/v1/documents/export",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          authorization: "Bearer secret",
          "idempotency-key": "preview:abc"
        }),
        body: JSON.stringify({ title: "Docs", format: "pdf", html: "<h1>Docs</h1>" })
      })
    );
    expect(result.data).toEqual(new Uint8Array([1, 2, 3]));
  });

  it("surfaces export failures", async () => {
    const client = new HttpSuperDocsClient({
      apiKey: "secret",
      baseUrl: "https://example.test",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(new Response("bad", { status: 503 }))
    });

    await expect(client.exportDocument({
      html: "<p>Docs</p>",
      title: "Docs",
      format: "docx",
      idempotencyKey: "preview:abc"
    })).rejects.toThrow("status 503");
  });
});
