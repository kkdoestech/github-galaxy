import { defineConfig } from '@playwright/test'

const ci = !!process.env.CI

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: ci ? 1 : 0,
  use: {
    baseURL: 'http://localhost:4173/',
    // locally, use the installed Chrome instead of downloading a browser
    channel: ci ? undefined : 'chrome',
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
    viewport: { width: 1360, height: 860 },
  },
  webServer: {
    command: 'npm run build:demo && npx vite preview --mode demo --port 4173 --strictPort',
    url: 'http://localhost:4173/',
    reuseExistingServer: !ci,
    timeout: 120_000,
  },
})
