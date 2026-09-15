import { defineConfig } from '@playwright/test';

// Opt-in: start an isolated, token-protected sidecar with a current React build.
export default defineConfig({
  testDir: './tests/browser-live',
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: process.env.VORTEX_LIVE_URL || 'http://127.0.0.1:8765',
    headless: true,
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] }
      : {},
  },
});
