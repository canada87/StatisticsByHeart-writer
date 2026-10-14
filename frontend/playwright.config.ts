import { defineConfig } from '@playwright/test'

/**
 * Smoke + screenshot tests against the DEV stack with SYNTHETIC data:
 *   docker compose -f docker/compose.dev.yml up -d --build
 *   cd frontend && npx playwright install chromium && npm run test:e2e
 * Never point this at a server holding real health data (screenshots are committed).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,
  reporter: [['list']],
  outputDir: './test-results',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8000',
    locale: 'it-IT',
    timezoneId: 'Europe/Rome',
    colorScheme: 'dark',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
