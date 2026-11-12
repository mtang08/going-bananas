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
  if (profile.data.planning_authority === 'calendar') {
    await mkdir(resolve('private/real/release'), { recursive: true })
    await page.getByTestId('today-card').waitFor()
    const views = [
      ['calendar', 'Calendar.'], ['trends', 'Trends.'], ['block', 'Training block'],
      ['history', 'Training history.'], ['strength', 'Strength history.'],
      ['settings', 'Planning settings'], ['coach', 'Coaching history'],
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
  } else {
  await page.getByRole('heading', { name: 'Your training, in context.' }).waitFor()
  await page.getByText(/Strong export connected|Strong export is included/i).first().waitFor()
  await mkdir(resolve('private/real'), { recursive: true })
  await page.screenshot({ path: resolve('private/real/dashboard.png'), fullPage: true })
  for (const name of ['History', 'Cycle', 'Data & settings']) {
    await page.locator('nav').getByRole('button', { name, exact: true }).click()
    await page.waitForTimeout(250)
    console.log(`${name}: real-data view loaded`)
  }
  if (await page.getByLabel('Strength schedule').inputValue() !== 'alternating') throw new Error('Alternating schedule not shown')
  if (await page.getByLabel('Week A Monday').inputValue() !== '2026-11-09') throw new Error('Week A reference not shown')
  await page.screenshot({ path: resolve('private/real/schedule-settings-readonly.png'), fullPage: true })
  await page.locator('nav').getByRole('button', { name: 'Cycle', exact: true }).click()
  await page.getByText('Full-body strength · repeating').first().waitFor()
  await page.getByText('Gym mobility · repeating').first().waitFor()
  await page.getByText('Mobility · optional · repeating').first().waitFor()
  await page.screenshot({ path: resolve('private/real/recurring-cycle-readonly.png'), fullPage: true })
  await page.locator('nav').getByRole('button', { name: 'History', exact: true }).click()
  await page.getByLabel('Start date').fill('2025-09-01')
  await page.getByLabel('End date').fill('2025-12-31')
  await page.getByRole('button', { name: 'Show dates' }).click()
  const runRow = page.locator('.activity-table tbody tr').filter({ hasText: 'running' }).first()
  await runRow.waitFor()
  await runRow.getByRole('button').click()
  const activityDialog = page.getByRole('dialog', { name: 'Activity detail' })
  await activityDialog.locator('details summary').filter({ hasText: /Auto:|Manual:|Source:|Run type unknown/ }).waitFor()
  await page.screenshot({ path: resolve('private/real/run-classification-readonly.png'), fullPage: true })
  await activityDialog.getByRole('button', { name: 'Close' }).click()
  await page.locator('nav').getByRole('button', { name: 'Coach', exact: true }).click()
  await page.getByRole('heading', { name: 'Plan, train, review.' }).waitFor()
  await page.getByRole('heading', { name: 'Coach plan history' }).waitFor()
  await page.getByText(/Review my recent training and plan the next 14 days/).waitFor()
  await page.getByText('Local rule guidance · legacy', { exact: true }).click()
  await page.getByRole('button', { name: 'Generate daily guidance' }).waitFor()
  await page.screenshot({ path: resolve('private/real/coach-readonly.png'), fullPage: true })
  await page.locator('nav').getByRole('button', { name: 'Strength', exact: true }).click()
  await page.getByRole('heading', { name: 'Strength history.' }).waitFor()
  await page.getByText(/recorded workouts in/).first().waitFor()
  await page.screenshot({ path: resolve('private/real/strength-readonly.png'), fullPage: true })
  if (process.argv.includes('--export')) {
    await page.locator('nav').getByRole('button', { name: 'Data & settings', exact: true }).click()
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
  for (const name of ['Strength', 'Cycle', 'Coach']) {
    if(name!=='Strength'){
      await page.getByRole('button', { name: 'Open menu' }).click()
      await page.locator('nav').getByRole('button', { name, exact: true }).click()
      await page.getByRole('heading', { name: name==='Coach'?'Plan, train, review.':'Keep the rhythm visible.' }).waitFor()
      await page.waitForFunction(() => parseFloat(getComputedStyle(document.querySelector('.sidebar')).left) <= -230)
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    if (overflow) throw new Error(`${name} mobile horizontal overflow`)
    await page.screenshot({ path: resolve(`private/real/${name.toLowerCase()}-mobile-readonly.png`), fullPage: true })
  }
  }
  if (errors.length) throw new Error(`Browser errors: ${errors.length}`)
  console.log('Production real-data browser smoke passed; no personal data was changed.')
} finally {
  await browser.close()
}
