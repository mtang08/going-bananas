import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CoachAuth, CoachChat, CoachChatSend } from '../src/api/types/coachChat'
import { Coach } from '../src/pages/Coach'

const path = '/api/v1/coach/chat'
const threadId = '11111111-1111-4111-8111-111111111111'
const proposalId = '22222222-2222-4222-8222-222222222222'
const authorization = 'https://auth.openai.com/oauth/authorize?test=1'
const empty = (): CoachChat => ({
  id: null,
  status: 'idle',
  messages: [],
  error: null,
  proposal_id: null,
  proposal_revision: null,
})
const response = (data: unknown) =>
  new Response(JSON.stringify({ schema_version: 'v1', mode: 'test', data }))
let thread: CoachChat
let account: CoachAuth
let proposalStatus: 'pending' | 'accepted'
let writes: { path: string; body: unknown }[]
let dropPost: boolean

beforeEach(() => {
  sessionStorage.clear()
  thread = empty()
  account = { status: 'idle', url: null, error: null }
  proposalStatus = 'pending'
  writes = []
  dropPost = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const endpoint = String(url)
      if (options?.method === 'POST') {
        const body = JSON.parse(String(options.body))
        writes.push({ path: endpoint, body })
        if (endpoint === `${path}/messages`) {
          if (dropPost) throw new TypeError('Network unavailable')
          const message = body as CoachChatSend
          thread = {
            ...thread,
            id: threadId,
            status: 'running',
            error: null,
            messages: [
              ...thread.messages,
              {
                id: message.client_message_id,
                role: 'user',
                text: message.text,
                client_message_id: message.client_message_id,
              },
            ],
          }
        }
        if (endpoint === `${path}/cancel`) thread = { ...thread, status: 'cancelled' }
        if (endpoint === `${path}/new`) thread = empty()
        if (endpoint === `${path}/auth/start`) {
          account = { status: 'waiting', url: authorization, error: null }
        }
        if (endpoint === `${path}/auth/cancel`)
          account = { status: 'cancelled', url: null, error: null }
      }
      if (endpoint.startsWith(`${path}/auth`)) return response(account)
      if (endpoint.startsWith(path)) return response(thread)
      if (endpoint.endsWith(proposalId)) {
        return response({
          status: proposalStatus,
          headline: 'Keep Wednesday easy',
          is_current: true,
          decision_result: proposalStatus === 'accepted' ? { calendar_version: 4 } : null,
        })
      }
      if (endpoint === '/api/v1/calendar') return response({ head: 0 })
      throw new Error(`Unexpected route ${endpoint}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function mount(starter?: 'sunday_review' | 'today_run') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Coach mode="test" starter={starter} />
    </QueryClientProvider>,
  )
}

const box = () => screen.getByRole('textbox', { name: 'Message your coach' })
const send = () => screen.getByRole('button', { name: 'Send message' })

describe('dashboard running coach', () => {
  it('requires an explicit send, streams text, resumes a reload, and links the proposal decision', async () => {
    const first = mount('sunday_review')
    await waitFor(() => expect(send()).toBeEnabled())
    expect(box()).toHaveValue(
      'Let’s do my Sunday review and talk through the next week of training.',
    )
    expect(writes).toEqual([])
    fireEvent.keyDown(box(), { key: 'Enter', shiftKey: true })
    expect(writes).toEqual([])
    fireEvent.keyDown(box(), { key: 'Enter' })
    await screen.findByRole('button', { name: 'Stop reply' })
    expect(writes[0]).toMatchObject({
      path: `${path}/messages`,
      body: { thread_id: null, intent: 'sunday_review' },
    })
    thread.messages.push({
      id: 'coach-1',
      role: 'assistant',
      text: 'From your recent runs,',
      client_message_id: null,
    })
    await screen.findByText('From your recent runs,')
    first.unmount()
    const second = mount()
    expect(await screen.findByText('From your recent runs,')).toBeInTheDocument()
    expect(writes).toHaveLength(1)
    thread.messages[1].text = 'From your recent runs, Wednesday should be easy.'
    thread.status = 'idle'
    await screen.findByText('From your recent runs, Wednesday should be easy.')

    fireEvent.change(box(), { target: { value: 'Sounds good. Save it for review.' } })
    fireEvent.click(send())
    await screen.findByRole('button', { name: 'Stop reply' })
    expect(writes[1]).toMatchObject({
      path: `${path}/messages`,
      body: { thread_id: threadId, text: 'Sounds good. Save it for review.' },
    })
    thread.status = 'idle'
    thread.proposal_id = proposalId
    thread.proposal_revision = 1
    expect(await screen.findByRole('link', { name: 'Review proposal' })).toHaveAttribute(
      'href',
      `#proposal/${proposalId}`,
    )
    expect(await screen.findByText('Pending review')).toBeInTheDocument()
    second.unmount()
    proposalStatus = 'accepted'
    mount()
    expect(await screen.findByText('Applied in calendar version 4.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View proposal' })).toHaveAttribute(
      'href',
      `#proposal/${proposalId}`,
    )
    expect(writes).toHaveLength(2)
  })

  it('keeps a disconnected draft and reuses its request ID, then lets the athlete stop the reply', async () => {
    mount()
    fireEvent.change(box(), { target: { value: 'I need to move my long run.' } })
    await waitFor(() => expect(send()).toBeEnabled())
    dropPost = true
    fireEvent.click(send())
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the local server')
    expect(box()).toHaveValue('I need to move my long run.')
    dropPost = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry sending' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Stop reply' }))
    await screen.findByText('Reply stopped.')
    expect(writes[1]).toEqual(writes[0])
    expect(writes[2]).toEqual({ path: `${path}/cancel`, body: { thread_id: threadId } })
    expect(screen.getByText('I need to move my long run.')).toBeInTheDocument()
  })

  it('recovers a waiting browser sign-in after reload and retains the original message', async () => {
    thread = {
      ...empty(),
      id: threadId,
      status: 'failed',
      error: { code: 'auth_required', message: 'The coach needs ChatGPT sign-in.' },
      messages: [
        { id: 'user-1', role: 'user', text: 'Review my week, please.', client_message_id: null },
      ],
    }
    const first = mount()
    await screen.findByText('The coach needs ChatGPT sign-in.')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with ChatGPT' }))
    expect(await screen.findByRole('link', { name: 'Open ChatGPT sign-in' })).toHaveAttribute(
      'href',
      authorization,
    )
    first.unmount()
    mount()
    expect(await screen.findByRole('link', { name: 'Open ChatGPT sign-in' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    expect(writes).toHaveLength(1)
    account = { status: 'signed_in', url: null, error: null }
    await screen.findByText('You’re signed in. You can send your last message again.', undefined, {
      timeout: 2500,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Use last message again' }))
    expect(box()).toHaveValue('Review my week, please.')
    expect(writes).toHaveLength(1)
  })

  it('asks before clearing an existing conversation and prefills the fresh review', async () => {
    thread = {
      ...empty(),
      id: threadId,
      messages: [
        { id: 'user-1', role: 'user', text: 'An earlier review.', client_message_id: null },
      ],
    }
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'New Sunday review' }))
    expect(screen.getByRole('dialog', { name: 'Start a new Sunday review?' })).toBeInTheDocument()
    expect(writes).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Keep talking' }))
    expect(screen.getByText('An earlier review.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'New Sunday review' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start new review' }))
    await waitFor(() => expect(screen.queryByText('An earlier review.')).not.toBeInTheDocument())
    expect(box()).toHaveValue(
      'Let’s do my Sunday review and talk through the next week of training.',
    )
    expect(writes).toEqual([{ path: `${path}/new`, body: { thread_id: threadId } }])
  })
})
