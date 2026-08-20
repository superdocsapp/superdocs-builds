import { describe, expect, it } from "vitest";
import {
  createGitHubSignature,
  verifyGitHubSignature
} from "../src/github/signature.js";

describe("GitHub webhook signature verification", () => {
  it("accepts a valid sha256 signature", () => {
    const payload = JSON.stringify({ action: "opened" });
    const signature = createGitHubSignature(payload, "secret");

    expect(
      verifyGitHubSignature({
        payload,
        signature,
        secret: "secret"
      })
    ).toBe(true);
  });

  it("rejects invalid signatures", () => {
    const payload = JSON.stringify({ action: "opened" });

    expect(
      verifyGitHubSignature({
        payload,
        signature: "sha256=bad",
        secret: "secret"
      })
    ).toBe(false);
  });
});

