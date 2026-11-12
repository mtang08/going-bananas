import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from '../src/App'
import { Coach } from '../src/pages/Coach'
import { AgentPlanHistory } from '../src/PlanViews'
import { localDate, type AgentRevision } from '../src/api'

vi.mock('recharts', () => ({ResponsiveContainer: () => null, BarChart: () => null, LineChart: () => null, Bar: () => null, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null}))
const today = localDate()
const target = {intent: 'easy', purpose: 'Hold recent tolerated exposure', prescription: 'Continuous run on a flat route', intensity: 'Conversational effort, RPE 3', duration_minutes: 32, distance_km: 5, reason: 'Hold steady while the delayed response is unknown.', provenance: 'codex_skill.v1', steps: ['Walk for 5 minutes afterward']}
const revision: AgentRevision = {id: 'revision-2', workflow: 'daily', as_of: today, created_at: `${today}T12:00:00Z`, summary: 'Hold the easy run', rationale: 'A fresh check-in supports the existing exposure.', diff: [{date: today, kind: 'run', before: {duration_minutes: 40}, after: {...target, intent: 'easy'}, reason: 'Reduce time after reported fatigue.'}], plan_id: 'plan-2', parent_revision_id: 'revision-1', status: 'applied', source_ids: ['E001']}
let calls: {url: string; method: string; body: unknown}[]
let failRollback: boolean
let confirmed: boolean
let rest: boolean
beforeEach(() => {
  calls = []; failRollback = false; confirmed = false; rest = false; localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = String(input), method = options?.method || 'GET', body = options?.body ? JSON.parse(String(options.body)) : null
    calls.push({url, method, body})
    if (url.endsWith('/rollback') && failRollback) return {ok: false, status: 409, json: async () => ({error: {code: 'version_conflict', message: 'Plan changed; refresh before undoing.'}})} as Response
    const data = url.includes('/rollback') ? {revision: {...revision, id: 'revision-3'}} : url.includes('/coach/agent/revisions') ? {current_revision_id: confirmed ? 'confirmation-3' : revision.id, revertible_revision_id: revision.id, items: [...(confirmed ? [{...revision, id: 'confirmation-3', summary: 'Today confirmed', diff: []}] : []), revision, {...revision, id: 'revision-1', summary: 'Earlier weekly plan', workflow: 'weekly'}]} : url.includes('/plans') ? {items: [{id: 'plan-2', status: 'accepted', version: 1, start_date: today, end_date: today, sessions: [{id: 'session-2', date: today, kind: 'run', target: rest ? {...target, intent: 'rest', duration_minutes: undefined, distance_km: undefined, prescription: 'Rest from running today'} : target}]}], opportunities: [{date: today, intent: 'quality', conditional: true}], recurring_sessions: [{date: today, kind: 'strength', optional: false}], unscheduled: false} : url.includes('/profile') ? {version: 1, anchor_confirmed: true, strength_days_confirmed: true, cycle_anchor: today} : url.includes('/coach/daily') ? {item: null, knowledge: {available: true}} : {items: []}
    return {ok: true, status: 200, json: async () => ({schema_version: 'v1', data_revision: 1, mode: 'demo', data})} as Response
  }))
})
afterEach(() => {cleanup(); vi.unstubAllGlobals()})
function mount(view: React.ReactNode) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  return {client, ...render(<QueryClientProvider client={client}>{view}</QueryClientProvider>)}
}

