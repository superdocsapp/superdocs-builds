import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  PolicySetSuperDocsSafetyError,
  SuperDocsClient,
  SuperDocsInvalidResponse,
  buildStartChatPayload,
  exportPolicyDocument,
  policyDocumentExportFilename,
} from "@/superdocs";
import { buildPolicyExportResponse } from "@/app/api/policyset/superdocs/export/route";
import type { PolicyDocumentType } from "@/domain";
import { DOCX_MIME, PDF_MIME } from "@/superdocs/types";

describe("SuperDocs chat request", () => {
  it("omits document_id when the caller does not pin a document", async () => {
    expect(buildStartChatPayload({ sessionId: "sess-1", message: "Edit both policies" })).not.toHaveProperty(
      "document_id",
    );

    let body: unknown;
    const client = new SuperDocsClient({
      apiKey: "test-key",
      fetch: async (_input, init) => {
        body = JSON.parse(String(init?.body));
        return jsonResponse({
          job_id: "job-1",
          session_id: "sess-1",
          status: "pending",
        });
      },
    });

    await client.startChat({ sessionId: "sess-1", message: "Edit both policies" });
    expect(body).toEqual({
      message: "Edit both policies",
      session_id: "sess-1",
      approval_mode: "ask_every_time",
      response_mode: "full",
    });
    expect(body).not.toHaveProperty("document_id");
  });

  it("includes document_id only when an explicit pin is provided", () => {
    expect(
      buildStartChatPayload({
        sessionId: "sess-1",
        message: "Edit this document",
        documentId: "doc_primary",
      }),
    ).toMatchObject({ document_id: "doc_primary" });
  });
});

describe("SuperDocs export helper", () => {
  it("focuses and verifies identity before exporting", async () => {
    const calls: string[] = [];
    const client = new SuperDocsClient({
      apiKey: "test-key",
      fetch: async (input, init) => {
        const url = String(input);
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url.includes("/focus")) {
          return jsonResponse({ focused_document_id: "doc_primary" });
        }
        if (url.includes("/documents/export")) {
          return binaryResponse(DOCX_MIME, new Uint8Array([0x50, 0x4b, 0x03, 0x04]));
        }
        throw new Error(`unexpected request ${url}`);
      },
    });

    const artifact = await client.exportFocusedDocument(
      { sessionId: "sess-1", documentId: "doc_primary" },
      { format: "docx", filename: "terms-of-service.docx" },
    );

    expect(calls).toHaveLength(2);
    expect(calls[0]).toContain("/sessions/sess-1/documents/doc_primary/focus");
    expect(calls[1]).toContain("/documents/export");
    expect(artifact.contentType).toBe(DOCX_MIME);
  });

  it("does not export when focus returns a different document", async () => {
    const calls: string[] = [];
    const client = new SuperDocsClient({
      apiKey: "test-key",
      fetch: async (input, init) => {
        const url = String(input);
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url.includes("/focus")) {
          return jsonResponse({ focused_document_id: "doc_other" });
        }
        return binaryResponse(PDF_MIME, new Uint8Array([0x25, 0x50, 0x44, 0x46]));
      },
    });

    await expect(
      client.exportFocusedDocument(
        { sessionId: "sess-1", documentId: "doc_primary" },
        { format: "pdf", filename: "terms-of-service.pdf" },
      ),
    ).rejects.toBeInstanceOf(SuperDocsInvalidResponse);

    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain("/focus");
    expect(calls.some((call) => call.includes("/export"))).toBe(false);
  });

  it("does not export when focus is explicitly unconfirmed", async () => {
    const calls: string[] = [];
    const client = new SuperDocsClient({
      apiKey: "test-key",
      fetch: async (input) => {
        const url = String(input);
        calls.push(url);
        if (url.includes("/focus")) {
          return jsonResponse({
            focused_document_id: "doc_primary",
            focused: false,
          });
        }
        return binaryResponse(PDF_MIME, new Uint8Array([0x25, 0x50, 0x44, 0x46]));
      },
    });

    await expect(
      client.exportFocusedDocument(
        { sessionId: "sess-1", documentId: "doc_primary" },
        { format: "pdf", filename: "terms-of-service.pdf" },
      ),
    ).rejects.toBeInstanceOf(SuperDocsInvalidResponse);
    expect(calls).toHaveLength(1);
  });
});

