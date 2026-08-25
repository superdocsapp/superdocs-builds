import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const DEV_PORT = Number(process.env.VITE_DEV_PORT ?? 5180);

export default defineConfig({
  plugins: [react()],
  server: {
    // Single source of truth for the dev port. This used to say 5173 while the npm
    // script forced 5180 and the backend CORS allowlist only trusted 5173.
    host: "0.0.0.0",
    port: DEV_PORT,
    strictPort: true
  },
  preview: {
    host: "0.0.0.0",
    port: DEV_PORT
  }
});
