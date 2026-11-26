// Run after loading backend/tests/fixtures/proposal-list.sql. psql uses the same PG* environment.
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { execFileSync, spawn } from 'node:child_process'
import { once } from 'node:events'
import { channel } from 'node:diagnostics_channel'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium, firefox, webkit, expect } = require('@playwright/test')
const ports = process.argv.slice(2)
assert(
  ports.length === 2 && ports.every((p) => /^\d+$/.test(p) && +p > 0 && +p <= 65535),
  'Usage: node scripts/rewrite/proposal-home.mjs <python_port> <go_port>',
)
const [python, candidate] = ports.map((p) => 'http://127.0.0.1:' + Number(p))
assert.notEqual(python, candidate)
const list = '/api/v1/coach/proposals?status=open'
const goalText = 'Settings fixture ' + randomUUID()
const draft = '00000000-0000-0000-0000-000000000033'

function setFixtureStatus(before, after) {
  const sql = `UPDATE coach_proposals SET status = '${after}'
    WHERE right(current_database(), 5) = '_test' AND status = '${before}'
      AND id = '${draft}' AND skill_version = 'fixture' AND input_hash = md5('51')
      AND snapshot_id = '00000000-0000-0000-0000-000000000001'
    RETURNING id`
  const changed = execFileSync('psql', ['-XqAt', '-v', 'ON_ERROR_STOP=1', '-c', sql], {
    encoding: 'utf8',
  })
  assert.equal(changed.trim(), draft, 'Expected disposable proposal-list fixture')
}

for (const url of [python + '/api/v1/profile', candidate + list]) {
  const response = await fetch(url)
  assert.equal(response.status, 200)
  assert.equal((await response.json()).mode, 'test', 'Start both listeners in test mode')
}

const engine = process.env.PROPOSAL_HOME_ENGINE || 'chrome'
const browsers = { chrome: chromium, chromium, webkit, firefox }
assert(engine === 'dom' || Object.hasOwn(browsers, engine), 'Unknown PROPOSAL_HOME_ENGINE')
const browser =
  engine === 'dom'
    ? null
    : await browsers[engine].launch(engine === 'chrome' ? { channel: 'chrome' } : {})

const frontend = fileURLToPath(new URL('../../frontend/', import.meta.url))
Object.assign(process.env, { APP_MODE: 'test', APP_PORT: ports[0], PROPOSAL_GO_PORT: ports[1] })
const { createServer } = await import(require.resolve('vite'))
const vite = await createServer({
  root: frontend,
  server: { host: '127.0.0.1', port: Number(process.env.VITE_PORT ?? 5173), strictPort: true },
  logLevel: 'silent',
})
let origin
let disconnectList = false
const upstreams = []
// Inspect the real outbound requests made by Vite's Node HTTP proxy.
const httpRequests = channel('http.client.request.start')
function observeUpstream({ request }) {
  if (!request.path.startsWith('/api/v1/')) return
  const target = 'http://' + request.getHeader('host')
  upstreams.push({ path: request.path, method: request.method, target })
  if (disconnectList && request.path === list && target === candidate) {
    request.destroy(new Error('Proposal upstream disconnected by the test'))
  }
}

async function renderDOM(testFile, extraEnv) {
  const child = spawn(process.execPath, [require.resolve('vitest/vitest.mjs'), 'run', testFile], {
    cwd: frontend,
    env: { ...process.env, PROPOSAL_HOME_ORIGIN: origin, ...extraEnv },
    stdio: 'inherit',
  })
  const [code] = await once(child, 'exit')
  assert.equal(code, 0, 'UI check failed')
}

async function renderState(state) {
  if (!browser) {
    await renderDOM('tests/proposal-home-http.test.tsx', { PROPOSAL_HOME_STATE: state })
    return
  }
  const page = await browser.newPage()
  try {
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    const result = page.waitForResponse(origin + list)
    await page.goto(origin)
    const response = await result
    assert.equal(response.status(), state === 'failed' ? 500 : 200)
    if (state !== 'failed') {
      assert.equal((await response.json()).data.items.length, state === 'open' ? 1 : 0)
    }
    await expect(page.getByText('No calendar yet.', { exact: true })).toBeVisible()
    const rows = page.locator('[data-testid="attention-row"][data-kind="proposal"]')
    const problem = page.getByRole('alert').filter({ hasText: 'Could not load proposals' })
    if (state === 'open') {
      await expect(rows).toHaveCount(1)
      await expect(rows).toContainText('Pending')
      await expect(rows).toContainText('2 changes')
      await expect(rows.getByRole('link', { name: 'Review' })).toHaveAttribute(
        'href',
        '#proposal/' + draft,
      )
    } else {
      await expect(rows).toHaveCount(0)
    }
    if (state === 'failed') await expect(problem).toBeVisible()
    else await expect(problem).toHaveCount(0)
    assert.deepEqual(errors, [])
  } finally {
    await page.close()
  }
}

