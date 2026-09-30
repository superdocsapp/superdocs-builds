import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Python service serves `ui/dist` and answers the API on the same origin,
// so there is no CORS, no second port, and one thing to start.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    target: "es2022",
    // `make dev` runs `npm run watch` inside a container with the host's `ui/`
    // bind-mounted. Docker Desktop on macOS does not deliver filesystem events
    // into that mount, so chokidar's native watcher sees nothing: an edit never
    // rebuilds, no error is printed, and reloading serves the previous bundle —
    // which reads exactly like the change not working. Polling is the only
    // thing that crosses the mount.
    //
    // Gated on the env var rather than on `mode`, so this stays off for the
    // `npm run build` in the Dockerfile — any `build.watch` value would make
    // that build hang instead of exiting — while the watcher keeps producing a
    // production bundle rather than a dev one.
    watch: process.env.VITE_WATCH_POLL ? { chokidar: { usePolling: true, interval: 300 } } : null,
  },
  // `vite dev` alone would have no backend; proxy the API to the container.
  server: { proxy: { "/upload": "http://localhost:8080", "/split": "http://localhost:8080",
                     "/export": "http://localhost:8080", "/health": "http://localhost:8080",
                     "/log": "http://localhost:8080" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
