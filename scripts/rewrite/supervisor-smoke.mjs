// Exercise a real user's Settings form against the normal synthetic supervisor.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium, expect } = require('@playwright/test')
const port = Number(process.argv[2])
assert(Number.isInteger(port) && port > 0 && port <= 65535)
const origin = 'http://127.0.0.1:' + port
const ready = await fetch(origin + '/api/v1/health/ready')
assert.equal(ready.status, 200)
assert.equal((await ready.json()).mode, 'test')
const html = await (await fetch(origin)).text()
assert.match(html, /<div id="root">/)
const script = html.match(/<script[^>]+src="([^"]+)"[^>]*>/)
assert(script)
assert.equal((await fetch(new URL(script[1], origin))).status, 200)
const text = 'Supervisor smoke ' + randomUUID()
const engine = process.env.SUPERVISOR_ENGINE ?? 'chrome'
if (engine === 'dom') {
  const cwd = fileURLToPath(new URL('../../frontend/', import.meta.url))
  execFileSync('npm', ['exec', '--', 'vitest', 'run', 'tests/goal-settings-http.test.tsx'], {
    cwd, stdio: 'inherit',
    env: { ...process.env, GOAL_SETTINGS_FIXTURE: text, PROPOSAL_HOME_ORIGIN: origin },
  })
  process.exit(0)
}
assert(['chrome', 'chromium'].includes(engine))
const browser = await chromium.launch(engine === 'chrome' ? { channel: 'chrome' } : {})
try {
  const page = await browser.newPage()
  const health = await page.request.get(origin + '/api/v1/health/ready')
  assert.equal(health.status(), 200)
  assert.equal((await health.json()).mode, 'test')
  await page.goto(origin + '/#settings')
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
  await page.getByLabel('Goal', { exact: true }).fill(text, { timeout: 15000 })
  await page.getByRole('button', { name: 'Add goal' }).click()
  await expect(page.getByText(text, { exact: false })).toBeVisible()
  await page.reload()
  await expect(page.getByText(text, { exact: false })).toBeVisible()
} finally {
  await browser.close()
}
