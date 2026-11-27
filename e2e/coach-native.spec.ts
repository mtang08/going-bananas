import { expect, test } from '../frontend/node_modules/@playwright/test'

test('discusses, saves, reloads and accepts a pending draft through the native dashboard', async ({
  page,
  request,
}) => {
  test.skip(
    process.env.GB_NATIVE_COACH_BROWSER !== '1',
    'Requires the isolated native coach fixture',
  )
  test.setTimeout(90_000)
  const calendarHead = async () => {
    const response = await request.get('/api/v1/calendar/versions')
    expect(response.ok()).toBe(true)
    const envelope = await response.json()
    expect(envelope.mode).toBe('test')
    return envelope.data.items[0].number
  }
  const head = await calendarHead()
  await page.goto('/')
  await page.getByRole('link', { name: 'Start Sunday review' }).click()
  const compose = page.getByRole('textbox', { name: 'Message your coach' })
  await compose.fill('Could we add five minutes to my next easy run?')
  await compose.press('Enter')
  await expect(page.getByText(/We could extend the next easy run/)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('link', { name: 'Review proposal' })).toHaveCount(0)
  await page.reload()
  await expect(page.getByText(/We could extend the next easy run/)).toBeVisible()
  await compose.fill('Yes, please save the 35-minute easy run for my review.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Pending review', { exact: true })).toBeVisible({ timeout: 20_000 })
  expect(await calendarHead()).toBe(head)
  await page.getByRole('link', { name: 'Review proposal' }).click()
  await expect(page.getByText('Add five easy minutes').first()).toBeVisible()
  await page.getByRole('button', { name: 'Accept selected' }).click()
  await expect(page.getByText(`Accepted — calendar version ${head + 1}`)).toBeVisible()
  await page.getByRole('link', { name: 'Back to coach' }).click()
  await expect(page.getByText(`Applied in calendar version ${head + 1}.`)).toBeVisible()
  expect(await calendarHead()).toBe(head + 1)
})
