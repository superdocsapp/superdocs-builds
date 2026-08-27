import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

/** One file into the directory the FastAPI app already reads. No install, no
 *  build step, no Node on the machine that serves it. */
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: { outDir: "../backend/static", emptyOutDir: true, target: "es2020", cssMinify: true },
  // `npm run dev` serves the page on 5173 and the engine answers on 8000, so
  // without this the page's only conversation with the server 404s and the
  // dev server is useful for nothing but looking at the idle screen.
  // PORT=8077 python3 -m docrepair.web -> set SALVAGE_API to match.
  server: {
    proxy: { "/api": process.env.SALVAGE_API ?? "http://127.0.0.1:8000" },
  },
});
