import { expect, test, type APIResponse } from '../frontend/node_modules/@playwright/test'
import type { APIRequestContext, Locator } from '../frontend/node_modules/@playwright/test'
import type { WeeklyDigest } from '../frontend/src/api/types/calendar'

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
})

async function weeks(request: APIRequestContext): Promise<[WeeklyDigest, WeeklyDigest]> {
  const path = '/api/v1/calendar/weekly-digest'
  const current = await request.get(path)
  expect(current.ok()).toBe(true)
  const week = await data(current)
  const previous = await request.get(`${path}?week_start=${day(week.week_start, -7)}`)
  expect(previous.ok()).toBe(true)
  return [week, await data(previous)]
}

function expectedSessionsLine(week: WeeklyDigest): string {
  const sessions = week.totals.sessions
  return week.days_elapsed < 7
    ? `${sessions.done} of ${sessions.planned_to_date} sessions done so far · ${sessions.planned} planned this week`
    : `${sessions.done} of ${sessions.planned} sessions done`
}

async function expectWeek(card: Locator, week: WeeklyDigest) {
  const { sessions, key_sessions, time, run_distance } = week.totals
  await expect(card).toContainText(expectedSessionsLine(week))
  await expect(card.getByTestId('digest-key-session')).toHaveCount(key_sessions.planned)

  for (const [outcome, label] of [
    ['partial', 'partial'], ['modified', 'modified'], ['missed', 'missed'], ['not_recorded', 'not recorded'],
  ] as const) {
    const count = sessions.by_outcome[outcome]
    if (count > 0) await expect(card.getByText(new RegExp(`\\b${count} ${label}\\b`))).toBeVisible()
    else await expect(card.getByText(new RegExp(`\\b\\d+ ${label}\\b`))).toHaveCount(0)
  }

  const unknowns = [
    time.planned_unknown > 0 && `${time.planned_unknown} planned without a duration`,
    time.actual_unknown > 0 && `${time.actual_unknown} recorded without a duration`,
    run_distance.planned_unknown > 0 && `${run_distance.planned_unknown} planned runs without a distance`,
    run_distance.actual_unknown > 0 && `${run_distance.actual_unknown} recorded runs without a distance`,
    !week.activity_coverage_complete && 'activity history may be incomplete',
  ].filter(Boolean)
  if (unknowns.length > 0) {
    await expect(card).toContainText(`Some amounts are unknown: ${unknowns.join('; ')}`)
  } else {
    await expect(card).not.toContainText('Some amounts are unknown')
  }
  await expect(card).not.toContainText(/NaN|undefined|null/)

  const unplanned = card.getByTestId('digest-unplanned')
  if (sessions.unplanned > 0) {
    await expect(unplanned).toBeVisible()
    await expect(unplanned).toContainText(new RegExp(`Unplanned: ${sessions.unplanned}\\b`))
  } else {
    await expect(unplanned).toHaveCount(0)
  }
}

test('wd: card matches the API for this week and last week', async ({ page, request }) => {
  const [current, previous] = await weeks(request)
  expect(current.schema).toBe('weekly_digest.v1')
  expect(previous.totals.sessions.planned, 'Demo seed gap: no planned sessions last week').toBeGreaterThan(0)
  expect(previous.totals.sessions.done, 'Demo seed gap: no completed sessions last week').toBeGreaterThan(0)
  expect(previous.days_elapsed).toBe(7)

  await page.goto('/')
  const card = page.getByTestId('weekly-digest')
  await expect(card).toBeVisible()
  await expect(card).toContainText('Planned vs done')
  await expect(card.getByRole('button', { name: 'This week' })).toHaveAttribute('aria-pressed', 'true')
  await expectWeek(card, current)

  const lastWeek = card.getByRole('button', { name: 'Last week' })
  await lastWeek.click()
  await expect(lastWeek).toHaveAttribute('aria-pressed', 'true')
  await expectWeek(card, previous)
})

test('wd: open run from a key session', async ({ page, request }) => {
  const [current, previous] = await weeks(request)
  const hasRun = (row: WeeklyDigest['sessions'][number]) => row.key && row.actual?.subject === 'activity'
  const week = [current, previous].find((digest) => digest.sessions.some(hasRun))
  expect(week, 'Demo seed gap: neither week has a key session linked to a run').toBeDefined()
  const keyRows = week!.sessions.filter((row) => row.key)
  const index = keyRows.findIndex(hasRun)
  const activityId = keyRows[index].actual!.id

  await page.goto('/')
  const card = page.getByTestId('weekly-digest')
  if (week === previous) {
    const lastWeek = card.getByRole('button', { name: 'Last week' })
    await lastWeek.click()
    await expect(lastWeek).toHaveAttribute('aria-pressed', 'true')
  }
  await card.getByTestId('digest-key-session').nth(index).getByRole('link', { name: 'Open run' }).click()
  await expect(page).toHaveURL((url) => url.hash === `#activity/${activityId}`)
  await expect(page.getByRole('link', { name: 'Back to Home' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})
