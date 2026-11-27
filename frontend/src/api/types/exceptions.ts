import type { components } from '../generated/exceptionStartup'

type Schemas = components['schemas']

export type Category = Schemas['ExceptionCategory']
export type Severity = Schemas['ExceptionSeverity']
export type Finding = Schemas['ExceptionFinding']
export type Patch = Schemas['ExceptionPatch']
export type PatchStatus = Patch['status']
export type Ladder = Patch['ladder_level']
export type ExceptionsView = Schemas['ExceptionView']
export type DismissFinding = Schemas['DismissFinding']
export type ResolvePatch = Schemas['ResolvePatch']

export interface SessionPatchRef {
  patch_id: string
  proposal_id: string
  reassess_on: string
  status: PatchStatus
}
export type BenchmarkOutcome = 'progress' | 'consolidate' | 'recalibrate_only' | 'inconclusive'
export interface ProposalException {
  finding_ids: string[]
  category: Exclude<Category, 'post_event'>
  severity: Severity
  confidence: 'low' | 'moderate' | 'high'
  triggering_evidence: string
  relevant_context: string | null
  ladder_level: Ladder
  patch_window: { start: string; end: string }
  unchanged: { session_uid: string; reason: string }[]
  reassess_on: string
  monitor: string[]
  return_criteria: string[]
  escalate_criteria: string[]
}
export interface ProposalEventReview {
  event_id: string | null
  activity_id: string | null
  outcome: BenchmarkOutcome | null
  compared_with: string | null
  pacing: string
  effort_and_limiter: string
  conditions: string | null
  symptoms: string | null
  recovery_observation: string
  recalibration: 'none' | 'propose_anchors' | 'defer'
  training_implication: string
}
export interface ProposalPatchResolution {
  patch_id: string
  status: 'resolved' | 'escalated'
  note: string
}
