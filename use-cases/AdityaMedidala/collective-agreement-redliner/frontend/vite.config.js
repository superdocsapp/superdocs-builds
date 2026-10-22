import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/negotiations": "http://localhost:8001",
      "/rounds": "http://localhost:8001",
    },
  },
});