describe("PolicySet export boundary", () => {
  const documentIds: Record<PolicyDocumentType, string> = {
    terms: "doc_terms",
    privacy: "doc_privacy",
    warranty: "doc_warranty",
    returns: "doc_returns",
  };

  it("refuses a requested document outside the current PolicySet mapping", async () => {
    const listSessionDocuments = vi.fn();
    const exportFocusedDocument = vi.fn();

    await expect(
      exportPolicyDocument(
        {
          sessionId: "sess-1",
          documentType: "terms",
          documentId: "doc_attacker",
          documentIds,
          format: "docx",
          companyName: "Northstar Goods LLC",
        },
        { listSessionDocuments, exportFocusedDocument },
      ),
    ).rejects.toBeInstanceOf(PolicySetSuperDocsSafetyError);

    expect(listSessionDocuments).not.toHaveBeenCalled();
    expect(exportFocusedDocument).not.toHaveBeenCalled();
  });

  it("refuses export when the current map differs from the authoritative session roster", async () => {
    const exportFocusedDocument = vi.fn();

    await expect(
      exportPolicyDocument(
        {
          sessionId: "sess-1",
          documentType: "terms",
          documentId: documentIds.terms,
          documentIds,
          format: "docx",
          companyName: "Northstar Goods LLC",
        },
        {
          listSessionDocuments: async () =>
            sessionDocuments({ ...documentIds, terms: "doc_other" }),
          exportFocusedDocument,
        },
      ),
    ).rejects.toBeInstanceOf(PolicySetSuperDocsSafetyError);

    expect(exportFocusedDocument).not.toHaveBeenCalled();
  });

  it.each([
    ["docx", DOCX_MIME],
    ["pdf", PDF_MIME],
  ] as const)(
    "returns %s bytes with the correct MIME type and sanitized filename",
    (format, contentType) => {
      const filename = policyDocumentExportFilename(
        "Northstar Goods LLC",
        "terms",
        format,
      );
      const response = buildPolicyExportResponse({
        filename,
        artifact: {
          format,
          bytes: new Uint8Array([1, 2, 3]),
          contentType,
          sha256: "hash",
          sizeBytes: 3,
          contentDisposition: null,
          warnings: [],
        },
      });

      expect(response.headers.get("Content-Type")).toBe(contentType);
      expect(response.headers.get("Content-Disposition")).toBe(
        `attachment; filename="${filename}"`,
      );
      expect(filename).toBe(`northstar-goods-terms-of-service.${format}`);
      expect(response.headers.get("Cache-Control")).toBe("no-store");
    },
  );

  it("keeps the SuperDocs API key out of the client export path", async () => {
    const clientSources = await Promise.all(
      [
        "src/app/policyset/superdocs-api.ts",
        "src/app/policyset/WorkspaceView.tsx",
        "src/app/policyset/ExportControl.tsx",
      ].map((path) => readFile(resolve(process.cwd(), path), "utf8")),
    );

    expect(clientSources.join("\n")).not.toContain("SUPERDOCS_API_KEY");
  });
});

function sessionDocuments(documentIds: Record<PolicyDocumentType, string>) {
  return Object.values(documentIds).map((documentId) => ({
    identity: { sessionId: "sess-1", documentId },
    title: null,
    focused: false,
    versionId: null,
    chunksCount: null,
    html: null,
  }));
}

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function binaryResponse(contentType: string, body: Uint8Array): Response {
  return new Response(Buffer.from(body), {
    status: 200,
    headers: { "Content-Type": contentType },
  });
}
