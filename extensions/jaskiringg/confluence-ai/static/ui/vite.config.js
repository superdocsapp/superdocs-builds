import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const forge = process.env.FORGE === "1";

export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: forge
    ? {}
    : {
        alias: {
          "@forge/bridge": path.resolve(__dirname, "src/forgeBridgeStub.js"),
        },
      },
  server: {
    port: 5178,
    proxy: { "/api": "http://127.0.0.1:8787" },
  },
  build: {
    outDir: "build",
    emptyOutDir: true,
  },
});
