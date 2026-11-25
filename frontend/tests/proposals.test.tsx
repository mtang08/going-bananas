import type { RaceEvent } from '../src/api/types/blocks'
import { qk } from '../src/api/queryKeys'
import type { ProposalException } from '../src/api/types/exceptions'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProposalReview } from '../src/pages/ProposalReview'
import type { ProposalDecision, ProposalDetail } from '../src/api/types/coach'
import type { PlannedStep, SessionState } from '../src/api/types/calendar'

Object.defineProperty(Element.prototype, 'scrollIntoView', { value: vi.fn(), configurable: true })

const unchangedSession: SessionState = {
  id: 's7-rev',
  session_uid: 's7',
  revision: 1,
  calendar_version_number: 2,
  deleted: false,
  local_date: '2026-11-18',
  slot: 0,
  kind: 'run',
  recipe_id: 'REC001',
  custom: false,
  locked: false,
  legacy_unstructured: false,
  legacy_payload: null,
  placeholder: false,
  intent: 'Easy',
  certainty: 'committed',
  planned_duration_s: 1800,
  planned_distance_m: null,
  structure: null,
  strength_slot_id: null,
  notes: null,
  brief: null,
  is_original: true,
  changed_by_version: 2,
  exception_patch: null,
}
const EXCEPTION: ProposalException = {
  finding_ids: [],
  category: 'accumulated_fatigue',
  severity: 'caution',
  confidence: 'moderate',
  triggering_evidence: 'Fatigue 8 on two mornings',
  relevant_context: 'Heat this week',
  ladder_level: 'next_session',
  patch_window: { start: '2026-11-16', end: '2026-11-18' },
  unchanged: [{ session_uid: 's7', reason: 'Easy run stays' }],
  reassess_on: '2026-11-19',
  monitor: ['Morning fatigue'],
  return_criteria: ['Usual fatigue twice'],
  escalate_criteria: ['High through Saturday'],
}
let requests: string[] = []
let proposal: ProposalDetail
let failure: 'network' | 'subset' | 'stale' | 'revision' | null = null
let failReload = false
let events: RaceEvent[] = []
let calendarToday = '2026-11-16'
let failCalendar = false
let calendarSessions: SessionState[]
let writes: ProposalDecision[] = []
let deletes: number[] = []
const clients: QueryClient[] = []
beforeEach(() => {
  requests = []
  failure = null
  failReload = false
  events = []
  calendarToday = '2026-11-16'
  failCalendar = false
  calendarSessions = [unchangedSession]
  writes = []
  deletes = []
  proposal = {
    id: 'p1',
    operation: 'review_rolling_plan',
    status: 'pending',
    submitted_at: '2026-11-12T12:00:00Z',
    decided_at: null,
    headline: 'Adjust the next week',
    why: [{ kind: 'observation', text: 'Keep the run manageable' }],
    uncertainty: [],
    change_triggers: [],
    coach_note: null,
    legacy_text: null,
    sources: [],
    confidence: { decision: 'moderate', evidence: 'high', data: 'moderate' },
    base_calendar_version: 7,
    base_block_version_id: null,
    snapshot_id: 'snapshot',
    running_interruption: null,
    head: 7,
    is_current: true,
    revision: 1,
    revisions: [],
    evidence_ids: ['E-AER-01'],
    policy_ids: ['P001'],
    recipe_ids: ['REC001'],
    next_check: { on: '2026-11-19', check: 'Review after the run' },
    escalation: null,
    decision_result: null,
    exception: null,
    event_review: null,
    patch_resolutions: [],
    patch: null,
    block_change: null,
    anchor_changes: [],
    validation_errors: [],
    skill_version: 'running-coach.v1',
    changes: ['c1', 'c2', 'c3'].map((id, index) => ({
      change_id: id,
      op: 'modify',
      session_uid: `s${index}`,
      before: { intent: 'Easy', planned_duration_s: 1800, structure: null },
      after: { planned_duration_s: 2100 },
      current: { intent: 'Easy' },
      reason: `Adjustment ${index + 1}`,
      decision: 'pending',
      material_flags: [],
    })),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, options?: RequestInit) => {
      const url = String(input)
      requests.push(url)
      if (options?.method === 'DELETE') {
        deletes.push(Number(new URL(url, 'http://localhost').searchParams.get('expected_revision')))
        if (failure === 'revision')
          return {
            ok: false,
            status: 409,
            json: async () => ({
              error: {
                code: 'proposal_revision_conflict',
                message: 'Revision changed',
                fields: [],
              },
            }),
          }
        proposal = { ...proposal, status: 'discarded' }
        return {
          ok: true,
          json: async () => ({
            schema_version: 'v1',
            mode: 'demo',
            data_revision: 2,
            data: { proposal_id: 'p1', revision: proposal.revision, status: 'discarded' },
          }),
        }
      }
      if (options?.method === 'POST') {
        const body = JSON.parse(String(options.body)) as ProposalDecision
        writes.push(body)
        if (failure === 'network') throw new Error('offline')
        if (failure)
          return {
            ok: false,
            status: failure === 'stale' || failure === 'revision' ? 409 : 422,
            json: async () => ({
              error: {
                code:
                  failure === 'stale'
                    ? 'stale_evidence'
                    : failure === 'revision'
                      ? 'proposal_revision_conflict'
                      : 'proposal_invalid_subset',
                message: 'Review the selected changes',
                fields: [{ path: 'changes.1', message: 'Preserve strength count' }],
              },
            }),
          }
        const status =
          body.accept_change_ids.length === 0 && proposal.changes.length
            ? 'rejected'
            : body.reject_change_ids.length
              ? 'partially_accepted'
              : 'accepted'
        proposal = {
          ...proposal,
          status,
          is_current: false,
          changes: proposal.changes.map((change) => ({
            ...change,
            decision: body.accept_change_ids.includes(change.change_id) ? 'accepted' : 'rejected',
          })),
        }
        return {
          ok: true,
          json: async () => ({
            schema_version: 'v1',
            mode: 'demo',
            data_revision: 2,
            data: {
              proposal_id: 'p1',
              status,
              calendar_version: body.accept_change_ids.length ? 8 : null,
              block_version_id: null,
              anchor_keys: [],
              stale_proposals: [],
            },
          }),
        }
      }
      if (failReload && url.includes('/coach/proposals/')) throw new Error('offline')
      if (url.endsWith('/events')) {
        return {
          ok: true,
          json: async () => ({
            schema_version: 'v1',
            mode: 'demo',
            data_revision: 1,
            data: { items: events },
          }),
        }
      }
      if (url.includes('/calendar') && failCalendar) throw new Error('offline')
      if (url.includes('/calendar'))
        return {
          ok: true,
          json: async () => ({
            schema_version: 'v1',
            mode: 'demo',
            data_revision: 1,
            data: {
              today: calendarToday,
              start: '2026-11-09',
              end: '2026-12-02',
              head: 7,
              sessions: calendarSessions,
            },
          }),
        }
      return {
        ok: true,
        json: async () => ({
          schema_version: 'v1',
          mode: 'demo',
          data_revision: 1,
          data: url.endsWith('/profile') ? {} : proposal,
        }),
      }
    }),
  )
})
afterEach(() => {
  cleanup()
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>
      <ProposalReview proposalId="p1" unit="mi" />
    </QueryClientProvider>,
  )
}
async function select(...ids: string[]) {
  fireEvent.click(await screen.findByRole('button', { name: 'Clear' }))
  for (const id of ids) fireEvent.click(await screen.findByLabelText(`Accept change ${id}`))
}

