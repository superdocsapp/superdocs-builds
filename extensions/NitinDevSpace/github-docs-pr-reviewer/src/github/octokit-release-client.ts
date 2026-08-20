import type {
  ComparedFile,
  GitHubReleaseClient,
  ReleaseAsset,
  ReleaseSummary
} from "./release-client.js";

type OctokitReleaseLike = {
  rest: {
    repos: {
      listReleases(input: {
        owner: string;
        repo: string;
        per_page?: number;
      }): Promise<{
        data: Array<{
          id: number;
          tag_name: string;
          published_at?: string | null;
          draft?: boolean;
          prerelease?: boolean;
        }>;
      }>;
      compareCommitsWithBasehead(input: {
        owner: string;
        repo: string;
        basehead: string;
      }): Promise<{
        data: { files?: Array<{ filename: string; status: string }> };
      }>;
      listReleaseAssets(input: {
        owner: string;
        repo: string;
        release_id: number;
        per_page?: number;
      }): Promise<{ data: Array<{ id: number; name: string }> }>;
      uploadReleaseAsset(input: {
        owner: string;
        repo: string;
        release_id: number;
        name: string;
        data: unknown;
        headers: Record<string, string | number>;
      }): Promise<{ data: { id: number; name: string } }>;
    };
  };
};

export function createOctokitReleaseClient(
  octokit: OctokitReleaseLike
): GitHubReleaseClient {
  return {
    async listReleases(input): Promise<ReleaseSummary[]> {
      const { data } = await octokit.rest.repos.listReleases({
        ...input,
        per_page: 100
      });

      return data.map((release) => ({
        id: release.id,
        tagName: release.tag_name,
        publishedAt: release.published_at ?? undefined,
        draft: release.draft,
        prerelease: release.prerelease
      }));
    },

    async compareRefs({ owner, repo, base, head }): Promise<ComparedFile[]> {
      const { data } = await octokit.rest.repos.compareCommitsWithBasehead({
        owner,
        repo,
        basehead: `${base}...${head}`
      });

      return (data.files ?? []).map((file) => ({
        path: file.filename,
        status: file.status
      }));
    },

    async listReleaseAssets(input): Promise<ReleaseAsset[]> {
      const { data } = await octokit.rest.repos.listReleaseAssets({
        ...input,
        per_page: 100
      });

      return data.map((asset) => ({ id: asset.id, name: asset.name }));
    },

    async uploadReleaseAsset(input): Promise<ReleaseAsset> {
      const { data } = await octokit.rest.repos.uploadReleaseAsset({
        owner: input.owner,
        repo: input.repo,
        release_id: input.release_id,
        name: input.name,
        data: Buffer.from(input.data),
        headers: {
          "content-type": input.contentType,
          "content-length": input.data.byteLength
        }
      });

      return { id: data.id, name: data.name };
    }
  };
}
