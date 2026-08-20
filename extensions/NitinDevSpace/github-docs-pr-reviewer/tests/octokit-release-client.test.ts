import { describe, expect, it, vi } from "vitest";
import { createOctokitReleaseClient } from "../src/github/octokit-release-client.js";

type CompareResponse = {
  data: { files?: Array<{ filename: string; status: string }> };
};

function createOctokit() {
  return {
    rest: {
      repos: {
        listReleases: vi.fn(async () => ({
          data: [
            {
              id: 99,
              tag_name: "v1.2.0",
              published_at: "2026-08-18T10:00:00Z",
              draft: false,
              prerelease: false
            },
            {
              id: 98,
              tag_name: "v1.1.0",
              published_at: null,
              draft: true,
              prerelease: false
            }
          ]
        })),
        compareCommitsWithBasehead: vi.fn(
          async (): Promise<CompareResponse> => ({
            data: {
              files: [{ filename: "docs/guide.md", status: "modified" }]
            }
          })
        ),
        listReleaseAssets: vi.fn(async () => ({
          data: [{ id: 5, name: "release-notes-v1.1.0.docx" }]
        })),
        uploadReleaseAsset: vi.fn(async (input) => ({
          data: { id: 6, name: input.name }
        }))
      }
    }
  };
}

describe("Octokit release client adapter", () => {
  it("normalises releases and turns a null published date into undefined", async () => {
    const octokit = createOctokit();
    const client = createOctokitReleaseClient(octokit);

    await expect(
      client.listReleases({ owner: "acme", repo: "docs" })
    ).resolves.toEqual([
      {
        id: 99,
        tagName: "v1.2.0",
        publishedAt: "2026-08-18T10:00:00Z",
        draft: false,
        prerelease: false
      },
      {
        id: 98,
        tagName: "v1.1.0",
        publishedAt: undefined,
        draft: true,
        prerelease: false
      }
    ]);
  });

  it("compares refs using the basehead form", async () => {
    const octokit = createOctokit();
    const client = createOctokitReleaseClient(octokit);

    await expect(
      client.compareRefs({
        owner: "acme",
        repo: "docs",
        base: "v1.1.0",
        head: "v1.2.0"
      })
    ).resolves.toEqual([{ path: "docs/guide.md", status: "modified" }]);

    expect(octokit.rest.repos.compareCommitsWithBasehead).toHaveBeenCalledWith({
      owner: "acme",
      repo: "docs",
      basehead: "v1.1.0...v1.2.0"
    });
  });

  it("treats a comparison with no file list as no files", async () => {
    const octokit = createOctokit();
    octokit.rest.repos.compareCommitsWithBasehead = vi.fn(
      async (): Promise<CompareResponse> => ({ data: {} })
    );
    const client = createOctokitReleaseClient(octokit);

    await expect(
      client.compareRefs({
        owner: "acme",
        repo: "docs",
        base: "v1.1.0",
        head: "v1.2.0"
      })
    ).resolves.toEqual([]);
  });

  it("uploads an asset with its content type and length", async () => {
    const octokit = createOctokit();
    const client = createOctokitReleaseClient(octokit);
    const data = new Uint8Array([80, 75, 3, 4]);

    await expect(
      client.uploadReleaseAsset({
        owner: "acme",
        repo: "docs",
        release_id: 99,
        name: "release-notes-v1.2.0.docx",
        contentType: "application/vnd.test",
        data
      })
    ).resolves.toEqual({ id: 6, name: "release-notes-v1.2.0.docx" });

    const call = octokit.rest.repos.uploadReleaseAsset.mock.calls[0][0];
    expect(call.headers).toEqual({
      "content-type": "application/vnd.test",
      "content-length": 4
    });
    expect([...call.data]).toEqual([80, 75, 3, 4]);
  });
});
