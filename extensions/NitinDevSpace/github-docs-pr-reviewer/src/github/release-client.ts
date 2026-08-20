export type ReleaseTarget = {
  owner: string;
  repo: string;
  releaseId: number;
  tagName: string;
  name?: string;
  publishedAt?: string;
  body?: string;
  htmlUrl?: string;
};

export type ReleaseSummary = {
  id: number;
  tagName: string;
  publishedAt?: string;
  draft?: boolean;
  prerelease?: boolean;
};

export type ReleaseAsset = {
  id: number;
  name: string;
};

export type ComparedFile = {
  path: string;
  status: string;
};

export type GitHubReleaseClient = {
  listReleases(input: {
    owner: string;
    repo: string;
  }): Promise<ReleaseSummary[]>;
  compareRefs(input: {
    owner: string;
    repo: string;
    base: string;
    head: string;
  }): Promise<ComparedFile[]>;
  listReleaseAssets(input: {
    owner: string;
    repo: string;
    release_id: number;
  }): Promise<ReleaseAsset[]>;
  uploadReleaseAsset(input: {
    owner: string;
    repo: string;
    release_id: number;
    name: string;
    contentType: string;
    data: Uint8Array;
  }): Promise<ReleaseAsset>;
};
