// Exercise a real user's Settings form against the normal synthetic supervisor.
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium, expect } = require('@playwright/test')
const port = Number(process.argv[2])
assert(Number.isInteger(port) && port > 0 && port <= 65535)
const origin = 'http://127.0.0.1:' + port
const browser = await chromium.launch({ channel: 'chrome' })
try {
  const page = await browser.newPage()
  const health = await page.request.get(origin + '/api/v1/health/ready')
  assert.equal(health.status(), 200)
  assert.equal((await health.json()).mode, 'test')
  await page.goto(origin + '/#settings')
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
  const text = 'Supervisor smoke ' + randomUUID()
  await page.getByLabel('Goal', { exact: true }).fill(text, { timeout: 15000 })
  await page.getByRole('button', { name: 'Add goal' }).click()
  await expect(page.getByText(text, { exact: false })).toBeVisible()
  await page.reload()
  await expect(page.getByText(text, { exact: false })).toBeVisible()
} finally {
  await browser.close()
}
