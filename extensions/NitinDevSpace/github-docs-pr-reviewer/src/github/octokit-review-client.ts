import type {
  CreatePullRequestReviewInput,
  GitHubIssueComment,
  GitHubReviewClient
} from "./review-publisher.js";

type OctokitLike = {
  rest: {
    issues: {
      listComments(input: {
        owner: string;
        repo: string;
        issue_number: number;
        per_page?: number;
      }): Promise<{ data: GitHubIssueComment[] }>;
      createComment(input: {
        owner: string;
        repo: string;
        issue_number: number;
        body: string;
      }): Promise<{ data: GitHubIssueComment }>;
      updateComment(input: {
        owner: string;
        repo: string;
        comment_id: number;
        body: string;
      }): Promise<{ data: GitHubIssueComment }>;
    };
    pulls: {
      createReview(input: CreatePullRequestReviewInput): Promise<{
        data: {
          id: number;
        };
      }>;
    };
  };
};

export function createOctokitReviewClient(octokit: OctokitLike): GitHubReviewClient {
  return {
    async listIssueComments(input) {
      const response = await octokit.rest.issues.listComments({
        ...input,
        per_page: 100
      });
      return response.data;
    },

    async createIssueComment(input) {
      const response = await octokit.rest.issues.createComment(input);
      return response.data;
    },

    async updateIssueComment(input) {
      const response = await octokit.rest.issues.updateComment(input);
      return response.data;
    },

    async createPullRequestReview(input) {
      const response = await octokit.rest.pulls.createReview(input);
      return {
        id: response.data.id
      };
    }
  };
}

