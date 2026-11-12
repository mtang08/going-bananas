import { expect, test, type APIResponse } from '../frontend/node_modules/@playwright/test'

// These journeys run only against the isolated calendar preview fixture.
test.describe.configure({ mode: 'serial' })
const data = async (response: APIResponse) => (await response.json()).data
const day = (today: string, offset: number) => {
  const date = new Date(`${today}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + offset)
  return date.toISOString().slice(0, 10)
}

test.beforeEach(async ({ request }) => {
  const response = await request.get('/api/v1/profile')
  expect(response.ok()).toBe(true)
  const envelope = await response.json()
  expect(envelope.mode).toBe('demo')
  expect(envelope.data.planning_authority).toBe('calendar')
})

test('p0a: home shows today and 14-day strip', async ({ page, request }) => {
  const calendar = await data(await request.get('/api/v1/calendar'))
  const history = await data(await request.get(`/api/v1/calendar?start=${day(calendar.today,-2)}&end=${calendar.today}`))
  const completedLong = history.sessions.find((s: {local_date:string;recipe_id:string}) =>
    s.local_date === day(calendar.today,-2) && s.recipe_id === 'REC002')
  expect(completedLong).toBeTruthy()
  expect(history.completions.some((c: {session_uid:string;activity_id:string|null}) =>
    c.session_uid === completedLong.session_uid && Boolean(c.activity_id))).toBe(true)
  const linked = history.completions.find((c: {session_uid:string;activity_id:string|null}) =>
    c.session_uid === completedLong.session_uid && c.activity_id)
  const longRuns = await data(await request.get(`/api/v1/metrics/long-runs?start=${day(calendar.today,-2)}&end=${calendar.today}`))
  expect(longRuns.some((metric: {value:{activity_id:string;classification:string}}) =>
    metric.value.activity_id === linked.activity_id && metric.value.classification === 'long')).toBe(true)
  await page.goto('/')
  await expect(page.getByTestId('today-card')).toBeVisible()
  const cells = page.getByTestId('strip-day')
  await expect(cells).toHaveCount(14)
  expect(await cells.first().getAttribute('data-date')).toBe(calendar.today)
  expect(await cells.last().getAttribute('data-date')).toBe(day(calendar.today, 13))
  await expect(page.getByTestId('today-card').getByText(/No session|Committed|Provisional/).first()).toBeVisible()
})

test('p0a: prompts on schedule', async ({ page, request }) => {
  const current = await data(await request.get('/api/v1/calendar'))
  const calendar = await data(await request.get(`/api/v1/calendar?start=${day(current.today,-7)}&end=${day(current.today,13)}`))
  const prompts = await data(await request.get('/api/v1/prompts'))
  const open = prompts.items.filter((p: {status: string}) => p.status === 'open')
  expect(open.some((p: {kind: string}) => p.kind === 'rpe')).toBe(true)
  expect(open.some((p: {kind: string}) => p.kind === 'delayed_symptom')).toBe(true)
  expect(open.some((p: {kind: string; session_uid: string}) => p.kind === 'missing_activity' &&
    calendar.sessions.some((s: {session_uid: string; local_date: string}) => s.session_uid === p.session_uid && s.local_date === day(calendar.today, -4)))).toBe(true)
  await page.goto('/')
  await expect(page.locator('[data-testid="prompt-item"][data-kind="rpe"]').first()).toBeVisible()
  await expect(page.locator('[data-testid="prompt-item"][data-kind="delayed_symptom"]').first()).toBeVisible()
  await expect(page.locator('[data-testid="prompt-item"][data-kind="missing_activity"]').first()).toBeVisible()
})

test('p0a: manual edit versions', async ({ page, request }) => {
  const before = await data(await request.get('/api/v1/calendar'))
  const original = before.sessions.find((s: {local_date:string; locked:boolean; kind:string}) =>
    s.local_date >= before.today && !s.locked && s.kind === 'run')
  expect(original).toBeTruthy()
  const movedDate = day(original.local_date, 1)
  const edit = await request.post('/api/v1/calendar/edits', {headers:{'X-Local-Request':'1'}, data:{
    expected_head:before.head, edits:[{op:'move',session_uid:original.session_uid,fields:{local_date:movedDate}}],
  }})
  expect(edit.status()).toBe(201)
  const edited = await data(edit)
  expect(edited.version).toBe(before.head + 1)
  const after = await data(await request.get('/api/v1/calendar'))
  expect(after.sessions.find((s: {session_uid:string}) => s.session_uid === original.session_uid)?.local_date).toBe(movedDate)
  await page.goto('/#calendar')
  await expect(page.getByTestId('version-row').filter({hasText:`v${edited.version} · Manual edit`})).toBeVisible()
  const rollback = await request.post('/api/v1/calendar/rollback', {headers:{'X-Local-Request':'1'}, data:{expected_head:edited.version,to_version:before.head}})
  expect(rollback.status()).toBe(201)
  const restored = await data(await request.get('/api/v1/calendar'))
  expect(restored.sessions.find((s: {session_uid:string}) => s.session_uid === original.session_uid)?.local_date).toBe(original.local_date)
  for (const old of before.sessions.filter((s: {local_date:string;locked:boolean}) => s.local_date < before.today || s.locked)) {
    expect(restored.sessions.find((s: {session_uid:string}) => s.session_uid === old.session_uid)?.local_date).toBe(old.local_date)
  }
})

test('p0a: structured workout per-rep', async ({ page, request }) => {
  const current = await data(await request.get('/api/v1/calendar'))
  const calendar = await data(await request.get(`/api/v1/calendar?start=${day(current.today,-14)}&end=${day(current.today,13)}`))
  for (const [offset, mismatch] of [[-6,false],[-12,true]] as const) {
    const session = calendar.sessions.find((s: {local_date:string;recipe_id:string}) => s.local_date === day(calendar.today,offset) && s.recipe_id === 'REC003')
    const completion = calendar.completions.find((c: {session_uid:string}) => c.session_uid === session.session_uid)
    expect(completion.activity_id).toBeTruthy()
    await page.goto(`/#activity/${completion.activity_id}`)
    await expect(page.getByRole('heading',{name:'Reps'})).toBeVisible()
    if (mismatch) await expect(page.getByText(/watch workout does not match the planned structure/)).toBeVisible()
    else await expect(page.getByRole('table',{name:/reps/i}).locator('tbody tr')).toHaveCount(4)
  }
})

