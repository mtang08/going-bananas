import { expect, test } from '../frontend/node_modules/@playwright/test'

test.beforeAll(async ({ request }) => {
  const response = await request.get('http://127.0.0.1:5173/api/v1/profile')
  const envelope = await response.json()
  expect(envelope.mode).toBe('demo')
  const p = envelope.data
  const configured = await request.put('http://127.0.0.1:5173/api/v1/profile', {
    headers: { 'X-Local-Request': '1' },
    data: { ...p, expected_version: p.version, timezone: 'America/New_York',
      cycle_anchor: '2026-11-02', anchor_confirmed: true,
      strength_days_confirmed: true, scheduled_strength_days: [0, 4] },
  })
  expect(configured.ok()).toBe(true)
})

test.beforeEach(async ({request}) => {
  const response=await request.get('http://127.0.0.1:5173/api/v1/health/live')
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
  const plansBefore=await (await page.request.get('http://127.0.0.1:5173/api/v1/plans')).json()
  await page.goto('/')
  await page.getByRole('button',{name:'Coach',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Train with context.'})).toBeVisible()
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
  const plansAfter=await (await page.request.get('http://127.0.0.1:5173/api/v1/plans')).json()
  expect(plansAfter.data.items).toEqual(plansBefore.data.items)
})

test('demo Strength browses imported years and recorded sets on mobile', async ({page}) => {
  await page.setViewportSize({width:390,height:844})
  await page.goto('/')
  await page.getByRole('button',{name:'Open menu'}).click()
  await page.getByRole('button',{name:'Strength'}).click()
  await expect(page.getByRole('heading',{name:'Strength history.'})).toBeVisible()
  const years=(await (await page.request.get('http://127.0.0.1:5173/api/v1/strength/years')).json()).data.years
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

test('manual draft can be accepted and linked to a confirmed actual session', async ({page}) => {
  const profileResponse=await page.request.get('http://127.0.0.1:5173/api/v1/profile')
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
  await page.getByRole('button',{name:'Draft plan'}).click()
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
  const plans=(await (await page.request.get(`http://127.0.0.1:5173/api/v1/plans?start_date=${startDate}&end_date=${endDate}`)).json()).data.items
  expect(plans.some((p:{status:string;sessions:{kind:string;completion_manual_session_id:string|null}[]})=>p.status==='accepted'&&p.sessions.some(s=>s.kind==='strength'&&s.completion_manual_session_id))).toBe(true)
  await page.locator('.day-card').nth(index).click()
  await page.getByRole('button',{name:'Unlink actual session'}).click()
  await expect(page.getByRole('dialog',{name:'Day editor'})).toBeHidden()
  const after=(await (await page.request.get(`http://127.0.0.1:5173/api/v1/plans?start_date=${startDate}&end_date=${endDate}`)).json()).data.items
  expect(after.find((p:{status:string})=>p.status==='accepted').sessions.some((s:{completion_manual_session_id:string|null})=>s.completion_manual_session_id)).toBe(false)
})
