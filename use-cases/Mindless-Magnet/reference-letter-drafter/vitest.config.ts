import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // Every test in this suite runs with no network and no key. If a test
    // needs one, it is testing the wrong thing.
    env: { NODE_ENV: "test" },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
      // `server-only` throws when imported outside a React Server Component.
      // The modules under test are server modules; this stub lets them load in
      // a plain Node test process without weakening the guard in the app.
      "server-only": path.resolve(__dirname, "tests/stubs/server-only.ts"),
    },
  },
});
