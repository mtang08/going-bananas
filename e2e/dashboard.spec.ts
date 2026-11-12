import { expect, test } from '../frontend/node_modules/@playwright/test'

test.beforeAll(async ({ request }) => {
  const response = await request.get('/api/v1/profile')
  const envelope = await response.json()
  expect(envelope.mode).toBe('demo')
  const p = envelope.data
  const configured = await request.put('/api/v1/profile', {
    headers: { 'X-Local-Request': '1' },
    data: { ...p, expected_version: p.version, timezone: 'America/New_York',
      cycle_anchor: '2026-11-02', anchor_confirmed: true,
      strength_days_confirmed: true, scheduled_strength_days: [0, 4] },
  })
  expect(configured.ok()).toBe(true)
})

test.beforeEach(async ({request}) => {
  const response=await request.get('/api/v1/health/live')
  expect(response.ok()).toBe(true)
  expect((await response.json()).mode).toBe('demo')
})

test('demo API drives overview, history, cycle, settings and check-in', async ({page}) => {
  const problems:string[]=[]
  page.on('pageerror', e=>problems.push(e.message))
  await page.goto('/')
  await expect(page.getByText('DEMO DATA').first()).toBeVisible()
  await expect(page.getByRole('heading',{name:'Your training, in context.'})).toBeVisible()
  await expect(page.getByText('This week', {exact:true})).toBeVisible()
  await page.getByRole('button',{name:'History'}).click()
  await expect(page.getByRole('heading',{name:'Training history.'})).toBeVisible()
  await page.getByRole('button',{name:'Cycle'}).click()
  await expect(page.getByRole('heading',{name:'Keep the rhythm visible.'})).toBeVisible()
  await page.getByRole('button',{name:'Data & settings'}).click()
  await expect(page.getByRole('heading',{name:'Data & settings.'})).toBeVisible()
  await page.getByRole('button',{name:'Record check-in'}).first().click()
  await expect(page.getByRole('dialog',{name:'Record check-in'})).toBeVisible()
  await page.getByRole('button',{name:/No issues; usual energy/}).click()
  await expect(page.getByRole('dialog',{name:'Record check-in'})).toBeHidden()
  expect(problems).toEqual([])
})

test('mobile view exposes navigation and quick check-in', async ({page}) => {
  await page.setViewportSize({width:390,height:844})
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'Your training, in context.'})).toBeVisible()
  await page.getByRole('button',{name:'Open menu'}).click()
  await page.getByRole('button',{name:'History'}).click()
  await expect(page.getByRole('heading',{name:'Training history.'})).toBeVisible()
  await page.getByRole('button',{name:'Record check-in'}).first().click()
  await expect(page.getByRole('dialog',{name:'Record check-in'})).toBeVisible()
})

test('history can browse a prior year with bounded date windows', async ({page}) => {
  await page.goto('/')
  await page.getByRole('button',{name:'History'}).click()
  await page.getByLabel('Start date').fill('2020-01-01')
  await page.getByLabel('End date').fill('2020-12-31')
  const first=page.waitForResponse(response=>response.url().includes('/api/v1/activities?')&&response.url().includes('start_date=2020-01-01')&&response.url().includes('end_date=2020-12-31'))
  await page.getByRole('button',{name:'Show dates'}).click()
  expect((await first).ok()).toBe(true)
  await expect(page.getByText('Jan 1, 2020 – Dec 31, 2020')).toBeVisible()
  const prior=page.waitForResponse(response=>response.url().includes('/api/v1/activities?')&&response.url().includes('end_date=2019-12-31'))
  await page.getByRole('button',{name:'Previous date window'}).click()
  expect((await prior).ok()).toBe(true)
  await page.getByLabel('Start date').fill('2019-01-01')
  await page.getByLabel('End date').fill('2020-12-31')
  await expect(page.getByText('Choose a window of 366 dates or fewer.')).toBeVisible()
  await expect(page.getByRole('button',{name:'Show dates'})).toBeDisabled()
})

