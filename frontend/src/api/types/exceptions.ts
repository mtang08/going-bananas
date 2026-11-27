import type { components } from '../generated/coachProposals'

export type Category =
  | 'symptoms_illness'
  | 'training_response'
  | 'accumulated_fatigue'
  | 'calendar_disruption'
  | 'post_event'
export type Severity = 'observe' | 'caution' | 'hold' | 'escalate'
export type FindingStatus = 'open' | 'addressed' | 'reviewed' | 'resolved' | 'dismissed' | 'expired'
export type PatchStatus = 'open' | 'resolved' | 'escalated' | 'superseded'
export type Ladder = 'current_session' | 'next_session' | 'next_days' | 'committed_window' | 'block'
export interface EvidenceItem {
  type:
    | 'checkin'
    | 'symptom'
    | 'activity'
    | 'session'
    | 'rpe'
    | 'recovery_night'
    | 'event'
    | 'profile'
    | 'block'
  id: string | null
  at: string
  detail: Record<string, unknown>
}
export interface Finding {
  id: string
  rule_code: string
  category: Category
  severity: Severity
  status: FindingStatus
  entity_key: string
  summary: string
  evidence: EvidenceItem[]
  evidence_at: string
  first_seen_at: string
  last_seen_at: string
  patch_id: string | null
  version: number
  is_new_since_last_review: boolean
}
export interface Patch {
  id: string
  proposal_id: string
  calendar_version_number: number
  category: Category
  severity: Severity
  ladder_level: Ladder
  window_start: string
  window_end: string
  reassess_on: string
  monitor: string[]
  return_criteria: string[]
  escalate_criteria: string[]
  unchanged: { session_uid: string; reason: string }[]
  status: PatchStatus
  resolved_at: string | null
  resolved_by: 'coach' | 'athlete' | null
  resolution_note: string | null
  created_at: string
  version: number
  session_uids: string[]
  reassess_due: boolean
}
export interface Recommendation {
  operation: 'exception_review' | 'review_training_block' | 'post_event_review'
  reason: string
  finding_ids: string[]
  prompt: string
}
export interface ExceptionsView {
  rule_version: string
  findings: Finding[]
  patches: Patch[]
  review_recommended: Recommendation[]
  counts: Record<Severity, number>
}
export interface CheckinExceptions {
  new_finding_ids: string[]
  review_recommended: Recommendation[]
}
export interface SessionPatchRef {
  patch_id: string
  proposal_id: string
  reassess_on: string
  status: PatchStatus
}
export type BenchmarkOutcome = 'progress' | 'consolidate' | 'recalibrate_only' | 'inconclusive'
export type ProposalException = components['schemas']['ExceptionBlock']
export type ProposalEventReview = components['schemas']['EventReview']
export type ProposalPatchResolution = components['schemas']['PatchResolution']
