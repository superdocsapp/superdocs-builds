import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    // `npm run dev` talks to the FastAPI process; in production FastAPI
    // serves the built assets itself, so there is only ever one origin.
    // No route under /api exists yet (that starts in M3) — matches Task 1's
    // ui/vite.config.js, one line ahead of need rather than a new pattern.
    proxy: { '/api': 'http://localhost:8010' },
  },
})