test('demo Coach generates explicit daily and weekly guidance without changing plans', async ({page}) => {
  const plansBefore=await (await page.request.get('/api/v1/plans')).json()
  await page.goto('/')
  await page.getByRole('button',{name:'Coach',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Plan, train, review.'})).toBeVisible()
  await expect(page.getByText(/Review my recent training and plan the next 14 days/)).toBeVisible()
  await page.getByText('Local rule guidance · legacy', {exact:true}).click()
  await expect(page.getByRole('button',{name:'Generate daily guidance'})).toBeVisible()
  await page.getByLabel('Illness').selectOption('none')
  const generated=page.waitForResponse(response=>response.url().endsWith('/api/v1/coach/daily')&&response.request().method()==='POST')
  await page.getByRole('button',{name:'Generate daily guidance'}).click()
  expect((await generated).ok()).toBe(true)
  await expect(page.getByText('Suggested session')).toBeVisible()
  await page.getByRole('button',{name:'Tomorrow preview'}).click()
  await expect(page.getByText(/Tomorrow’s preview is provisional/)).toBeVisible()
  const preview=page.waitForResponse(response=>response.url().endsWith('/api/v1/coach/daily')&&response.request().method()==='POST')
  await page.getByRole('button',{name:'Generate daily guidance'}).click()
  expect((await preview).ok()).toBe(true)
  await expect(page.getByRole('button',{name:'Accept suggestion'})).toBeDisabled()
  await expect(page.getByRole('button',{name:'Decline'})).toBeDisabled()
  await page.getByRole('button',{name:'Weekly review'}).click()
  const weekly=page.waitForResponse(response=>response.url().endsWith('/api/v1/coach/weekly')&&response.request().method()==='POST')
  await page.getByRole('button',{name:'Generate weekly review'}).click()
  expect((await weekly).ok()).toBe(true)
  await expect(page.getByText('Next cycle proposal')).toBeVisible()
  const plansAfter=await (await page.request.get('/api/v1/plans')).json()
  expect(plansAfter.data.items).toEqual(plansBefore.data.items)
})

test('demo Strength browses imported years and recorded sets on mobile', async ({page}) => {
  await page.setViewportSize({width:390,height:844})
  await page.goto('/')
  await page.getByRole('button',{name:'Open menu'}).click()
  await page.getByRole('button',{name:'Strength'}).click()
  await expect(page.getByRole('heading',{name:'Strength history.'})).toBeVisible()
  const years=(await (await page.request.get('/api/v1/strength/years')).json()).data.years
  if(years.length){
    const year=String(years[0].year)
    await page.getByLabel('Year').selectOption(year)
    await expect(page.getByText(new RegExp(`recorded workouts in ${year}`))).toBeVisible()
    const workout=page.locator('table tbody .table-link').first()
    if(await workout.count()){
      await workout.click()
      await expect(page.getByText(/Recorded set values · units unconfirmed/)).toBeVisible()
    }
  }
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false)
})

test('demo Week A/B settings project full-body and mobility without weekly drafts', async ({page}) => {
  const response=await page.request.get('/api/v1/profile')
  const profile=(await response.json()).data
  const saved=await page.request.put('/api/v1/profile',{
    headers:{'X-Local-Request':'1'},
    data:{...profile,expected_version:profile.version,strength_schedule_mode:'alternating',strength_week_a_start:'2026-11-09',strength_week_a_days:[0,4],strength_week_b_days:[1,5],mobility_week_a_days:[2],mobility_week_b_days:[3],mobility_optional_days:[6],strength_days_confirmed:true},
  })
  expect(saved.ok()).toBe(true)
  const planResponse=await page.request.get('/api/v1/plans?start_date=2027-01-04&end_date=2027-01-17')
  expect(planResponse.ok()).toBe(true)
  const slots=(await planResponse.json()).data.recurring_sessions as {date:string;kind:string;optional:boolean}[]
  expect(slots.filter(s=>s.kind==='strength').map(s=>s.date)).toEqual(['2027-01-04','2027-01-08','2027-01-12','2027-01-16'])
  expect(slots.filter(s=>s.kind==='mobility'&&!s.optional).map(s=>s.date)).toEqual(['2027-01-06','2027-01-14'])
  expect(slots.filter(s=>s.kind==='mobility'&&s.optional).map(s=>s.date)).toEqual(['2027-01-10','2027-01-17'])
  await page.goto('/')
  await page.getByRole('button',{name:'Data & settings'}).click()
  await expect(page.getByLabel('Strength schedule')).toHaveValue('alternating')
  await expect(page.getByLabel('Week A Monday')).toHaveValue('2026-11-09')
  await page.getByRole('button',{name:'Cycle'}).click()
  await expect(page.getByRole('button',{name:'Optional dated plan'})).toBeVisible()
  for(let i=0;i<4;i++)await page.getByRole('button',{name:'Next fortnight'}).click()
  const gymMobility=page.getByRole('button',{name:/Wednesday, January 6/})
  await expect(gymMobility.getByText('Gym mobility · repeating')).toBeVisible()
  const fullBody=page.getByRole('button',{name:/Friday, January 8/})
  await expect(fullBody.getByText('Full-body strength · repeating')).toBeVisible()
  await expect(page.getByRole('button',{name:/Sunday, January 10/}).getByText('Mobility · optional · repeating')).toBeVisible()
  await page.getByRole('button',{name:'Coach'}).click()
  await page.getByText('Local rule guidance · legacy', {exact:true}).click()
  const generated=page.waitForResponse(r=>r.url().endsWith('/api/v1/coach/weekly')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'Weekly review'}).click()
  await page.getByRole('button',{name:'Generate weekly review'}).click()
  expect((await generated).ok()).toBe(true)
  await expect(page.getByText('Projected dates · next 14 days')).toBeVisible()
  await expect(page.getByText(/Full-body strength/).first()).toBeVisible()
})

