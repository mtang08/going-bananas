export type GuidanceDecision = 'proceed' | 'modify' | 'reschedule' | 'rest' | 'seek_clinical_input'
export interface DailyGuidance { id: string; created_at: string; input_hash: string; local_date: string; checkin_id: string | null; engine: string; decision: GuidanceDecision; session_uid: string | null; rationale: string; missing_inputs: string[]; coach_review_suggested: boolean; trigger_codes: string[] }
export const DECISION_LABELS: Record<GuidanceDecision, string> = { proceed: 'Proceed', modify: 'Modify', reschedule: 'Reschedule', rest: 'Rest', seek_clinical_input: 'Seek clinical input' }