it('renders coach paragraphs and bullets safely with confidence collapsed and follow-up after the plan', async () => {
  proposal.headline = 'Keep this week manageable.'
  proposal.why = [
    { kind: 'observation', text: 'Recent runs felt harder.' },
    { kind: 'inference', text: 'Hold volume steady.' },
  ]
  proposal.changes[0].reason = '<script>alert("test")</script>'
  const { container } = mount()
  await screen.findByText('Keep this week manageable.')
  expect(screen.getByText('Recent runs felt harder.')).toBeVisible()
  expect(screen.getByText('Confidence details').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText('<script>alert("test")</script>')).toBeInTheDocument()
  expect(container.querySelector('script')).toBeNull()
  const table = screen.getByRole('table', { name: 'Proposed plan changes' })
  expect(
    table.compareDocumentPosition(screen.getByText(/Review after the run/)) &
      Node.DOCUMENT_POSITION_PRECEDING,
  ).toBeTruthy()
})

it('preselects sessions and submits only the changes left checked', async () => {
  mount()
  expect(await screen.findByLabelText('Accept change c1')).toBeChecked()
  expect(writes).toHaveLength(0)
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeEnabled()
  fireEvent.click(screen.getByLabelText('Accept change c2'))
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText('Accepted — calendar version 8')
  expect(writes[0]).toEqual({
    idempotency_key: expect.any(String),
    expected_head: 7,
    expected_revision: 1,
    accept_change_ids: ['c1', 'c3'],
    reject_change_ids: ['c2'],
    accept_block_change: false,
    accept_anchor_changes: [],
  })
  expect(screen.queryByRole('button', { name: 'Accept selected' })).not.toBeInTheDocument()
})

