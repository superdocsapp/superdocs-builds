import { describe, expect, it } from "vitest";

const apiKey = process.env.SUPERDOCS_API_KEY;
const live = apiKey ? describe : describe.skip;

live("SuperDocs live smoke test", () => {
  it("authenticates the configured account without spending an operation", async () => {
    const response = await fetch("https://api.superdocs.app/v1/agents/whoami", {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    expect(response.ok).toBe(true);
  });
});
