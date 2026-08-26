import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { cliRunnerPlugin } from './vite-plugin-cli-runner.ts'

// https://vite.dev/config/
export default defineConfig({
  // cliRunnerPlugin only registers via configureServer (dev-only) — it is
  // not present in `vite build` output or `vite preview`.
  plugins: [react(), cliRunnerPlugin()],
})
