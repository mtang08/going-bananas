// Driven by scripts/rewrite/proposal-home.mjs against disposable HTTP listeners.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { qk } from '../src/api/queryKeys'

const state = process.env.PROPOSAL_HOME_STATE

it.skipIf(!state)(`renders Home with the ${state} Go proposal list over HTTP`, async () => {
  const nativeFetch = globalThis.fetch
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal('fetch', (path: string, init?: RequestInit) => {
    expect(path).toMatch(/^\/api\/v1\//)
    expect(init?.method ?? 'GET').toBe('GET')
    return nativeFetch(new URL(path, process.env.PROPOSAL_HOME_ORIGIN), init)
  })
  try {
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    )
    await screen.findByText('No calendar yet.')
    await waitFor(() =>
      expect(client.getQueryState(qk.proposalsOpen)?.status).toBe(
        state === 'failed' ? 'error' : 'success',
      ),
    )
    const draftLink = screen.queryByRole('link', { name: 'Review' })
    if (state === 'open') {
      expect(draftLink).toHaveAttribute('href', '#proposal/00000000-0000-0000-0000-000000000033')
      const row = draftLink!.closest<HTMLElement>('[data-kind="proposal"]')!
      expect(within(row).getByText('Pending')).toBeVisible()
      expect(row).toHaveTextContent('2 changes')
    } else {
      expect(draftLink).toBeNull()
    }
    if (state === 'failed') {
      expect(await screen.findByText(/Could not load proposals/)).toBeVisible()
    } else {
      expect(screen.queryByText(/Could not load proposals/)).toBeNull()
    }
  } finally {
    cleanup()
    client.clear()
    vi.unstubAllGlobals()
  }
})
