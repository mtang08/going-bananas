import { expect, test, type APIResponse } from '../frontend/node_modules/@playwright/test'

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
})

test('ti: workout progression in trends', async ({ page }) => {
  await page.goto('/#trends')
  const card = page.getByTestId('trend-workout-progression')
  await expect(card).toBeVisible()
  const picker = card.getByRole('combobox', {name: /Workout/})
  await expect(picker.locator('option:checked')).toContainText('4 × 5:00 · 3/4 assessed')
  await expect(card.getByTestId('progression-row')).toHaveCount(4)
  await expect(card.getByTestId('progression-row').filter({hasText: 'Partial'})).toHaveCount(1)
  await expect(card.getByTestId('progression-row').filter({hasText: 'Not assessable: Watch workout does not match the plan'})).toHaveCount(1)
  const other = await picker.locator('option').filter({hasText: '5 × 4:00'}).getAttribute('value')
  expect(other).toBeTruthy()
  await picker.selectOption(other!)
  await expect(card.getByTestId('progression-row')).toHaveCount(1)
  await card.getByRole('button', {name: 'Same session type'}).click()
  await expect(picker.locator('option:checked')).toContainText('Threshold intervals')
  await expect(card.getByTestId('progression-row')).toHaveCount(5)
  await expect(card.getByRole('columnheader', {name: 'Work steps'})).toBeVisible()
})

test('ti: activity compares with earlier sessions', async ({ page, request }) => {
  const current = await data(await request.get('/api/v1/calendar'))
  const calendar = await data(await request.get(`/api/v1/calendar?start=${day(current.today,-14)}&end=${current.today}`))
  const session = calendar.sessions.find((s: {local_date:string;recipe_id:string}) => s.local_date === day(current.today,-6) && s.recipe_id === 'REC003')
  expect(session).toBeTruthy()
  const completion = calendar.completions.find((c: {session_uid:string}) => c.session_uid === session.session_uid)
  expect(completion.activity_id).toBeTruthy()
  await page.goto(`/#activity/${completion.activity_id}`)
  await expect(page.getByRole('heading', {name: 'This workout over time'})).toBeVisible()
  const card = page.getByTestId('activity-workout-history')
  await expect(card.getByTestId('progression-row')).toHaveCount(4)
  await expect(card.getByTestId('progression-row').first()).toContainText('(this run)')
  await expect(card.getByRole('link', {name: 'See the full history in Trends'})).toHaveAttribute('href', '#trends')
})

test('ti: aerobic efficiency in trends', async ({ page }) => {
  await page.goto('/#trends')
  const card = page.getByTestId('trend-aerobic')
  await expect(card).toBeVisible()
  await expect(card.locator('xpath=ancestor::*[@data-testid="trends-not-assessable"]')).toHaveCount(0)
  await expect(card.getByText(/28 days: median \d\.\d\d m\/beat over 7 runs · \+\d\.\d% early → late/)).toBeVisible()
  await expect(card.getByRole('img', {name: 'Metres per heartbeat on steady runs, last 84 days'})).toBeVisible()
  await expect(card.getByText(/Descriptive only/)).toBeVisible()
})

test('ti: activity aerobic panel', async ({ page, request }) => {
  const current = await data(await request.get('/api/v1/calendar'))
  const calendar = await data(await request.get(`/api/v1/calendar?start=${day(current.today,-2)}&end=${current.today}`))
  const session = calendar.sessions.find((s: {local_date:string;recipe_id:string}) => s.local_date === day(current.today,-2) && s.recipe_id === 'REC002')
  expect(session).toBeTruthy()
  const completion = calendar.completions.find((c: {session_uid:string}) => c.session_uid === session.session_uid)
  expect(completion.activity_id).toBeTruthy()
  await page.goto(`/#activity/${completion.activity_id}`)
  await page.getByText('Aerobic efficiency', {exact: true}).click()
  await expect(page.getByText(/m per heartbeat/)).toBeVisible()
  await expect(page.getByText(/Heart-rate drift \+\d\.\d%/)).toBeVisible()

  const date = day(current.today, -20)
  const activities = await data(await request.get(`/api/v1/activities?start_date=${date}&end_date=${date}`))
  const treadmill = activities.items.find((activity: {sport:string}) => activity.sport === 'treadmill_running')
  expect(treadmill).toBeTruthy()
  await page.goto(`/#activity/${treadmill.id}`)
  await page.getByText('Aerobic efficiency', {exact: true}).click()
  await expect(page.getByText('Not assessed: No pace data')).toBeVisible()
})
