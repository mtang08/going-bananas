// The differential runner supplies a disposable DB and one loopback Vite origin.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { Goals } from '../src/pages/settings/Goals'

const text = process.env.GOAL_SETTINGS_FIXTURE

it.skipIf(!text)(
  'creates a goal, edits it in Settings, and displays the refreshed list',
  async () => {
    const origin = process.env.PROPOSAL_HOME_ORIGIN!
    const nativeFetch = globalThis.fetch
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.stubGlobal('fetch', (path: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      if (init?.method && init.method !== 'GET') headers.set('Origin', origin)
      return nativeFetch(new URL(path, origin), { ...init, headers })
    })
    try {
      render(
        <QueryClientProvider client={client}>
          <Goals />
        </QueryClientProvider>,
      )
      const input = await screen.findByLabelText('Goal')
      fireEvent.change(input, { target: { value: text } })
      fireEvent.click(screen.getByRole('button', { name: 'Add goal' }))
      const row = await screen.findByText((content) => content.startsWith(text + ' ·'))
      fireEvent.click(within(row).getByRole('button', { name: 'Edit' }))
      fireEvent.change(input, { target: { value: 'Updated ' + text } })
      fireEvent.click(screen.getByRole('button', { name: 'Save goal' }))
      expect(
        await screen.findByText((content) => content.startsWith('Updated ' + text + ' ·')),
      ).toBeVisible()
    } finally {
      cleanup()
      client.clear()
      vi.unstubAllGlobals()
    }
  },
)
