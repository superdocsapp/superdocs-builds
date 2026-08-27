import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5174,
    // The API holds the SuperDocs key, so the browser only ever talks to us.
    proxy: { "/api": { target: process.env.API_ORIGIN ?? "http://api:8000", changeOrigin: true } },
  },
});
