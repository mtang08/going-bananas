import { expect, test } from '../frontend/node_modules/@playwright/test'
import { addDays } from '../frontend/src/lib/format'

test('record an open break, confirm availability, and end it without rewriting workouts', async ({
  page,
  request,
}) => {
  const path = '/api/v1/running-interruption'
  const read = async (url: string) => {
    const response = await request.get(url)
    expect(response.ok()).toBe(true)
    const envelope = await response.json()
    expect(envelope.mode).toBe('demo')
    return envelope.data
  }
  const initial = await read(path)
  expect(initial.interruption).toBeNull()
  const calendar = '/api/v1/calendar'
  const before = await read(calendar)
  const expectCalendarUnchanged = async () => {
    const after = await read(calendar)
    expect(after.head).toBe(before.head)
    expect(after.sessions).toEqual(before.sessions)
    expect(after.completions).toEqual(before.completions)
  }
  await page.goto('/#home')
  const record = page.getByRole('button', {
    name: 'Record a running interruption',
  })
  await record.click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Reason', exact: true }).selectOption('illness')
  await dialog.getByRole('combobox', { name: 'Return timing', exact: true }).selectOption('open')
  await dialog.getByLabel('Reassess on').fill(initial.today)
  await dialog.getByRole('button', { name: 'Save interruption' }).click()
  const episode = page.getByRole('region', { name: 'Running interruption' })
  await expect(episode).toContainText('Review due')
  await expect(episode).toContainText('Return date open')
  const paused = await read(path)
  expect(paused.first_run).toBeNull()
  expect(paused.recorded_return).toBeNull()
  await expectCalendarUnchanged()
  await page.reload()
  await episode.getByRole('button', { name: 'Edit interruption' }).click()
  await dialog.getByRole('combobox', { name: 'Return timing', exact: true }).selectOption('dated')
  const available = addDays(initial.today, 3)
  await dialog.getByLabel('First day available').fill(available)
  await dialog.getByRole('button', { name: 'Save interruption' }).click()
  await expect(episode).toContainText('Next availability')
  const confirmed = await read(path)
  expect(confirmed.interruption.return_on).toBe(available)
  expect(confirmed.recorded_return).toBeNull()
  await expectCalendarUnchanged()
  if (confirmed.first_run) {
    expect(confirmed.first_run.local_date >= available).toBe(true)
    await expect(
      episode.locator('a[href="#calendar/' + confirmed.first_run.local_date + '"]'),
    ).toBeVisible()
  } else {
    await expect(episode).toContainText(confirmed.review_reason)
  }
  await episode.getByRole('button', { name: 'End interruption' }).click()
  await dialog.getByRole('button', { name: 'Confirm end' }).click()
  await expect(record).toBeVisible()
  expect((await read(path)).interruption).toBeNull()
  await expectCalendarUnchanged()
})