it.each(['delete', 'add'] as const)(
  'shows the lift and reason upfront for a strength omission recorded as %s',
  async (op) => {
    const lift = { local_date: '2026-11-18', intent: 'Lower body A' }
    const reason = 'Give sore legs a day to recover before the long run.'
    proposal.changes = [
      {
        ...proposal.changes[0],
        op,
        session_uid: op === 'delete' ? 's0' : null,
        before: op === 'delete' ? { ...lift, kind: 'strength' } : null,
        after: op === 'add' ? { ...lift, kind: 'rest' } : null,
        reason,
        material_flags: ['strength_omission'],
      },
      {
        ...proposal.changes[1],
        before: { local_date: lift.local_date, kind: 'run' },
      },
    ]

    mount()
    const omission = await screen.findByRole('checkbox', {
      name: 'Accept skipping Lower body A on Wed, Nov 18',
    })
    const row = within(omission.closest('tr')!)
    expect(row.getByText('Wed, Nov 18')).toBeInTheDocument()
    expect(row.getByText('Lower body A')).toBeInTheDocument()
    expect(row.getByText('Skip lift')).toBeInTheDocument()
    expect(row.getByText(reason)).toBeInTheDocument()
    expect(row.getByText('This change applies only to the lift.')).toBeInTheDocument()
    expect(row.queryByText('Rest')).not.toBeInTheDocument()
    expect(row.queryByText(/^RPE/)).not.toBeInTheDocument()
    expect(omission.closest('tr')?.nextElementSibling).not.toHaveClass('proposal-detail-row')
    fireEvent.click(row.getByRole('link', { name: 'Read reason 1' }))
    expect(document.getElementById('proposal-reason-1')).toBeNull()
    expect(omission).toBeChecked()

    fireEvent.click(omission)
    expect(screen.getByLabelText('Accept change c2')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
    await screen.findByText('Accepted — calendar version 8')
    expect(writes[0]).toMatchObject({ accept_change_ids: ['c2'], reject_change_ids: ['c1'] })
  },
)

it('refreshes plan data after a decision but not settings', async () => {
  mount()
  const client = clients[clients.length - 1]
  client.setQueryData(qk.calendar, 1)
  client.setQueryData(qk.goals, 1)
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText('Accepted — calendar version 8')
  expect(client.getQueryState(qk.calendar)?.isInvalidated).toBe(true)
  expect(client.getQueryState(qk.goals)?.isInvalidated).toBe(false)
})
it('retains selections and shows structured subset errors', async () => {
  failure = 'subset'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText('changes.1: Preserve strength count')
  expect(screen.getByLabelText('Accept change c1')).toBeChecked()
})
it('retries the exact frozen request after a lost response', async () => {
  failure = 'network'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText(/Cannot reach/)
  failure = null
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1]).toEqual(writes[0])
})
it('creates a new request key after editing the selection', async () => {
  failure = 'subset'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText('changes.1: Preserve strength count')
  await select('c3')
  failure = null
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1].idempotency_key).not.toBe(writes[0].idempotency_key)
})
it('disables stale proposals and retains their saved diff', async () => {
  proposal.is_current = false
  mount()
  await screen.findByText(/This proposal is stale/)
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeDisabled()
  expect(screen.getAllByText('Easy').length).toBeGreaterThan(0)
})
it('blocks further acceptance after a source conflict', async () => {
  failure = 'stale'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText(/This proposal is stale/)
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeDisabled()
})
it('requires an explicit reload after a revision conflict and discards old selections', async () => {
  failure = 'revision'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText(/edited while you reviewed it/)
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeDisabled()
  proposal = {
    ...proposal,
    revision: 2,
    revisions: [
      {
        revision: 2,
        saved_at: '2026-11-12T13:00:00Z',
        reason: 'Adjusted the run',
        changed_change_ids: ['c2'],
        changed_fields: ['rationale'],
      },
    ],
  }
  failure = null
  fireEvent.click(screen.getByRole('button', { name: 'Reload proposal' }))
  await waitFor(() => expect(screen.getAllByText(/Revision 2/).length).toBeGreaterThan(0))
  expect(screen.getByLabelText('Accept change c2')).toBeChecked()
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeEnabled()
  expect(screen.getByText('Revision history').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByLabelText('Accept change c2').closest('tr')).toHaveClass(
    'proposal-revised-row',
  )
  await select('c2')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1].expected_revision).toBe(2)
  expect(writes[1].idempotency_key).not.toBe(writes[0].idempotency_key)
})
it('keeps a revision conflict blocked when reload fails', async () => {
  failure = 'revision'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText(/edited while you reviewed it/)
  failReload = true
  fireEvent.click(screen.getByRole('button', { name: 'Reload proposal' }))
  await screen.findByText(/Refresh failed/)
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Reload proposal' })).toBeEnabled()
  expect(writes).toHaveLength(1)
})
it('clears stale decision state when a newer current revision arrives', async () => {
  failure = 'stale'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText(/This proposal is stale/)
  proposal = {
    ...proposal,
    revision: 2,
    is_current: true,
    revisions: [
      {
        revision: 2,
        saved_at: '2026-11-12T13:00:00Z',
        reason: 'Updated recovery',
        changed_change_ids: ['removed-c4'],
        changed_fields: ['summary'],
      },
    ],
  }
  await clients[0].invalidateQueries({ queryKey: ['v2', 'proposals', 'p1'] })
  await waitFor(() => expect(screen.queryByText(/This proposal is stale/)).not.toBeInTheDocument())
  expect(screen.getByLabelText('Accept change c2')).toBeChecked()
  fireEvent.click(screen.getByText('Revision history'))
  expect(screen.getByText(/removed sessions: 1/)).toBeInTheDocument()
  failure = null
  await select('c2')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1].expected_revision).toBe(2)
})
it('resets review selections when a background refresh reveals a new revision', async () => {
  mount()
  await select('c1')
  proposal = {
    ...proposal,
    revision: 2,
    revisions: [
      {
        revision: 2,
        saved_at: '2026-11-12T13:00:00Z',
        reason: 'Updated recovery',
        changed_change_ids: [],
        changed_fields: ['summary'],
      },
    ],
  }
  await clients[0].invalidateQueries({ queryKey: ['v2', 'proposals', 'p1'] })
  await waitFor(() => expect(screen.getByLabelText('Accept change c2')).toBeChecked())
  expect(screen.getByRole('button', { name: 'Accept selected' })).toBeEnabled()
  await select('c3')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].expected_revision).toBe(2)
})
it('rejects every item without claiming a calendar update', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Reject all' }))
  await screen.findByText('Decision recorded — calendar unchanged')
  expect(writes[0].reject_change_ids).toEqual(['c1', 'c2', 'c3'])
  expect(writes[0].accept_change_ids).toEqual([])
})
it('records explicit empty acknowledgment with no ambiguous rejection', async () => {
  proposal.changes = []
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Accept (no changes)' }))
  await screen.findByText('Decision recorded — calendar unchanged')
  expect(writes[0].accept_change_ids).toEqual([])
  expect(screen.queryByRole('button', { name: 'Reject all' })).not.toBeInTheDocument()
})

