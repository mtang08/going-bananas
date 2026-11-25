import { expect, test } from '../frontend/node_modules/@playwright/test'

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

for (const pain of [0, 3]) {
  test(`offline morning, pain ${pain}: reopen, retry a lost receipt, and sync once`, async ({
    page, context, request,
  }) => {
    const health = await request.get('/api/v1/health/ready')
    expect(health.ok()).toBe(true)
    expect(['demo', 'test']).toContain((await health.json()).mode)

    // Drop the acknowledgment only after an actual successful write. This also
    // works in WebKit where service-worker traffic can bypass route interception.
    await context.addInitScript(() => {
      const fetchFromServer = window.fetch.bind(window)
      window.fetch = async (...args) => {
        const response = await fetchFromServer(...args)
        if (typeof args[0] === 'string' && args[0].startsWith('/api/v1/phone/checkins/') && response.ok) {
          const receipt = (await response.clone().json()).data
          const attempts = JSON.parse(localStorage.getItem('test-attempts') || '[]')
          attempts.push({ id: receipt.id, observed: JSON.parse(String(args[1]?.body)).observed_at })
          localStorage.setItem('test-attempts', JSON.stringify(attempts))
          if (!localStorage.getItem('test-deliver-receipt')) throw new TypeError('Connection lost')
        }
        return response
      }
    })
    await page.goto('/phone/')
    await expect(page.getByText('Ready offline', { exact: true })).toBeVisible()
    await page.close()
    await context.setOffline(true)
    const morning = await context.newPage()
    await morning.goto('/phone/')
    const score = pain === 0 ? '0 · No pain' : '3 · Mild'
    await morning.getByRole('button', { name: score, exact: true }).click()
    if (pain > 0) await morning.getByRole('button', { name: 'Eased', exact: true }).click()
    await expect(morning.getByRole('heading', { name: 'Saved on iPhone' })).toBeVisible()
    await morning.close()

    const reopened = await context.newPage()
    await reopened.goto('/phone/')
    await expect(reopened.getByRole('heading', { name: 'Saved on iPhone' })).toBeVisible()
    await context.setOffline(false)
    // A fresh open also retries when the phone was online while the Mac slept.
    await reopened.close()
    const online = await context.newPage()
    await online.goto('/phone/')
    const attempts = (): Promise<{id: string; observed: string}[]> =>
      online.evaluate(() => JSON.parse(localStorage.getItem('test-attempts') || '[]'))
    await expect.poll(async () => (await attempts()).length).toBeGreaterThan(0)
    await expect(online.getByRole('heading', { name: 'Saved on iPhone' })).toBeVisible()
    await online.evaluate(() => localStorage.setItem('test-deliver-receipt', '1'))
    await online.getByRole('button', { name: 'Retry sync' }).click()
    await expect(online.getByRole('heading', { name: 'Synced' })).toBeVisible()
    const submitted = await attempts()
    expect(submitted.length).toBeGreaterThanOrEqual(2)
    expect(submitted.every(submission =>
      submission.id === submitted[0].id && submission.observed === submitted[0].observed
    )).toBe(true)

    const history = await request.get('/api/v1/v2/checkins')
    expect(history.ok()).toBe(true)
    const rows = (await history.json()).data.items.filter((item: { idempotency_key: string }) =>
      item.idempotency_key.includes(submitted[0].id))
    expect(rows).toHaveLength(1)
    expect(Date.parse(rows[0].observed_at)).toBe(Date.parse(submitted[0].observed))
    expect(rows[0].activity_id).toBe(null)
  })
}
