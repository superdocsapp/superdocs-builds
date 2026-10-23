import { beforeEach, describe, expect, it, vi } from "vitest";

const mockPost = vi.fn();
const mockGet = vi.fn();

vi.mock("axios", () => {
  return {
    default: {
      create: () => ({
        post: mockPost,
        get: mockGet,
        interceptors: {
          response: { use: vi.fn() },
          request: { use: vi.fn() },
        },
      }),
    },
  };
});

describe("api client", () => {
  beforeEach(() => {
    mockPost.mockReset();
    mockGet.mockReset();
  });

  it("createBrief posts session id", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        brief_id: "b1",
        session_id: "s1",
        status: "pending",
      },
    });
    const { createBrief } = await import("@/services/api");
    const result = await createBrief("s1");
    expect(mockPost).toHaveBeenCalledWith("/briefs", { session_id: "s1" });
    expect(result.brief_id).toBe("b1");
  });
});
