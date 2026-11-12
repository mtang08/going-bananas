export type SessionKind = 'run' | 'strength' | 'cross' | 'rest' | 'mobility'
export type Certainty = 'committed' | 'provisional'
export type StepType = 'warmup' | 'work' | 'recovery' | 'cooldown'
export interface StepTarget { modality: 'speed' | 'hr' | 'effort'; low: number | null; high: number | null; effort_cue: string | null }
export interface PlannedStep { type: StepType; duration_type: 'time' | 'distance'; duration_value: number; target: StepTarget | null }
export interface RepeatBlock { type: 'repeat'; count: number; steps: PlannedStep[] }
export type StructureItem = PlannedStep | RepeatBlock
export interface ExpandedStep extends PlannedStep { step_path: string; expanded_step: number; repeat_index: number | null }
export interface SessionFields { local_date: string; slot: number; kind: SessionKind; recipe_id: string | null; custom: boolean; intent: string; placeholder: boolean; locked: boolean; planned_duration_s: number | null; planned_distance_m: number | null; structure: StructureItem[] | null; strength_slot_id: string | null; notes: string | null }
export interface SessionState extends SessionFields { id: string; certainty: Certainty; legacy_unstructured: boolean; legacy_payload: Record<string, unknown> | null; session_uid: string; revision: number; calendar_version_number: number; deleted: boolean; is_original: boolean; changed_by_version: number }
export type CompletionStatus = 'completed_as_planned' | 'completed_modified' | 'partial' | 'moved' | 'skipped' | 'extra' | 'unknown'
export type MatchMethod = 'explicit' | 'auto_same_day' | 'confirmed_move' | 'user_marked' | 'none'
export type ModificationReason = 'symptom_onset' | 'fatigue' | 'illness' | 'schedule' | 'weather' | 'equipment' | 'other'
export interface Completion { id:string;input_version:number; session_uid: string; activity_id: string | null; strong_workout_id: string | null; manual_session_id: string | null; status: CompletionStatus; match_method: MatchMethod; modification_reason: ModificationReason | null; reason_note: string | null; version: number; updated_at: string; local_date: string | null } // local_date [DTO fixed here]: actual subject date when linked, else planned date
export interface CalendarView { today: string; timezone: string; start: string; end: string; version: number; head: number; undo: {target_version:number;eligible:boolean;protected_session_uids:string[]} | null; last_planned_date: string | null; sessions: SessionState[]; completions: Completion[] } // today/timezone/start/end [DTO fixed here]; head 0 = no calendar yet
export type CalendarVersionKind = 'bootstrap' | 'manual_edit' | 'proposal_accept' | 'rollback' | 'legacy_import'
export interface CalendarVersion { id: string; number: number; parent_number: number | null; kind: CalendarVersionKind; actor: 'system' | 'user' | 'coach'; reason: string | null; proposal_id: string | null; restored_from_number: number | null; block_version_id: string | null; created_at: string }
export type ChangeOp = 'add' | 'modify' | 'move' | 'delete'
export interface CalendarDiff { changes: { session_uid: string; op: ChangeOp; before: Partial<SessionFields> | null; after: Partial<SessionFields> | null }[] }
export interface CalendarEdit { op: ChangeOp; session_uid?: string; fields: Partial<SessionFields> }
export interface CalendarEditsRequest { expected_head: number; edits: CalendarEdit[]; reason?: string }
export interface CalendarRollbackRequest { expected_head: number; to_version: number; reason?: string }
export interface CalendarBootstrapRequest { anchor_date: string; pattern: { quality: 1; long: 1 }; start_date: string }
export interface CalendarWriteResult { version: number; kind: CalendarVersionKind; stale_proposals: string[]; preserved_session_uids: string[] }
export interface CompletionPut { expected_version?: number; activity_id?: string | null; strong_workout_id?: string | null; manual_session_id?: string | null; status?: 'skipped' | 'unknown'; modification_reason?: ModificationReason | null; reason_note?: string | null }
export const RECIPE_LABELS: Record<string, string> = { REC001: 'Easy run', REC002: 'Long run', REC003: 'Threshold intervals', REC004: 'Steady / tempo', REC005: 'VO2 intervals', REC006: 'Short intervals / fartlek', REC007: 'Strides', REC008: 'Hills', REC009: 'Benchmark / race-specific', REC010: 'Low-impact substitution' }
export type SessionMarker = 'planned' | 'completed' | 'modified' | 'partial' | 'moved' | 'missed' | 'not_recorded'
export const MARKER_LABELS: Record<SessionMarker, string> = { planned: 'Planned', completed: 'Completed', modified: 'Completed, modified', partial: 'Partial', moved: 'Moved', missed: 'Missed', not_recorded: 'Not recorded' }
