import base from "./playwright.config";
import { defineConfig } from "@playwright/test";

if (
  process.env.RUN_SUPERDOCS_LIVE_TESTS !== "1" ||
  process.env.SUPERDOCS_MODE !== "real"
)
  throw new Error(
    "Live UI test requires RUN_SUPERDOCS_LIVE_TESTS=1 and SUPERDOCS_MODE=real",
  );

export default defineConfig({
  ...base,
  workers: 1,
  retries: 0,
  use: {
    ...base.use,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "npm run bff",
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
