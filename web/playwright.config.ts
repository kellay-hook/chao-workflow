import { defineConfig, devices } from '@playwright/test'

const isWindows = process.platform === 'win32'
const python = isWindows ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: process.env.FLOWMIND_WEB_URL || 'http://localhost:5180',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --reload --reload-dir backend --port 8020`,
      cwd: '..',
      url: 'http://localhost:8020/healthz',
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5180',
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})