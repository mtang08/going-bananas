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
  if (process.argv.includes('--export')) {
    await page.getByRole('heading', { name: 'Historical imports' }).waitFor()
    await page.getByText('Garmin export', { exact: true }).first().waitFor()
    await page.getByText(/Observed dates only; completeness unverified/).first().waitFor()
    await page.locator('nav').getByRole('button', { name: 'History', exact: true }).click()
    await page.getByLabel('Start date').fill('2025-09-01')
    await page.getByLabel('End date').fill('2025-12-31')
    const history = page.waitForResponse(response => response.url().includes('/api/v1/activities?') && response.url().includes('start_date=2025-09-01'))
    await page.getByRole('button', { name: 'Show dates' }).click()
    const result = await (await history).json()
    if (result.mode !== 'real' || !result.data.items.length) throw new Error('Imported history missing')
    await page.getByText('Sep 1, 2025 – Dec 31, 2025', { exact: true }).waitFor()
    await page.screenshot({ path: resolve('private/real/imported-history.png'), fullPage: true })
    console.log('Imported prior-year history and import coverage rendered successfully')
  }
  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  if (overflow) throw new Error('Mobile horizontal overflow')
  if (errors.length) throw new Error(`Browser errors: ${errors.length}`)
  console.log('Production real-data browser smoke passed; no personal data was changed.')
} finally {
  await browser.close()
}
