import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:4175", screenshot: "only-on-failure" },
  webServer: [
    {
      command: "npm run bff:offline",
      url: "http://127.0.0.1:4174/api/superdocs/config",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4175",
      url: "http://127.0.0.1:4175",
      reuseExistingServer: false,
    },
  ],
});