describe('persisted research-coach plans', () => {
  it('explains skill invocation and keeps legacy rules separate without generating advice', async () => {
    mount(<Coach onCheckin={() => {}} onSetup={() => {}}/>)
    expect(screen.getByText(/Review my recent training and plan the next 14 days/)).toBeInTheDocument()
    await screen.findByText(/Hold the easy run/)
    expect(screen.getByText('Local rule guidance · legacy').parentElement).not.toHaveAttribute('open')
    expect(screen.queryByRole('button', {name: 'Generate daily guidance'})).not.toBeInTheDocument()
    expect(calls.every(call => call.method === 'GET')).toBe(true)
  })

  it('renders authoritative duration, volume and effort while preserving same-day strength, then shows rationale and links actuals', async () => {
    mount(<App/>)
    fireEvent.click(screen.getByRole('button', {name: 'Cycle'}))
    const day = await screen.findByRole('button', {name: /32 min · 5 km/})
    expect(within(day).getByText('Full-body strength · repeating')).toBeInTheDocument()
    expect(within(day).getByText('Conversational effort, RPE 3')).toBeInTheDocument()
    expect(within(day).queryByText('quality run candidate')).not.toBeInTheDocument()
    fireEvent.click(day)
    const dialog = screen.getByRole('dialog', {name: 'Day editor'})
    expect(within(dialog).getByText(target.reason)).toBeInTheDocument()
    expect(within(dialog).getByText(target.purpose)).toBeInTheDocument()
    expect(within(dialog).getByText(target.steps[0])).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Actual for planned run')).toBeInTheDocument()
  })

  it('shows prescription changes and only undoes the current revision with a reason and concurrency guard', async () => {
    const {client} = mount(<AgentPlanHistory/>)
    await screen.findByText(/Hold the easy run/)
    fireEvent.click(screen.getByText(/Hold the easy run/))
    fireEvent.click(screen.getByText(/Earlier weekly plan/))
    expect(screen.getAllByText('Before: 40 min')).toHaveLength(2)
    expect(screen.getAllByRole('button', {name: 'Undo this revision'})).toHaveLength(1)
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    fireEvent.click(screen.getByRole('button', {name: 'Undo this revision'}))
    expect(screen.getByRole('button', {name: 'Confirm rollback'})).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Reason for undoing'), {target: {value: 'Return to the prior agreed session.'}})
    fireEvent.click(screen.getByRole('button', {name: 'Confirm rollback'}))
    await waitFor(() => expect(calls.find(call => call.method === 'POST')?.body).toEqual({expected_revision_id: 'revision-2', reason: 'Return to the prior agreed session.'}))
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({queryKey: ['plans']}))
  })

  it('shows a stale rollback failure without claiming the calendar was restored', async () => {
    failRollback = true
    mount(<AgentPlanHistory/>)
    fireEvent.click(await screen.findByText(/Hold the easy run/))
    fireEvent.click(screen.getByRole('button', {name: 'Undo this revision'}))
    fireEvent.change(screen.getByLabelText('Reason for undoing'), {target: {value: 'Restore prior guidance.'}})
    fireEvent.click(screen.getByRole('button', {name: 'Confirm rollback'}))
    await screen.findByRole('alert')
    expect(screen.getByText('Plan changed; refresh before undoing.')).toBeInTheDocument()
    expect(screen.getByRole('button', {name: 'Confirm rollback'})).toBeEnabled()
  })

  it('refreshes the calendar and can undo the latest change after a later confirmation', async () => {
    confirmed = true
    const {client} = mount(<AgentPlanHistory/>)
    await screen.findByText(/Today confirmed/)
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    fireEvent.click(screen.getByRole('button', {name: 'Refresh plans'}))
    expect(invalidate).toHaveBeenCalledWith({queryKey: ['plans']})
    fireEvent.click(screen.getByText(/Hold the easy run/))
    fireEvent.click(screen.getByRole('button', {name: 'Undo this revision'}))
    fireEvent.change(screen.getByLabelText('Reason for undoing'), {target: {value: 'Restore prior guidance after confirmation.'}})
    fireEvent.click(screen.getByRole('button', {name: 'Confirm rollback'}))
    await waitFor(() => expect(calls.find(call => call.method === 'POST')).toMatchObject({url: '/api/v1/coach/agent/revisions/revision-2/rollback', body: {expected_revision_id: 'confirmation-3'}}))
  })

  it('requires reviewing undo again when a refresh changes the current revision', async () => {
    mount(<AgentPlanHistory/>)
    fireEvent.click(await screen.findByText(/Hold the easy run/))
    fireEvent.click(screen.getByRole('button', {name: 'Undo this revision'}))
    fireEvent.change(screen.getByLabelText('Reason for undoing'), {target: {value: 'Restore prior guidance.'}})
    confirmed = true
    fireEvent.click(screen.getByRole('button', {name: 'Refresh plans'}))
    await screen.findByText(/Today confirmed/)
    expect(screen.getByRole('button', {name: 'Confirm rollback'})).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('The plan changed.')
    expect(calls.filter(call => call.method === 'POST')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', {name: 'Undo this revision'}))
    expect(screen.getByLabelText('Reason for undoing')).toHaveValue('')
    fireEvent.change(screen.getByLabelText('Reason for undoing'), {target: {value: 'Reviewed the confirmation; restore prior guidance.'}})
    fireEvent.click(screen.getByRole('button', {name: 'Confirm rollback'}))
    await waitFor(() => expect(calls.find(call => call.method === 'POST')?.body).toMatchObject({expected_revision_id: 'confirmation-3'}))
  })


  it('shows saved rest without a projected run or workout completion selector', async () => {
    rest = true
    mount(<App/>)
    fireEvent.click(screen.getByRole('button', {name: 'Cycle'}))
    const day = await screen.findByRole('button', {name: /Rest from running today/})
    expect(within(day).getByText('Rest · running slot')).toBeInTheDocument()
    expect(within(day).queryByText('quality run candidate')).not.toBeInTheDocument()
    expect(within(day).getByText('Full-body strength · repeating')).toBeInTheDocument()
    fireEvent.click(day)
    const dialog = screen.getByRole('dialog', {name: 'Day editor'})
    expect(within(dialog).getByText(/Rest from running today/)).toBeInTheDocument()
    expect(within(dialog).queryByLabelText('Actual for planned run')).not.toBeInTheDocument()
  })

})