it('keeps imported prose visible without inventing structured reps', async () => {
  proposal.changes[0].before = {
    intent: 'Imported easy prescription',
    notes: 'Walk breaks as needed',
    legacy_unstructured: true,
    structure: null,
  }
  mount()
  expect((await screen.findAllByText('Walk breaks as needed')).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/Imported prescription/).length).toBeGreaterThan(0)
})
it('keeps malformed saved workouts reviewable and blocks accepting them', async () => {
  const bad: PlannedStep = {
    type: 'work',
    duration_type: 'time',
    duration_value: 180,
    target: { modality: 'effort', low: 6, high: 7, effort_cue: 'Controlled' },
  }
  proposal.changes[0].after = {
    intent: 'Controlled intervals',
    notes: 'Keep the run days',
    structure: [{ type: 'repeat', count: 5, steps: [bad] }],
  }
  proposal.changes[1].before = { structure: [bad] }
  mount()
  await screen.findByText('Controlled intervals')
  expect(screen.getAllByText(/This workout's steps are invalid/).length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText('Keep the run days')).toBeInTheDocument()
  expect(screen.getByLabelText('Accept change c1')).toBeDisabled()
  expect(screen.getByLabelText('Accept change c2')).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Reject all' })).toBeEnabled()
  expect(writes).toHaveLength(0)
  await select('c2')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].accept_change_ids).toEqual(['c2'])
  expect(writes[0].reject_change_ids).toEqual(['c1', 'c3'])
})
it('renders repeated effort targets with RPE in the cue', async () => {
  const work: PlannedStep = {
    type: 'work',
    duration_type: 'time',
    duration_value: 180,
    target: { modality: 'effort', low: null, high: null, effort_cue: 'RPE 6-7, controlled' },
  }
  proposal.changes[0].after = { structure: [{ type: 'repeat', count: 5, steps: [work] }] }
  mount()
  expect(await screen.findByText('5 × (Work 3:00 · RPE 6-7, controlled)')).toBeInTheDocument()
  expect(screen.getByLabelText('Accept change c1')).toBeEnabled()
  expect(writes).toHaveLength(0)
})
it('requires separate selections for block and anchor changes', async () => {
  proposal.changes = []
  proposal.block_change = {
    decision: 'start',
    block_uid: null,
    version_fields: {
      objective: 'Build consistency',
      constraints: [{ kind: 'schedule', text: 'Keep strength days' }],
    },
  }
  proposal.anchor_changes = [
    {
      anchor_key: 'hr_threshold_lower-2026-11-12',
      kind: 'hr_threshold_lower',
      value_low: 165,
      value_high: null,
      unit: 'bpm',
      protocol: 'manual',
      confidence: 'moderate',
      calibrated_at: '2026-11-12T12:00:00Z',
      supersedes_key: null,
    },
  ]
  mount()
  expect(await screen.findByLabelText('Accept block change')).not.toBeChecked()
  expect(screen.getByLabelText('Accept anchor hr_threshold_lower-2026-11-12')).not.toBeChecked()
  fireEvent.click(screen.getByLabelText('Accept block change'))
  fireEvent.click(screen.getByLabelText('Accept anchor hr_threshold_lower-2026-11-12'))
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].accept_block_change).toBe(true)
  expect(writes[0].accept_anchor_changes).toEqual(['hr_threshold_lower-2026-11-12'])
})
it('shows saved block and anchor decisions after reopening a terminal proposal', async () => {
  proposal.status = 'partially_accepted'
  proposal.is_current = false
  proposal.changes = []
  proposal.block_change = {
    decision: 'continue',
    block_uid: 'b1',
    version_fields: { objective: 'Continue' },
  }
  proposal.anchor_changes = [
    {
      anchor_key: 'hr_threshold_lower-2026-11-12',
      kind: 'hr_threshold_lower',
      value_low: 165,
      value_high: null,
      unit: 'bpm',
      protocol: 'manual',
      confidence: 'moderate',
      calibrated_at: '2026-11-12T12:00:00Z',
      supersedes_key: null,
    },
  ]
  proposal.decision_result = {
    proposal_id: 'p1',
    status: 'partially_accepted',
    calendar_version: null,
    block_version_id: 'v1',
    anchor_keys: [],
    stale_proposals: [],
  }
  mount()
  await screen.findByText('Block decision: accepted')
  expect(screen.getByText('Anchor decision: rejected')).toBeInTheDocument()
  expect(screen.queryByLabelText('Accept block change')).not.toBeInTheDocument()
  expect(screen.getByText('Decision recorded — calendar unchanged')).toBeInTheDocument()
})

it('shows the complete proposed workouts in date order with matching numbered reasons and no evidence tags', async () => {
  proposal.why = [{ kind: 'inference', text: 'Keep the training manageable.' }]
  proposal.changes = [
    {
      change_id: 'c1',
      op: 'modify',
      session_uid: 's1',
      before: {
        local_date: '2026-11-16',
        kind: 'run',
        recipe_id: 'REC001',
        intent: 'Conversational effort',
        planned_duration_s: 1800,
        planned_distance_m: 5000,
        notes: 'Keep the route flat',
      },
      after: { planned_duration_s: 2100 },
      current: null,
      reason: 'Add five easy minutes.',
      decision: 'pending',
      material_flags: [],
    },
    {
      change_id: 'c2',
      op: 'add',
      session_uid: null,
      before: null,
      after: {
        local_date: '2026-11-12',
        kind: 'strength',
        intent: 'Full body A',
        planned_duration_s: 3600,
      },
      current: null,
      reason: 'Preserve the lifting commitment.',
      decision: 'pending',
      material_flags: [],
    },
    {
      change_id: 'c3',
      op: 'delete',
      session_uid: 's3',
      before: {
        local_date: '2026-11-14',
        kind: 'run',
        recipe_id: 'REC002',
        intent: 'Long easy run',
        planned_duration_s: 4500,
      },
      after: null,
      current: null,
      reason: 'Allow more recovery.',
      decision: 'pending',
      material_flags: [],
    },
  ]
  mount()
  const table = await screen.findByRole('table', { name: 'Proposed plan changes' })
  const rows = within(table)
    .getAllByRole('row')
    .filter(
      (row) =>
        !row.classList.contains('proposal-week-row') &&
        !row.classList.contains('proposal-detail-row'),
    )
    .slice(1)
  expect(rows).toHaveLength(3)
  expect(within(rows[0]).getByText('Full body A')).toBeInTheDocument()
  expect(within(rows[1]).getByText('Remove this session from the plan.')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Conversational effort')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Duration: 35m')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Distance: 5.00 km')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Keep the route flat')).toBeInTheDocument()
  expect(within(rows[2]).getByRole('link', { name: 'Read reason 3' })).toHaveAttribute(
    'href',
    '#proposal-reason-3',
  )
  expect(
    rows.map((row) => row.nextElementSibling?.querySelector('details > summary')?.textContent),
  ).toEqual(['Preserve the lifting commitment.', 'Allow more recovery.', 'Add five easy minutes.'])
  expect(
    screen.queryByText(/E-AER-01|P001|REC001|REC002|Evidence and policies/),
  ).not.toBeInTheDocument()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ accept_change_ids: ['c1'], reject_change_ids: ['c2', 'c3'] })
})

it('shows moved dates and preserves explicit cleared values in the proposal', async () => {
  proposal.changes = [
    {
      ...proposal.changes[0],
      op: 'move',
      before: {
        local_date: '2026-11-12',
        kind: 'run',
        planned_distance_m: 5000,
        notes: 'Old note',
      },
      after: { local_date: '2026-11-13', planned_distance_m: null, notes: null },
    },
  ]
  mount()
  const table = await screen.findByRole('table', { name: 'Proposed plan changes' })
  expect(within(table).getByText(/Previously Thu, Nov 12/)).toBeInTheDocument()
  expect(within(table).getByText('Distance: Not specified')).toBeInTheDocument()
  expect(within(table).getByText('Old note')).not.toBeVisible()
  expect(
    within(screen.getByRole('checkbox', { name: 'Accept change c1' }).closest('tr')!).queryByText(
      'Old note',
    ),
  ).not.toBeInTheDocument()
})

