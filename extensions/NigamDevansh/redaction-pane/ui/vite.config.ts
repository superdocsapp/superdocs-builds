import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The pane is served by the Python service from `ui/dist`, over the same HTTPS
// origin Word loads `SourceLocation` from. One origin, one certificate, one
// process to start — see service/app.py.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    // Word's `SourceLocation` points at this file by name, so it must not be
    // renamed to index.html by convention.
    rollupOptions: { input: "taskpane.html" },
    target: "es2022",
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
