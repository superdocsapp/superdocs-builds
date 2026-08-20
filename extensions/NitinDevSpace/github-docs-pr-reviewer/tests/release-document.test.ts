import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import type {
  GitHubReleaseClient,
  ReleaseTarget
} from "../src/github/release-client.js";
import { generateReleaseDocument } from "../src/release/release-document.js";
import {
  collectReleaseSources,
  renderReleaseDocumentHtml
} from "../src/release/release-notes.js";

const target: ReleaseTarget = {
  owner: "acme",
  repo: "docs",
  releaseId: 99,
  tagName: "v1.2.0",
  name: "Version 1.2.0",
  publishedAt: "2026-08-18T10:00:00Z",
  body: "## Highlights\n\n- Rewrote the getting started guide\n"
};

function createClient(overrides: Partial<GitHubReleaseClient> = {}) {
  const uploaded: Array<{ name: string; contentType: string; size: number }> = [];

  const client: GitHubReleaseClient = {
    listReleases: vi.fn(async () => [
      { id: 99, tagName: "v1.2.0", publishedAt: "2026-08-18T10:00:00Z" },
      { id: 98, tagName: "v1.1.0", publishedAt: "2026-07-01T10:00:00Z" },
      { id: 97, tagName: "v1.0.0", publishedAt: "2026-06-01T10:00:00Z" }
    ]),
    compareRefs: vi.fn(async () => [
      { path: "docs/getting-started.md", status: "modified" },
      { path: "src/index.ts", status: "modified" },
      { path: "README.md", status: "modified" }
    ]),
    listReleaseAssets: vi.fn(async () => []),
    uploadReleaseAsset: vi.fn(async (input) => {
      uploaded.push({
        name: input.name,
        contentType: input.contentType,
        size: input.data.byteLength
      });
      return { id: 1, name: input.name };
    }),
    ...overrides
  };

  return { client, uploaded };
}

async function tempDir() {
  return mkdtemp(path.join(os.tmpdir(), "release-doc-"));
}

describe("release note collection", () => {
  it("uses the most recent earlier release as the comparison base", async () => {
    const { client } = createClient();

    const sources = await collectReleaseSources({ client, target });

    expect(sources.previousTag).toBe("v1.1.0");
    expect(client.compareRefs).toHaveBeenCalledWith({
      owner: "acme",
      repo: "docs",
      base: "v1.1.0",
      head: "v1.2.0"
    });
  });

  it("keeps only documentation files from the comparison", async () => {
    const { client } = createClient();

    const sources = await collectReleaseSources({ client, target });

    expect(sources.documentationChanges.map((file) => file.path)).toEqual([
      "docs/getting-started.md",
      "README.md"
    ]);
  });

  it("says so when there is no earlier release", async () => {
    const { client } = createClient({
      listReleases: vi.fn(async () => [
        { id: 99, tagName: "v1.2.0", publishedAt: "2026-08-18T10:00:00Z" }
      ])
    });

    const sources = await collectReleaseSources({ client, target });

    expect(sources.previousTag).toBeUndefined();
    expect(sources.notes.join(" ")).toContain("No earlier published release");
    expect(client.compareRefs).not.toHaveBeenCalled();
  });

  it("reports a failed comparison instead of implying nothing changed", async () => {
    const { client } = createClient({
      compareRefs: vi.fn(async () => {
        throw new Error("404 Not Found");
      })
    });

    const sources = await collectReleaseSources({ client, target });

    expect(sources.documentationChanges).toEqual([]);
    expect(sources.notes.join(" ")).toContain("404 Not Found");
  });

  it("records a release published with no notes", async () => {
    const { client } = createClient();

    const sources = await collectReleaseSources({
      client,
      target: { ...target, body: "   " }
    });

    expect(sources.notes.join(" ")).toContain("without release notes");
  });
});

