import type { components as Proposals } from '../generated/coachProposals'
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
export type ProposalException = Proposals['schemas']['ExceptionBlock']
export type ProposalEventReview = Proposals['schemas']['EventReview']
export type ProposalPatchResolution = Proposals['schemas']['PatchResolution']
