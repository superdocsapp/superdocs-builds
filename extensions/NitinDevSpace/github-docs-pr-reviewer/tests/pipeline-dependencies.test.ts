import { describe, expect, it } from "vitest";
import { buildWebhookDependencies } from "../src/pipeline/dependencies.js";
import { loadConfig } from "../src/config.js";

describe("webhook dependency composition", () => {
  it("starts without GitHub credentials and names the missing piece", () => {
    const result = buildWebhookDependencies(
      loadConfig({ NODE_ENV: "test" })
    );

    expect(result.inactiveReason).toBe("GITHUB_APP_ID is not set");
    expect(result.dependencies.executeCommand).toBeUndefined();
    expect(result.dependencies.reviewPullRequest).toBeUndefined();
    expect(result.dependencies.generateReleaseDocument).toBeUndefined();
  });
});
