import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // Dev-only proxy to the FastAPI backend (see src/localizer/api/), so
    // the browser sees same-origin requests and the backend needs no CORS
    // config. Target defaults to localhost for `npm run dev` run directly;
    // docker-compose overrides it to the "api" service name via
    // VITE_API_PROXY_TARGET, since 127.0.0.1 inside the ui container would
    // point at the ui container itself, not the api container.
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
