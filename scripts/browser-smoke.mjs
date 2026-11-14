import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  await page.route('**/api/**', route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) { errors.push('unexpected mutation'); return route.abort() }
    return route.continue()
  })
  page.on('pageerror', () => errors.push('pageerror'))
  page.on('response', response => { if (response.status() >= 500) errors.push('servererror') })
  await page.goto('http://127.0.0.1:8000')
  await page.getByText('REAL DATA', { exact: true }).first().waitFor()
  const profile = await (await page.request.get('http://127.0.0.1:8000/api/v1/profile')).json()
  if (profile.mode !== 'real') throw new Error('Expected real workspace')
  if (profile.data.planning_authority !== 'calendar') throw new Error('Calendar authority required')
  await mkdir(resolve('private/real/release'), { recursive: true })
  await page.getByTestId('today-card').waitFor()
  const views = [
    ['calendar', 'Calendar.'], ['trends', 'Trends.'], ['block', 'Training block'],
    ['settings', 'Settings'],
  ]
  for (const [hash, heading] of views) {
    await page.goto(`http://127.0.0.1:8000/#${hash}`)
    await page.getByRole('heading', { name: heading, exact: true }).waitFor()
    await page.waitForLoadState('networkidle')
    if (await page.getByText('Could not load this view', { exact: true }).count()) throw new Error(`${hash} read failed`)
    console.log(`${hash}: real-data view loaded`)
  }
  await page.goto('http://127.0.0.1:8000/#settings')
  if (await page.getByLabel('Strength schedule').inputValue() !== profile.data.strength_schedule_mode) throw new Error('Schedule mismatch')
  if (await page.getByLabel('Week A Monday').inputValue() !== profile.data.strength_week_a_start) throw new Error('Week A mismatch')
  const activities = await (await page.request.get('http://127.0.0.1:8000/api/v1/activities?limit=50')).json()
  const run = activities.data.items.find(item => ['running', 'trail_running', 'treadmill_running'].includes(item.sport))
  if (!run) throw new Error('Expected existing run history')
  await page.goto(`http://127.0.0.1:8000/#activity/${run.id}`)
  await page.getByRole('heading', { name: 'Planned vs actual', exact: true }).waitFor()
  await page.waitForLoadState('networkidle')
  await page.screenshot({ path: resolve('private/real/release/activity-readonly.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  for (const hash of ['home', 'calendar', 'trends', 'block', 'settings']) {
    await page.goto(`http://127.0.0.1:8000/#${hash}`)
    await page.waitForLoadState('networkidle')
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error(`${hash} mobile horizontal overflow`)
    await page.screenshot({ path: resolve(`private/real/release/${hash}-mobile-readonly.png`), fullPage: true })
  }
  if (errors.length) throw new Error(`Browser errors: ${errors.length}`)
  console.log('Production real-data browser smoke passed; no personal data was changed.')
} finally {
  await browser.close()
}
