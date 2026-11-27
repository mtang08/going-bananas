import { expect, test } from '../frontend/node_modules/@playwright/test'

const local = { 'X-Local-Request': '1', 'Content-Type': 'application/json' }
const fixture = '/api/v1/__test/coach'

test('signs in, resumes a streamed Sunday review, and accepts its actual pending proposal', async ({
  page,
  request,
}) => {
  test.skip(
    process.env.GB_COACH_BROWSER_TEST !== '1',
    'Requires the isolated scripted coach server',
  )

  const profile = await request.get('/api/v1/profile')
  expect(profile.ok()).toBe(true)
  expect((await profile.json()).mode).toBe('demo')
  const baseline = await request.get('/api/v1/calendar')
  expect(baseline.ok()).toBe(true)
  const { head } = (await baseline.json()).data
  const gatewayState = async () => {
    const state = await request.get(`${fixture}/state`)
    expect(state.ok()).toBe(true)
    return state.json()
  }

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('link', { name: 'Start Sunday review' }).click()
  const compose = page.getByRole('textbox', { name: 'Message your coach' })
  await expect(compose).toHaveValue(/Sunday review/)
  expect(await gatewayState()).toEqual({ turns: 0, resumes: 0 })

  await page.getByRole('button', { name: 'Sign in with ChatGPT' }).click()
  await expect(page.getByRole('link', { name: 'Open ChatGPT sign-in' })).toHaveAttribute(
    'href',
    /^https:\/\/auth\.openai\.com\/oauth\/authorize\?/,
  )
  await page.reload()
  await expect(page.getByRole('link', { name: 'Open ChatGPT sign-in' })).toBeVisible()
  await expect(compose).toHaveValue(/Sunday review/)
  expect((await request.post(`${fixture}/sign-in`, { headers: local, data: {} })).ok()).toBe(true)
  await expect(page.getByRole('link', { name: 'Open ChatGPT sign-in' })).toHaveCount(0)
  expect(await gatewayState()).toEqual({ turns: 0, resumes: 0 })

  const opening = `${await compose.inputValue()} Hold this turn for the synthetic browser check.`
  await compose.fill(opening)
  await compose.press('Enter')
  await expect(page.getByText('Checking the training log', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Stop reply' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByText('Checking the training log', { exact: true })).toBeVisible()
  await expect(page.getByText(opening, { exact: true })).toBeVisible()
  expect(await gatewayState()).toEqual({ turns: 1, resumes: 0 })
  await expect(compose).toHaveValue('')
  const bodyWidth = await page.locator('body').evaluate((body) => body.scrollWidth)
  expect(bodyWidth).toBeLessThanOrEqual(390)

  expect((await request.post(`${fixture}/release`, { headers: local, data: {} })).ok()).toBe(true)
  await expect(page.getByText(/I would extend the next easy run/)).toBeVisible()
  await page.goto('/#home')
  await page.getByRole('link', { name: 'Continue review' }).click()
  await expect(page.getByText(/I would extend the next easy run/)).toBeVisible()
  await compose.fill('Looks good. Save it as a pending proposal.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Pending review', { exact: true })).toBeVisible()
  expect(await gatewayState()).toEqual({ turns: 2, resumes: 1 })
  expect((await (await request.get('/api/v1/calendar')).json()).data.head).toBe(head)

  await page.getByRole('link', { name: 'Review proposal' }).click()
  await expect(page.getByRole('heading', { name: 'Review proposal' })).toBeVisible()
  await expect(page.getByText('Add five easy minutes').first()).toBeVisible()
  await page.getByRole('button', { name: 'Accept selected' }).click()
  await expect(page.getByText(`Accepted — calendar version ${head + 1}`)).toBeVisible()
  await page.getByRole('link', { name: 'Back to coach' }).click()
  await expect(page.getByText(`Applied in calendar version ${head + 1}.`)).toBeVisible()

  await page.getByRole('button', { name: 'New Sunday review' }).click()
  await page.getByRole('button', { name: 'Start new review' }).click()
  await expect(compose).toHaveValue(/Sunday review/)
  await expect(page.getByText(opening, { exact: true })).toHaveCount(0)
  expect(await gatewayState()).toEqual({ turns: 2, resumes: 1 })
})