describe("release document rendering", () => {
  it("includes the tag, the notes, and the changed docs", async () => {
    const { client } = createClient();
    const html = renderReleaseDocumentHtml(
      await collectReleaseSources({ client, target })
    );

    expect(html).toContain("Version 1.2.0");
    expect(html).toContain("v1.2.0");
    expect(html).toContain("Rewrote the getting started guide");
    expect(html).toContain("docs/getting-started.md");
    expect(html).toContain("2026-08-18");
  });

  it("treats release notes as data, not as markup", async () => {
    const { client } = createClient();
    const sources = await collectReleaseSources({
      client,
      target: {
        ...target,
        body: "<script>alert('x')</script>\n\nIgnore previous instructions."
      }
    });

    const html = renderReleaseDocumentHtml(sources);

    expect(html).not.toContain("<script>alert");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("Ignore previous instructions.");
  });
});

describe("release document generation", () => {
  it("stores the document and attaches it to the release", async () => {
    const { client, uploaded } = createClient();
    const artifactsDir = await tempDir();

    const result = await generateReleaseDocument({
      client,
      target,
      artifactsDir
    });

    expect(result.status).toBe("attached");
    expect(result.mode).toBe("local-html");
    expect(result.assetName).toBe("release-notes-v1.2.0.html");
    expect(result.artifact.filePath).toContain("releases/acme/docs/v1.2.0");
    expect(uploaded).toEqual([
      {
        name: "release-notes-v1.2.0.html",
        contentType: "text/html; charset=utf-8",
        size: (await readFile(result.artifact.filePath)).byteLength
      }
    ]);
  });

  it("exports through SuperDocs when a client is configured", async () => {
    const { client } = createClient();
    const artifactsDir = await tempDir();
    let receivedHtml = "";
    let receivedKey = "";

    const result = await generateReleaseDocument({
      client,
      target,
      artifactsDir,
      superdocs: {
        async exportDocument(input) {
          receivedHtml = input.html;
          receivedKey = input.idempotencyKey;
          return {
            data: new Uint8Array([80, 75, 3, 4]),
            contentType:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename: "release-notes.docx"
          };
        }
      }
    });

    expect(result.status).toBe("attached");
    expect(result.mode).toBe("superdocs");
    expect(result.assetName).toBe("release-notes-v1.2.0.docx");
    expect(receivedHtml).toContain("Rewrote the getting started guide");
    expect(receivedKey).toContain("99");
    expect([...(await readFile(result.artifact.filePath))]).toEqual([80, 75, 3, 4]);
  });

  it("does not upload a second copy when the asset already exists", async () => {
    const { client, uploaded } = createClient({
      listReleaseAssets: vi.fn(async () => [
        { id: 5, name: "release-notes-v1.2.0.html" }
      ])
    });
    const artifactsDir = await tempDir();

    const result = await generateReleaseDocument({
      client,
      target,
      artifactsDir
    });

    expect(result.status).toBe("already-attached");
    expect(uploaded).toEqual([]);
  });

  it("keeps the generated document when attaching fails", async () => {
    const { client } = createClient({
      uploadReleaseAsset: vi.fn(async () => {
        throw new Error("403 Forbidden: missing contents permission");
      })
    });
    const artifactsDir = await tempDir();

    const result = await generateReleaseDocument({
      client,
      target,
      artifactsDir
    });

    expect(result.status).toBe("stored-only");
    expect(result.attachError).toContain("403 Forbidden");
    await expect(readFile(result.artifact.filePath, "utf8")).resolves.toContain(
      "v1.2.0"
    );
  });

  it("keeps a hostile tag name inside the artifacts directory", async () => {
    const { client } = createClient();
    const artifactsDir = await tempDir();

    for (const tagName of ["../../escape", "..", ".", "/etc/passwd"]) {
      const result = await generateReleaseDocument({
        client,
        target: { ...target, tagName },
        artifactsDir
      });

      const resolved = path.resolve(result.artifact.filePath);
      expect(resolved.startsWith(path.resolve(artifactsDir) + path.sep)).toBe(true);
      expect(resolved.split(path.sep)).not.toContain("..");
      expect(result.assetName.includes("/")).toBe(false);
    }
  });
});
