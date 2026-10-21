import {defineConfig} from '@playwright/test';

const port = Number(process.env.PLAYWRIGHT_PORT || 8877);

export default defineConfig({
  testDir: 'e2e',
  timeout: 30000,
  use: {baseURL: `http://127.0.0.1:${port}`, headless: true},
  webServer: {
    command: `.venv/bin/python -m uvicorn linecard.api:app --host 127.0.0.1 --port ${port}`,
    cwd: '..',
    port,
    reuseExistingServer: false,
  },
});
