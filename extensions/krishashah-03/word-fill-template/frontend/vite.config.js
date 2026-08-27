import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Word will only load a taskpane over HTTPS, even in development. Run
// `npx office-addin-dev-certs install` once to generate and trust a
// localhost certificate; this reads it directly so no extra dependency is
// needed. Falls back to plain HTTP (fine for browser-only testing) if the
// certificate hasn't been installed yet.
function loadDevCertificate() {
  const certDir = join(homedir(), '.office-addin-dev-certs')
  const certPath = join(certDir, 'localhost.crt')
  const keyPath = join(certDir, 'localhost.key')

  if (!existsSync(certPath) || !existsSync(keyPath)) {
    return undefined
  }

  return {
    cert: readFileSync(certPath),
    key: readFileSync(keyPath),
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    https: loadDevCertificate(),
  },
})