it('confirms discard at the reviewed revision without making a decision', async () => {
  proposal.revision = 3
  mount()
  const client = clients[clients.length - 1]
  client.setQueryData(qk.calendar, 1)
  client.setQueryData(qk.proposals, 1)
  fireEvent.click(await screen.findByRole('button', { name: 'Discard proposal' }))
  expect(screen.getByText(/removed from the open list/)).toBeInTheDocument()
  expect(deletes).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }))
  await screen.findByText(/Proposal discarded/)
  expect(deletes).toEqual([3])
  expect(writes).toEqual([])
  expect(client.getQueryState(qk.calendar)?.isInvalidated).toBe(false)
  expect(client.getQueryState(qk.proposals)?.isInvalidated).toBe(true)
  expect(screen.queryByRole('button', { name: 'Reject all' })).not.toBeInTheDocument()
  expect(screen.queryByText('Decision: rejected')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Return home' })).toHaveAttribute('href', '#home')
})
it('cancels discard without a write', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Discard proposal' }))
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('button', { name: 'Confirm discard' })).not.toBeInTheDocument()
  expect(deletes).toEqual([])
  expect(writes).toEqual([])
})
it.each(['stale', 'invalid'] as const)('can discard a %s proposal', async (status) => {
  proposal.status = status
  proposal.is_current = false
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Discard proposal' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }))
  await screen.findByText(/Proposal discarded/)
  expect(deletes).toEqual([1])
})
it('clears a mutation stale warning after discard', async () => {
  failure = 'stale'
  mount()
  await select('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText(/This proposal is stale/)
  fireEvent.click(screen.getByRole('button', { name: 'Discard proposal' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }))
  await screen.findByText(/Proposal discarded/)
  expect(screen.queryByText(/This proposal is stale/)).not.toBeInTheDocument()
  expect(screen.queryByText(/unchecked changes will be rejected/)).not.toBeInTheDocument()
})
it('blocks discard after a revision conflict until an explicit reload', async () => {
  failure = 'revision'
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Discard proposal' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }))
  await screen.findByText(/edited while you reviewed it/)
  expect(screen.getByRole('button', { name: 'Confirm discard' })).toBeDisabled()
  expect(deletes).toEqual([1])
  proposal = { ...proposal, revision: 2 }
  failure = null
  fireEvent.click(screen.getByRole('button', { name: 'Reload proposal' }))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Discard proposal' })).toBeEnabled(),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Discard proposal' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }))
  await waitFor(() => expect(deletes).toEqual([1, 2]))
})
it.each(['accepted', 'rejected', 'discarded'] as const)(
  'hides discard for %s proposals',
  async (status) => {
    proposal.status = status
    mount()
    await screen.findByText(/Adjust the next week/)
    expect(screen.queryByRole('button', { name: 'Discard proposal' })).not.toBeInTheDocument()
  },
)