test('demo run history keeps insufficient classification explicit with optional details', async ({page}) => {
  await page.goto('/')
  await page.getByRole('button',{name:'History'}).click()
  const runRow=page.locator('.activity-table tbody tr').filter({has:page.locator('.activity-name', {hasText:'running'})}).first()
  await expect(runRow).toBeVisible()
  await runRow.getByRole('button').click()
  const dialog=page.getByRole('dialog',{name:'Activity detail'})
  await expect(dialog.getByText('Run type unknown · details')).toBeVisible()
  await dialog.getByText('Run type unknown · details').click()
  await expect(dialog.getByText(/insufficient confidence/)).toBeVisible()
  await expect(dialog.getByLabel('Workout label')).toBeVisible()
})

test('manual draft can be accepted and linked to a confirmed actual session', async ({page}) => {
  const profileResponse=await page.request.get('/api/v1/profile')
  const profile=(await profileResponse.json()).data
  expect(profile.anchor_confirmed).toBe(true)
  expect(profile.strength_days_confirmed).toBe(true)
  const anchor=new Date(`${profile.cycle_anchor}T12:00:00`)
  const today=new Date(); today.setHours(12,0,0,0)
  const start=new Date(anchor)
  while(start<today) start.setDate(start.getDate()+14)
  const at=(offset:number)=>{const d=new Date(start);d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
  const startDate=at(0),endDate=at(13)
  await page.goto('/')
  await page.getByRole('button',{name:'Cycle'}).click()
  await page.getByRole('button',{name:'Optional dated plan'}).click()
  const dialog=page.getByRole('dialog',{name:'Draft plan'})
  await dialog.getByLabel('Plan start').fill(startDate)
  await dialog.getByLabel('Plan end').fill(endDate)
  for(const offset of [0,2,4,6,8,10,12]){
    await dialog.getByLabel('Session date').fill(at(offset))
    await dialog.getByLabel('Session',{exact:true}).selectOption('run')
    await dialog.getByRole('button',{name:'Add session'}).click()
  }
  for(const offset of [0,4,7,11]){
    await dialog.getByLabel('Session date').fill(at(offset))
    await dialog.getByLabel('Session',{exact:true}).selectOption('strength')
    await dialog.getByRole('button',{name:'Add session'}).click()
  }
  await dialog.getByRole('button',{name:'Save draft'}).click()
  await expect(dialog).toBeHidden()
  const newest=page.locator('.plan-row').first()
  await expect(newest.getByText('draft',{exact:true})).toBeVisible()
  await newest.getByRole('button',{name:'Accept'}).click()
  await expect(newest.getByText('accepted',{exact:true})).toBeVisible()
  const index=Math.round((start.getTime()-today.getTime())/86_400_000)
  await page.locator('.day-card').nth(index).click()
  const created=page.waitForResponse(response=>response.url().endsWith('/manual-sessions')&&response.request().method()==='POST')
  await page.getByRole('dialog',{name:'Day editor'}).getByRole('button',{name:'Save session'}).click()
  const actualId=(await (await created).json()).data.id
  await expect(page.getByRole('dialog',{name:'Day editor'})).toBeHidden()
  await page.locator('.day-card').nth(index).click()
  const actual=page.getByRole('combobox',{name:'Actual for planned strength'})
  await actual.selectOption(`manual:${actualId}`)
  await expect(page.getByRole('dialog',{name:'Day editor'})).toBeHidden()
  const plans=(await (await page.request.get(`/api/v1/plans?start_date=${startDate}&end_date=${endDate}`)).json()).data.items
  expect(plans.some((p:{status:string;sessions:{kind:string;completion_manual_session_id:string|null}[]})=>p.status==='accepted'&&p.sessions.some(s=>s.kind==='strength'&&s.completion_manual_session_id))).toBe(true)
  await page.locator('.day-card').nth(index).click()
  await page.getByRole('button',{name:'Unlink actual session'}).click()
  await expect(page.getByRole('dialog',{name:'Day editor'})).toBeHidden()
  const after=(await (await page.request.get(`/api/v1/plans?start_date=${startDate}&end_date=${endDate}`)).json()).data.items
  expect(after.find((p:{status:string})=>p.status==='accepted').sessions.some((s:{completion_manual_session_id:string|null})=>s.completion_manual_session_id)).toBe(false)
})

test('Codex weekly plan and daily adjustment appear in the calendar and can be rolled back', async ({page, request}) => {
  const headers = {'X-Local-Request': '1'}
  const root = '/api/v1'
  const key = `browser-agent-${Date.now()}`
  const checkin = await request.post(`${root}/checkins`, {headers, data: {idempotency_key: key, observed_at: new Date().toISOString(), symptoms: 'none', gait: 'normal', feeling: 'usual', note: 'Synthetic browser acceptance fixture for persisted plans.'}})
  expect(checkin.ok()).toBe(true)
  const state = (await (await request.get(`${root}/coach/agent/context?workflow=weekly`)).json()).data
  const review = {actual_vs_plan: 'Synthetic acceptance fixture; unlinked actuals remain unknown.', progression: 'Hold exposure to verify the saved calendar workflow.', recovery: 'No recovery inference is made by this browser fixture.', symptoms: 'Synthetic check-in reports no current symptoms.', strength: 'Keep the confirmed full-body and mobility rotation.', weekly_strategy: 'Preserve the easy running rhythm without catch-up sessions.', uncertainty: ['This is a synthetic browser test, not personalized training advice.'], follow_up: ['Verify the next saved daily decision.'], evidence: []}
  const target = {intent: 'easy', purpose: 'Synthetic browser prescription', prescription: 'Run 20 minutes on familiar flat terrain.', intensity: 'Comfortable conversational effort.', duration_minutes: 20, reason: 'Verify the calendar renders the saved running prescription.'}
  const weekly = await request.post(`${root}/coach/agent/proposals`, {headers, data: {workflow: 'weekly', as_of: state.as_of, evidence_hash: state.evidence_hash, expected_revision_id: state.current_revision_id, idempotency_key: `${key}-weekly`, summary: 'Browser fixture weekly plan', rationale: 'Persist a concrete synthetic plan for calendar acceptance testing.', review, source_ids: ['S001'], sessions: state.context.run_opportunities.map((slot: {date: string}) => ({date: slot.date, kind: 'run', target}))}})
  expect(weekly.ok(), await weekly.text()).toBe(true)
  const weeklyData = (await weekly.json()).data
  expect(weeklyData.revision.workflow).toBe('weekly')
  await page.goto('/')
  await page.getByRole('button', {name: 'Cycle', exact: true}).click()
  const prescribed = page.locator('.day-card').filter({hasText: '20 min'}).first()
  await expect(prescribed).toBeVisible()
  await prescribed.click()
  const dialog = page.getByRole('dialog', {name: 'Day editor'})
  await expect(dialog.getByText(target.reason)).toBeVisible()
  await expect(dialog.getByText('Saved by the Codex research coach').first()).toBeVisible()
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  const dailyState = (await (await request.get(`${root}/coach/agent/context?workflow=daily`)).json()).data
  const daily = await request.post(`${root}/coach/agent/proposals`, {headers, data: {workflow: 'daily', as_of: dailyState.as_of, evidence_hash: dailyState.evidence_hash, expected_revision_id: dailyState.current_revision_id, idempotency_key: `${key}-daily`, summary: 'Browser fixture daily adjustment', rationale: 'Use a concrete shorter exposure to verify the revision workflow.', review, source_ids: ['S001'], sessions: [{date: state.context.run_opportunities[0].date, kind: 'run', target: {...target, duration_minutes: 15, prescription: 'Run 15 minutes on familiar flat terrain.', reason: 'Shorter synthetic session for daily adjustment acceptance testing.'}}]}})
  expect(daily.ok(), await daily.text()).toBe(true)
  await page.getByRole('button', {name: 'Refresh plans', exact: true}).click()
  await expect(page.locator('.day-card').filter({hasText: '15 min'})).toHaveCount(1)
  const savedDecision = page.locator('.agent-revision').filter({has: page.locator('summary', {hasText: 'Browser fixture daily adjustment'})})
  await savedDecision.locator(':scope > summary').click()
  await expect(savedDecision.getByText(/Before: easy · 20 min/)).toBeVisible()
  await expect(savedDecision.getByText(/After: easy · 15 min/)).toBeVisible()
  await savedDecision.getByRole('button', {name: 'Undo this revision'}).click()
  await savedDecision.getByLabel('Reason for undoing').fill('Restore the weekly synthetic fixture prescription.')
  const undo = page.waitForResponse(response => response.url().endsWith('/rollback') && response.request().method() === 'POST')
  await savedDecision.getByRole('button', {name: 'Confirm rollback'}).click()
  expect((await undo).ok()).toBe(true)
  await expect(page.locator('.day-card').filter({hasText: '15 min'})).toHaveCount(0)
  await expect(page.locator('.day-card').filter({hasText: '20 min'})).toHaveCount(7)
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
})
