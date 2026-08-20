import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    // `npm run dev` talks to the FastAPI process; in production FastAPI
    // serves the built assets itself, so there is only ever one origin.
    proxy: { '/api': 'http://localhost:8020' },
  },
})