it('selects all valid changes and clears them', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Select all' }))
  for (const id of ['c1', 'c2', 'c3'])
    expect(screen.getByLabelText(`Accept change ${id}`)).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
  for (const id of ['c1', 'c2', 'c3'])
    expect(screen.getByLabelText(`Accept change ${id}`)).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Clear' })).toBeDisabled()
  expect(writes).toHaveLength(0)
})
it('select all skips changes with invalid saved workouts', async () => {
  const bad: PlannedStep = {
    type: 'work',
    duration_type: 'time',
    duration_value: 180,
    target: { modality: 'effort', low: 6, high: 7, effort_cue: 'Controlled' },
  }
  proposal.changes[0].after = {
    intent: 'Controlled intervals',
    notes: 'Keep the run days',
    structure: [{ type: 'repeat', count: 5, steps: [bad] }],
  }
  mount()
  await screen.findByText('Controlled intervals')
  fireEvent.click(screen.getByRole('button', { name: 'Select all' }))
  expect(screen.getByLabelText('Accept change c1')).not.toBeChecked()
  for (const id of ['c2', 'c3']) expect(screen.getByLabelText(`Accept change ${id}`)).toBeChecked()
})
it('applies all sessions with one explicit decision and links to Calendar and Home', async () => {
  mount()
  await screen.findByLabelText('Accept change c1')
  expect(writes).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Accept selected' }))
  await screen.findByText('Accepted — calendar version 8')
  expect(writes[0].accept_change_ids).toEqual(['c1', 'c2', 'c3'])
  expect(screen.getByRole('link', { name: 'Open calendar' })).toHaveAttribute('href', '#calendar')
  expect(screen.getByRole('link', { name: 'Return home' })).toHaveAttribute('href', '#home')
})
it('separates discard from reject and drops the legacy link', async () => {
  mount()
  await screen.findByRole('button', { name: 'Select all' })
  const secondary = within(screen.getByTestId('proposal-secondary'))
  expect(secondary.getByRole('button', { name: 'Discard proposal' })).toBeInTheDocument()
  expect(secondary.getByText(/Discard removes it without a decision/)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Legacy coaching history' })).toBeNull()
  expect(screen.queryByText('Planning upgrade required')).toBeNull()
})

it('shows the exception card after the intro', async () => {
  proposal.exception = EXCEPTION
  mount()
  const card = await screen.findByTestId('proposal-exception')
  for (const text of [
    'Exception',
    'Fatigue and recovery',
    'Caution',
    'Confidence: moderate',
    'Why now',
    'Fatigue 8 on two mornings',
    'Context',
    'Next session only · Mon, Nov 16–Wed, Nov 18',
    'Reassess on Thu, Nov 19',
    'Watch for',
    'Morning fatigue',
    'Back to plan when',
    'Usual fatigue twice',
    'Escalate if',
    'High through Saturday',
  ])
    expect(within(card).getByText(text)).toBeInTheDocument()
  expect(
    await within(card).findByText('Wed, Nov 18 · Easy run — Easy run stays'),
  ).toBeInTheDocument()
  expect(
    screen.getByTestId('proposal-intro').compareDocumentPosition(card) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
  expect(
    screen.getByRole('heading', { name: 'Proposed plan changes' }).compareDocumentPosition(card) &
      Node.DOCUMENT_POSITION_PRECEDING,
  ).toBeTruthy()
})
it('old proposals without the new fields render unchanged', async () => {
  mount()
  await screen.findByText('Adjust the next week')
  for (const id of ['proposal-exception', 'proposal-event-review', 'proposal-patch-updates'])
    expect(screen.queryByTestId(id)).toBeNull()
})

it('shows outcome and comparison in the race review', async () => {
  proposal.operation = 'review_training_block'
  proposal.event_review = {
    event_id: null,
    activity_id: 'a1',
    outcome: 'progress',
    compared_with: '5K TT 21:40 last block',
    pacing: 'Even splits',
    effort_and_limiter: 'RPE 9, breathing',
    conditions: null,
    symptoms: null,
    recovery_observation: 'Normal next day',
    recalibration: 'propose_anchors',
    training_implication: 'Progress volume',
  }
  mount()
  const card = await screen.findByTestId('proposal-event-review')
  expect(Array.from(card.querySelectorAll('dt')).map((x) => x.textContent)).toEqual([
    'Outcome',
    'Compared with',
    'Pacing',
    'Effort and limiter',
    'Recovery observation',
    'Recalibration',
    'Training implication',
  ])
  for (const text of ['Progress', '5K TT 21:40 last block', 'New paces proposed'])
    expect(within(card).getByText(text)).toBeInTheDocument()
  expect(card.querySelector('h2')).toHaveTextContent('Benchmark review')
  cleanup()
  proposal.operation = 'post_event_review'
  mount()
  expect(
    (await screen.findByTestId('proposal-event-review')).querySelector('h2'),
  ).toHaveTextContent('Race review')
})
it('lists patch updates', async () => {
  proposal.patch_resolutions = [{ patch_id: 'pa1', status: 'resolved', note: 'Fatigue settled' }]
  mount()
  const card = await screen.findByTestId('proposal-patch-updates')
  for (const text of ['Patch updates', 'Resolved', 'Fatigue settled'])
    expect(within(card).getByText(text)).toBeInTheDocument()
  cleanup()
  proposal.patch_resolutions = []
  mount()
  await screen.findByText('Adjust the next week')
  expect(screen.queryByTestId('proposal-patch-updates')).toBeNull()
})

it.each([
  {
    today: '2026-11-16',
    dates: ['2026-11-17', '2026-11-24', '2026-12-01'],
    offline: false,
    headings: [
      'Week of Nov 16 · Committed',
      'Week of Nov 23 · Provisional',
      'Week of Nov 30 · Provisional',
    ],
  },
  {
    today: '2026-11-18',
    dates: ['2026-11-23', '2026-11-25'],
    offline: false,
    headings: ['Week of Nov 23 · Committed and provisional'],
  },
  {
    today: '2026-11-16',
    dates: ['2026-11-17'],
    offline: true,
    headings: ['Week of Nov 16'],
  },
])(
  'groups proposed dates when today is $today and calendar offline is $offline',
  async ({ today, dates, offline, headings }) => {
    calendarToday = today
    failCalendar = offline
    proposal.changes = dates.map((date, index) => ({
      change_id: `group-${index}`,
      op: 'add',
      session_uid: null,
      before: null,
      after: { local_date: date, kind: 'run', intent: 'Easy run' },
      current: null,
      reason: 'Build consistency.',
      decision: 'pending',
      material_flags: [],
    }))
    mount()
    const table = await screen.findByRole('table', { name: 'Proposed plan changes' })
    await waitFor(() => {
      expect(
        within(table)
          .getAllByRole('columnheader', { name: /^Week of / })
          .map((cell) => cell.textContent),
      ).toEqual(headings)
    })
    expect(within(table).getByRole('link', { name: 'Read reason 1' })).toBeInTheDocument()
  },
)

it('names the goal race and outline on the block card', async () => {
  events = [
    {
      id: 'e1',
      name: 'NYC Half',
      event_date: '2027-03-14',
      distance_m: 21098,
      purpose: 'pr',
      goal_time_s: 6300,
      rank: 1,
      status: 'planned',
      result_s: null,
      version: 1,
    },
  ]
  proposal.changes = []
  proposal.block_change = {
    decision: 'continue',
    block_uid: 'b1',
    version_fields: {
      objective: 'Build consistency',
      target_event_id: 'e1',
      build_outline: [
        { emphasis: 'threshold durability', weeks: 4 },
        { emphasis: 'half-marathon-specific endurance', weeks: 5 },
      ],
    },
  }
  mount()
  expect(await screen.findByText('Builds toward: NYC Half (Mar 14)')).toBeInTheDocument()
  const list = screen.getByRole('list', { name: 'Build outline' })
  expect(
    within(list)
      .getAllByRole('listitem')
      .map((item) => item.textContent),
  ).toEqual(['4 wk threshold durability', '5 wk half-marathon-specific endurance'])
})

it('says no event when the block has no goal race', async () => {
  proposal.changes = []
  proposal.block_change = {
    decision: 'continue',
    block_uid: 'b1',
    version_fields: { objective: 'Build consistency', target_event_id: null, build_outline: [] },
  }
  mount()
  expect(await screen.findByText('Builds toward: no event')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Build outline' })).toBeNull()
})

it('shows confidence, unknowns, rationale rows, triggers, and a next check inside the brief', async () => {
  proposal.why = [
    { kind: 'observation', text: 'Tempo held two weeks running' },
    { kind: 'research', text: 'Progress one variable at a time' },
    { kind: 'inference', text: 'One more repeat may fit the week' },
    { kind: 'priority', text: 'Keep Thursday easy' },
  ]
  proposal.uncertainty = ['No sleep data since Wed']
  proposal.change_triggers = [{ when: 'Calf gets sore', then: 'Reduce volume' }]
  proposal.next_check = { on: '2026-11-29', check: 'Thu tempo RPE and calf response' }
  proposal.escalation = 'block_review'
  mount()
  const card = await screen.findByTestId('proposal-intro')
  const contents = within(card)
  for (const text of [
    'Observed',
    'Research',
    'Inference',
    'Your priority',
    'Would change this',
    'Calf gets sore',
    'Reduce volume',
  ]) {
    expect(contents.getByText(text)).toBeVisible()
  }
  for (const text of [
    'Confidence: moderate',
    'Unknown: No sleep data since Wed',
    'Next check: Sun, Nov 29',
    'Thu tempo RPE and calf response',
    'Suggested next review: block review',
  ]) {
    expect(card).toHaveTextContent(text)
  }
})

it('reports missing confidence and hides empty brief sections', async () => {
  proposal.confidence = {}
  proposal.why = []
  proposal.uncertainty = []
  proposal.change_triggers = []
  mount()
  const card = await screen.findByTestId('proposal-intro')
  expect(card).toHaveTextContent('Confidence: Not stated')
  expect(card).not.toHaveTextContent('Confidence: undefined')
  expect(within(card).getByText(proposal.headline)).toBeVisible()
  for (const label of ['Why', 'Would change this', 'Unknown:', 'Earlier format', /^Sources/]) {
    expect(within(card).queryByText(label)).not.toBeInTheDocument()
  }
})

it('keeps the coach note, sources, and earlier format collapsed', async () => {
  proposal.coach_note = 'Short note'
  proposal.legacy_text = 'Prior rationale\n\nNext check after the run'
  proposal.sources = [
    { kind: 'policy', title: 'Progress one variable at a time', papers: ['Paper A (2020)'] },
  ]
  mount()
  const card = within(await screen.findByTestId('proposal-intro'))
  for (const label of ['Coach note', 'Sources (1)', 'Earlier format']) {
    expect(card.getByText(label).closest('details')).not.toHaveAttribute('open')
  }
  expect(card.getByText('Prior rationale')).not.toBeVisible()
  expect(card.getByText('Short note')).not.toBeVisible()
  expect(card.getByText('Progress one variable at a time')).toHaveAttribute(
    'title',
    'Paper A (2020)',
  )
})

it('the numbered reason link opens the expander and shows the session brief', async () => {
  proposal.changes[0].after = {
    intent: 'Threshold control',
    brief: {
      effort: { rpe_low: 6, rpe_high: 7, feel: 'controlled' },
      focus: ['Even splits'],
      adjust_if: [{ when: 'Rep pace fades more than 5%', then: 'stop after rep 4' }],
      why: 'Last two sessions hit pace at RPE 7',
    },
  }
  mount()
  const link = await screen.findByRole('link', { name: 'Read reason 1' })
  const details = document.getElementById('proposal-reason-1')!
  expect(details.tagName).toBe('DETAILS')
  expect(details).not.toHaveAttribute('open')
  expect(within(link.closest('tr')!).getByText('RPE 6–7')).toBeVisible()
  fireEvent.click(link)
  expect(details).toHaveAttribute('open')
  for (const text of [
    'Adjust if',
    'Rep pace fades more than 5%',
    'stop after rep 4',
    'Even splits',
    'Last two sessions hit pace at RPE 7',
  ]) {
    expect(within(details).getByText(text)).toBeVisible()
  }
})

it('shows notes in the row and the comparison without creating a coach brief', async () => {
  proposal.changes[0].before = {
    local_date: '2026-11-16',
    kind: 'run',
    notes: 'Keep the route flat',
  }
  mount()
  const link = await screen.findByRole('link', { name: 'Read reason 1' })
  expect(within(link.closest('tr')!).getByText('Keep the route flat')).toBeVisible()
  expect(screen.queryByText(/^RPE/)).not.toBeInTheDocument()
  fireEvent.click(link)
  const detail = within(document.getElementById('proposal-reason-1')!)
  expect(detail.queryByText('Adjust if')).not.toBeInTheDocument()
  fireEvent.click(detail.getByText('Compare with previous plan'))
  expect(detail.getByRole('heading', { name: 'Notes' })).toBeVisible()
  expect(detail.getByText('Keep the route flat')).toBeVisible()
})

it('shows the current session in the comparison for a stale proposal', async () => {
  proposal.status = 'stale'
  proposal.is_current = false
  proposal.changes[0].current = { intent: 'Keep it easy' }
  mount()
  fireEvent.click(await screen.findByRole('link', { name: 'Read reason 1' }))
  const detail = within(document.getElementById('proposal-reason-1')!)
  fireEvent.click(detail.getByText('Compare with saved and current plan'))
  expect(detail.getByRole('heading', { name: 'Current session' })).toBeVisible()
  expect(detail.getByText('Keep it easy')).toBeVisible()
})

const blockFields: NonNullable<ProposalDetail['block_change']>['version_fields'] = {
  objective: 'Threshold durability',
  status: 'active',
  start_date: '2026-11-23',
  review_date: '2026-12-20',
  progression_dimension: 'quality_volume',
  objective_status: 'unresolved',
  why: [
    { kind: 'observation', text: 'Tempo held 4:08/km at RPE 6 two weeks running' },
    { kind: 'priority', text: 'City 10K is the goal race' },
  ],
  indicators: [
    {
      source: 'quality_progression',
      label: 'Tempo reps at the same RPE',
      progress_when: 'pace 2% faster at RPE 7 or lower',
    },
    { source: 'rpe_vs_intent', label: 'Easy days stay easy', progress_when: 'RPE 4 or lower' },
  ],
  early_review_triggers: ['Calf 3/10 twice', '2 missed key sessions'],
  maintained_qualities: ['aerobic volume', 'strides'],
  non_goals: ['Peak racing'],
  constraints: [{ kind: 'schedule', text: 'Keep strength days' }],
  eligible_recipe_ids: ['REC001'],
}

async function mountBlockChange(fields: typeof blockFields) {
  proposal.changes = []
  proposal.block_change = { decision: 'continue', block_uid: 'b1', version_fields: fields }
  mount()
  return within(
    (await screen.findByRole('heading', { name: 'Training block: continue' })).closest(
      '.block-change-card',
    )!,
  )
}

it('shows block objective and summary chips followed by collapsible criteria', async () => {
  const card = await mountBlockChange(blockFields)
  expect(card.getByText('Threshold durability').tagName).toBe('STRONG')
  for (const text of [
    'active',
    'Progression: quality volume',
    'Objective: unresolved',
    'Builds toward: no event',
  ]) {
    expect(card.getByText(text)).toBeVisible()
  }
  for (const label of [
    'Why this block',
    'Review by',
    'Qualities, constraints, eligible sessions',
  ]) {
    const summary = card.getByText(label)
    expect(summary.closest('details')).not.toHaveAttribute('open')
    fireEvent.click(summary)
  }
  expect(card.getByText('Observed')).toBeVisible()
  expect(card.getByText('Your priority')).toBeVisible()
  expect(card.getByText('Tempo held 4:08/km at RPE 6 two weeks running')).toBeVisible()
  expect(card.getByText('City 10K is the goal race')).toBeVisible()
  expect(card.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
    'Indicator',
    'Progress when',
    'Source',
  ])
  expect(
    card.getByRole('row', {
      name: /Tempo reps at the same RPE.*pace 2% faster.*Workout progression/,
    }),
  ).toBeVisible()
  expect(card.getByRole('row', { name: /Easy days stay easy.*Effort vs plan/ })).toBeVisible()
  expect(card.getByText('Review early if:').closest('p')).toHaveTextContent(
    'Calf 3/10 twice · 2 missed key sessions',
  )
  for (const text of [
    'Review early if:',
    'Maintains:',
    'Outside this block:',
    'Peak racing',
    'schedule: Keep strength days',
    'Easy run',
  ]) {
    expect(card.getByText(text)).toBeVisible()
  }
})

it('shows the proposed benchmark date as a chip', async () => {
  const card = await mountBlockChange({
    ...blockFields,
    benchmark: {
      kind: 'time_trial',
      event_id: null,
      protocol: '5 km time trial',
      distance_m: 5000,
      planned_date: '2026-12-13',
      progress_if: 'Faster than 21:40',
      consolidate_if: 'Within 20 s of 21:40',
    },
  })
  expect(card.getByText('Benchmark: Dec 13')).toBeVisible()
})

it('renders no empty block disclosures for a migrated change', async () => {
  const card = await mountBlockChange({
    objective: 'Continue',
    status: 'active',
    why: [],
    indicators: [],
    early_review_triggers: [],
    maintained_qualities: [],
    non_goals: [],
    constraints: [],
    eligible_recipe_ids: [],
  })
  for (const label of [
    'Why this block',
    'Review by',
    'Qualities, constraints, eligible sessions',
    'Not specified',
  ]) {
    expect(card.queryByText(label)).not.toBeInTheDocument()
  }
  expect(card.getByRole('checkbox', { name: 'Accept block change' })).toBeVisible()
})

it('previews selected moves across weeks and nearby intervals without counting an explicit dose twice', async () => {
  const long = {
    ...unchangedSession,
    session_uid: 'long',
    local_date: '2026-11-22',
    recipe_id: 'REC002',
    planned_duration_s: 5400,
    planned_distance_m: 12000,
    structure: [{ type: 'work', duration_type: 'distance', duration_value: 12000, target: null }],
  } satisfies SessionState
  const intervals = {
    ...unchangedSession,
    session_uid: 'hard',
    local_date: '2026-11-24',
    recipe_id: 'REC003',
    planned_duration_s: 3600,
    planned_distance_m: null,
  }
  calendarSessions = [long, intervals]
  proposal.changes = [
    {
      ...proposal.changes[0],
      session_uid: long.session_uid,
      op: 'move',
      before: long,
      after: { local_date: '2026-11-23' },
    },
    {
      ...proposal.changes[1],
      session_uid: intervals.session_uid,
      op: 'delete',
      before: intervals,
      after: null,
    },
    {
      ...proposal.changes[2],
      session_uid: null,
      op: 'add',
      before: null,
      after: { ...unchangedSession, local_date: '2026-12-01' },
    },
  ]
  mount()
  const impact = within(await screen.findByLabelText('Two-week schedule impact'))
  expect(impact.getByText('Move Long run').closest('li')).toHaveTextContent(
    'Sun, Nov 22 → Mon, Nov 23',
  )
  expect(impact.getByText('−7.5 mi')).toBeInTheDocument()
  expect(impact.getByText('+7.5 mi known · some dose unknown')).toBeInTheDocument()
  expect(impact.getByText('−1h 30m')).toBeInTheDocument()
  expect(impact.getByText('+30m')).toBeInTheDocument()
  expect(impact.getByText('Selected changes outside this preview or without a date')).toBeVisible()
  expect(impact.queryByText(/Nearest demanding workout/)).not.toBeInTheDocument()

  const checks = screen.getAllByRole('checkbox')
  fireEvent.click(checks[1])
  expect(
    await impact.findByText(/Threshold intervals on Tue, Nov 24 \(the next day\)/),
  ).toBeVisible()
  expect(impact.getByText('+7.5 mi')).toBeInTheDocument()
  expect(impact.getByText('+1h 30m')).toBeInTheDocument()

  fireEvent.click(checks[0])
  expect(impact.queryByText('Move Long run')).not.toBeInTheDocument()
  expect(impact.getAllByText('0.0 mi')).toHaveLength(2)
  expect(writes).toHaveLength(0)
})

it('shows which affected future runs would remain when the athlete deselects a return-plan change', async () => {
  proposal.running_interruption = {
    today: '2026-11-16',
    interruption: {
      reason: 'illness',
      starts_on: '2026-11-15',
      return_on: null,
      review_on: '2026-11-20',
    },
    affected_runs: [
      { session_uid: 'past', local_date: '2026-11-15', recipe_id: 'REC002' },
      { session_uid: 's0', local_date: '2026-11-18', recipe_id: 'REC001' },
    ],
    affected_runs_omitted: 0,
  }
  proposal.changes = [{ ...proposal.changes[0], op: 'delete', after: null }]
  mount()
  const review = within(await screen.findByLabelText('Running break in this proposal'))
  expect(review.getByText(/Reassess on Nov 20/)).toBeVisible()
  expect(await review.findByText(/Removed from the plan/)).toBeVisible()
  expect(review.queryByText(/Long run/i)).toBeNull()
  fireEvent.click(await screen.findByLabelText('Accept change c1'))
  expect(review.getByText(/Stays on the calendar/)).toBeVisible()
  expect(writes).toHaveLength(0)
})
