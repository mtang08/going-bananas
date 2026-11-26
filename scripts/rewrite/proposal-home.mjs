// Run after loading backend/tests/fixtures/proposal-list.sql. psql uses the same PG* environment.
import assert from 'node:assert/strict'
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
  server: { host: '127.0.0.1', port: 0, strictPort: true },
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
  upstreams.push({ path: request.path, target })
  if (disconnectList && request.path === list && target === candidate) {
    request.destroy(new Error('Proposal upstream disconnected by the test'))
  }
}

async function renderState(state) {
  if (!browser) {
    const child = spawn(
      process.execPath,
      [require.resolve('vitest/vitest.mjs'), 'run', 'tests/proposal-home-http.test.tsx'],
      {
        cwd: frontend,
        env: { ...process.env, PROPOSAL_HOME_STATE: state, PROPOSAL_HOME_ORIGIN: origin },
        stdio: 'inherit',
      },
    )
    const [code] = await once(child, 'exit')
    assert.equal(code, 0, 'Home DOM check failed')
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
    assert.equal(target, path === list ? candidate : python, 'Wrong upstream for ' + path)
  }
}

try {
  await vite.listen()
  origin = 'http://127.0.0.1:' + vite.httpServer.address().port
  httpRequests.subscribe(observeUpstream)
  await checkState('open')
  setFixtureStatus('pending', 'accepted')
  try {
    await checkState('empty')
  } finally {
    setFixtureStatus('accepted', 'pending')
  }
  await checkState('failed')
  console.log(
    `PASS Home (${engine}) rendered the Go draft, empty list, and disconnected list alert alongside Python.`,
  )
} finally {
  httpRequests.unsubscribe(observeUpstream)
  await vite.close()
  await browser?.close()
}
