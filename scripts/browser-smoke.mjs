import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', () => errors.push('pageerror'))
  page.on('response', response => { if (response.status() >= 500) errors.push('servererror') })
  await page.goto('http://127.0.0.1:8000')
  await page.getByText('REAL DATA', { exact: true }).first().waitFor()
  await page.getByRole('heading', { name: 'Your training, in context.' }).waitFor()
  await page.getByText(/Strong history is not connected|Strong history not connected|Strong not connected/i).first().waitFor()
  await mkdir(resolve('private/real'), { recursive: true })
  await page.screenshot({ path: resolve('private/real/dashboard.png'), fullPage: true })
  for (const name of ['History', 'Cycle', 'Data & settings']) {
    await page.locator('nav').getByRole('button', { name, exact: true }).click()
    await page.waitForTimeout(250)
    console.log(`${name}: real-data view loaded`)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  if (overflow) throw new Error('Mobile horizontal overflow')
  if (errors.length) throw new Error(`Browser errors: ${errors.length}`)
  console.log('Production real-data browser smoke passed; no personal data was changed.')
} finally {
  await browser.close()
}