test('p0a: check-in exception guidance', async ({ page, request }) => {
  const body = {idempotency_key:crypto.randomUUID(),kind:'exception',observed_at:new Date().toISOString(),
    fatigue:7,illness:null,gait_change:null,context_tags:[],symptoms:[],activity_id:null,prompt_id:null,note:null}
  const response = await request.post('/api/v1/v2/checkins',{headers:{'X-Local-Request':'1'},data:body})
  expect(response.status()).toBe(201)
  const guidance = await data(await request.post('/api/v1/coach/v2/daily/request',{headers:{'X-Local-Request':'1'},data:{}}))
  expect(guidance.decision).toBe('modify')
  expect(guidance.coach_review_suggested).toBe(true)
  await page.goto('/')
  await expect(page.getByText(/Coach review suggested/)).toBeVisible()
})

test('p0a: trends explicit missing', async ({ page, request }) => {
  const calendar = await data(await request.get('/api/v1/calendar'))
  await page.goto('/#trends')
  await expect(page.getByRole('heading',{name:'Trends.'})).toBeVisible()
  for (const offset of [-4,-6]) {
    const row = page.locator(`[data-testid="recovery-night"][data-date="${day(calendar.today,offset)}"]`)
    await expect(row).toHaveClass(/missing/)
  }
  await expect(page.getByText(/No anchor/).first()).toBeVisible()
})

test('p0a: anchor enables intensity', async ({ page, request }) => {
  const calendar = await data(await request.get('/api/v1/calendar'))
  const existing = await data(await request.get('/api/v1/anchors'))
  for (const [kind,value] of [['hr_aerobic_upper',150],['hr_threshold_lower',165]] as const) {
    if (existing.items.some((anchor: {kind:string;value_low:number;valid_from:string}) =>
      anchor.kind === kind && anchor.value_low === value && anchor.valid_from <= day(calendar.today,-28))) continue
    const response = await request.post('/api/v1/anchors',{headers:{'X-Local-Request':'1'},data:{
      kind,value_low:value,value_high:null,unit:'bpm',protocol:'manual',confidence:'moderate',
      calibrated_at:`${day(calendar.today,-28)}T12:00:00Z`,valid_from:day(calendar.today,-28),conditions:null,notes:null,supersedes_key:null,
    }})
    expect(response.status()).toBe(200)
  }
  await page.goto('/#trends')
  await expect(page.getByText(/Easy .* Moderate .* High/).first()).toBeVisible()
})

test('p0a: only local requests', async ({ page }) => {
  const hosts = new Set<string>()
  page.on('request', request => hosts.add(new URL(request.url()).hostname))
  await page.goto('/')
  await page.getByRole('button',{name:'Calendar'}).click()
  await page.getByRole('button',{name:'Trends'}).click()
  expect([...hosts]).toEqual(['127.0.0.1'])
})
