/**
 * End-to-end smoke tests (spec 14: "Playwright smoke flow passes").
 *
 * They drive the real stack: the Vite dev server (proxying /api to the API) with a seeded
 * database. Start both first (`make dev-api`, `make worker`, `npm run dev`, `make seed-local`).
 *
 * Browsers: every Chromium-family browser already installed on this machine is used
 * as-is (Chrome, Edge, Brave), so nothing has to be downloaded. Set PW_ALL_BROWSERS=1
 * after `npx playwright install firefox webkit` to add Firefox and Safari's engine.
 */
import { existsSync } from 'node:fs'

import { defineConfig, devices, type Project } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'

function firstExisting(paths: string[]): string | undefined {
  return paths.find((p) => existsSync(p))
}

const brave = firstExisting([
  process.env.BRAVE_PATH ?? '',
  'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
  '/usr/bin/brave-browser',
])
const chrome = firstExisting([
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
])
const edge = firstExisting([
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/usr/bin/microsoft-edge',
])

const projects: Project[] = []
if (chrome)
  projects.push({ name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } })
if (edge) projects.push({ name: 'edge', use: { ...devices['Desktop Edge'], channel: 'msedge' } })
if (brave)
  projects.push({
    name: 'brave',
    use: { ...devices['Desktop Chrome'], launchOptions: { executablePath: brave } },
  })
if (chrome ?? edge)
  projects.push({
    name: 'mobile',
    use: { ...devices['Pixel 7'], ...(chrome ? { channel: 'chrome' } : { channel: 'msedge' }) },
  })
if (process.env.PW_ALL_BROWSERS === '1') {
  projects.push({ name: 'firefox', use: { ...devices['Desktop Firefox'] } })
  projects.push({ name: 'webkit', use: { ...devices['Desktop Safari'] } })
}

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.e2e\.ts$/,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // one shared database: keep the flows in order
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Deterministic screenshots (spec 12.4).
    contextOptions: { reducedMotion: 'reduce' },
  },
  projects,
})
