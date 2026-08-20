import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

describe("loadConfig", () => {
  it("loads defaults for local development", () => {
    const config = loadConfig({});

    expect(config.NODE_ENV).toBe("development");
    expect(config.PORT).toBe(3000);
    expect(config.SUPERDOCS_API_BASE_URL).toBe("https://api.superdocs.app");
  });

  it("coerces PORT from environment text", () => {
    const config = loadConfig({ PORT: "4545" });

    expect(config.PORT).toBe(4545);
  });
});

