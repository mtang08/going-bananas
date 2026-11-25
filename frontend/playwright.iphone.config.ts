import { defineConfig, devices } from '@playwright/test'
import base from './playwright.config'

export default defineConfig({
  ...base,
  testMatch: 'iphone-checkin.spec.ts',
  use: { baseURL: base.use?.baseURL },
  projects: [
    { name: 'Mobile Chrome', use: { ...devices['Pixel 7'], browserName: 'chromium', channel: 'chrome' } },
    { name: 'Mobile WebKit', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
})