function isTravel(requestPath) {
  const path = requestPath.split('?')[0]
  return path === '/api/v1/trips' || path.startsWith('/api/v1/google-calendar/')
}

async function checkState(state) {
  upstreams.length = 0
  disconnectList = state === 'failed'
  await renderState(state)
  assert(
    upstreams.some(({ path }) => path === list),
    'Home did not request open proposals',
  )
  assert(
    upstreams.some(({ path }) => path === '/api/v1/calendar'),
    'Home did not request calendar',
  )
  for (const { path, target } of upstreams) {
    assert.equal(target, [list, '/api/v1/goals'].includes(path) || isTravel(path) ? candidate : python, 'Wrong upstream for ' + path)
  }
}

async function checkGoalEdit() {
  upstreams.length = 0
  disconnectList = false
  if (browser) {
    const page = await browser.newPage()
    try {
      await page.goto(origin + '/#settings')
      await page.getByLabel('Goal', { exact: true }).fill(goalText)
      await page.getByRole('button', { name: 'Add goal' }).click()
      await page.getByText(goalText).getByRole('button', { name: 'Edit' }).click()
      await page.getByLabel('Goal', { exact: true }).fill('Updated ' + goalText)
      await page.getByRole('button', { name: 'Save goal' }).click()
      await expect(page.getByText('Updated ' + goalText)).toBeVisible()
    } finally {
      await page.close()
    }
  } else {
    await renderDOM('tests/goal-settings-http.test.tsx', { GOAL_SETTINGS_FIXTURE: goalText })
  }

  const goalsPath = '/api/v1/goals'
  const reads = upstreams.filter(({ method, path }) => method === 'GET' && path === goalsPath)
  assert(reads.length >= 2, 'Expected the Settings goal list to refresh after edits')
  assert(upstreams.some(({ method, path }) => method === 'POST' && path === goalsPath))
  const writes = upstreams.filter(({ method }) => method === 'PATCH')
  assert.equal(writes.length, 1)
  assert.match(writes[0].path, /^\/api\/v1\/goals\/[a-f0-9-]{36}$/)
  for (const request of upstreams) {
    assert.equal(
      request.target,
      request === writes[0] || request.path === goalsPath || isTravel(request.path) ? candidate : python,
      'Wrong upstream for ' + request.path,
    )
  }
  console.log(
    `PASS Settings (${engine}) created, edited and reloaded a goal in Go.`,
  )
}

try {
  await vite.listen()
  origin = 'http://127.0.0.1:' + vite.httpServer.address().port
  httpRequests.subscribe(observeUpstream)
  const tripsPath = '/api/v1/trips'
  const body = { start_date: '2026-06-08', end_date: '2026-06-10', destination_label: 'Synthetic trip', destination_tz: 'Europe/Paris' }
  const create = await fetch(origin + tripsPath, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Local-Request': '1' }, body: JSON.stringify(body),
  })
  assert.equal(create.status, 201, 'Go trip write through Vite')
  const created = (await create.json()).data
  assert.equal(created.destination_label, body.destination_label)
  assert(upstreams.some(r => r.method === 'POST' && r.path === tripsPath && r.target === candidate))
  const forbidden = await fetch(origin + tripsPath, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  assert.equal(forbidden.status, 403)
  console.log('PASS trip creation used Go and enforced the shared local write guard')
  await checkState('open')
  setFixtureStatus('pending', 'accepted')
  try {
    await checkState('empty')
  } finally {
    setFixtureStatus('accepted', 'pending')
  }
  await checkState('failed')
  await checkGoalEdit()
  console.log(
    `PASS Home (${engine}) rendered the Go draft, empty list, and disconnected list alert alongside Python.`,
  )
} finally {
  httpRequests.unsubscribe(observeUpstream)
  await vite.close()
  await browser?.close()
}
