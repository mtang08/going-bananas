import type { ProposalListResponse } from '../client'
import type { components } from '../generated/coachProposals'
import type {
  Patch,
  ProposalEventReview,
  ProposalException,
  ProposalPatchResolution,
} from './exceptions'
import type { RunningInterruption, InterruptionRun } from './runningInterruption'

type Schemas = components['schemas']

export interface ProposalInterruption {
  today: string
  interruption: RunningInterruption
  affected_runs: Pick<InterruptionRun, 'session_uid' | 'local_date' | 'recipe_id'>[]
  affected_runs_omitted: number
}
export type ProposalSummary = ProposalListResponse['data']['items'][number]
export type ProposalStatus = ProposalSummary['status']
export type ProposalRevision = Schemas['RevisionSummary']
export type ProposalSession = Partial<import('./calendar').SessionFields> & {
  legacy_unstructured?: boolean
  legacy_payload?: Record<string, unknown> | null
}
export interface ProposalChange {
  change_id: string
  op: 'add' | 'modify' | 'move' | 'delete'
  session_uid: string | null
  before: ProposalSession | null
  after: ProposalSession | null
  current: ProposalSession | null
  reason: string
  decision: 'pending' | 'accepted' | 'rejected'
  material_flags: string[]
}
export interface AnchorChange {
  anchor_key: string
  kind: string
  value_low: number
  value_high: number | null
  unit: string
  protocol: string
  confidence: string
  calibrated_at: string
  supersedes_key: string | null
}
// The review components share domain renderers for calendar, interruption, and
// exception records. The remaining fields follow the generated HTTP contract.
export interface ProposalDetail extends Omit<
  Schemas['ProposalDetail'],
  | 'running_interruption'
  | 'confidence'
  | 'block_change'
  | 'anchor_changes'
  | 'changes'
  | 'exception'
  | 'event_review'
  | 'patch_resolutions'
  | 'patch'
> {
  running_interruption: ProposalInterruption | null
  confidence: Record<string, string>
  block_change: {
    decision: string
    block_uid: string | null
    version_fields: Partial<import('./blocks').BlockVersion>
  } | null
  anchor_changes: AnchorChange[]
  changes: ProposalChange[]
  exception: ProposalException | null
  event_review: ProposalEventReview | null
  patch_resolutions: ProposalPatchResolution[]
  patch: Omit<Patch, 'session_uids' | 'reassess_due'> | null
}
// The review UI always submits every selection explicitly.
export type ProposalDecision = Required<Schemas['DecisionRequest']>
export type ProposalDecisionResult = Schemas['DecisionResult']
export type ProposalDiscardResult = Schemas['DiscardResult']
