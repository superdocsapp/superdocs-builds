import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";
import { readAppCredentials } from "../src/github/app-auth.js";

function pem(): string {
  return "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n";
}

describe("GitHub App credential reading", () => {
  it("reports a missing app id without decoding anything", () => {
    const result = readAppCredentials(loadConfig({ NODE_ENV: "test" }));

    expect(result).toEqual({ ok: false, reason: "GITHUB_APP_ID is not set" });
  });

  it("reports a missing private key", () => {
    const result = readAppCredentials(
      loadConfig({ NODE_ENV: "test", GITHUB_APP_ID: "123" })
    );

    expect(result).toEqual({
      ok: false,
      reason: "GITHUB_PRIVATE_KEY_BASE64 is not set"
    });
  });

  it("rejects a value that is not a PEM key", () => {
    const result = readAppCredentials(
      loadConfig({
        NODE_ENV: "test",
        GITHUB_APP_ID: "123",
        GITHUB_PRIVATE_KEY_BASE64: Buffer.from("not-a-key", "utf8").toString(
          "base64"
        )
      })
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason).toContain("did not decode to a PEM private key");
  });

  it("accepts a base64-encoded PEM key", () => {
    const result = readAppCredentials(
      loadConfig({
        NODE_ENV: "test",
        GITHUB_APP_ID: "123",
        GITHUB_PRIVATE_KEY_BASE64: Buffer.from(pem(), "utf8").toString("base64")
      })
    );

    expect(result).toEqual({
      ok: true,
      credentials: { appId: "123", privateKey: pem() }
    });
  });
});
