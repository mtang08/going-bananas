# TASK-014 — Preserve recurrence while adding strength templates and planning registries

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce; manager-supplied dependency-complete gb-mvp1-* tag; planning/remaining_mvp MVP-1.0
Wave / priority: P0-A; wave 1a (dependency_graph.md).
Dependencies: TASK-003
File ownership: Create backend/app/services/strength_routine.py and backend/app/api/planning.py; create backend/tests/unit/test_strength_routine.py, backend/tests/integration/test_planning_api.py.
Forbidden changes: No profile schema/schedule redesign, Garmin/Strong imports, automatic schedule changes, calendar engine, main/CLI/frontend edits. No block mutation API; proposals own block writes.

## Objective and observable end state
Confirmed alternating strength/mobility schedule remains exactly unchanged. Templates can be edited/versioned independently. Suggestions appear only when no template and never replace confirmed days.

## Inputs and fixed contracts
schemas§§2.4,3.4,6.1. APIs /strength-routine GET/PUT; /goals and /events GET/POST/PATCH/{id}; /blocks/active GET object|null and /blocks/{block_uid}/history GET{items}. Session-level service exports routine_view(session)->dict, replace_routine(session,expected_version:int,slots:list[dict])->dict, suggest_slots(workouts:list[dict])->list[dict], confirmed_schedule(session)->dict, routine_occurrences(session,start:date,end:date)->list[dict]. No service commits. All new writes authoritycalendar required; legacy profile editor untouched.

## Implementation procedure
Global lock invariant: every new writer acquires advisory71382413 before app_state FOR UPDATE and before source mutations; never defer advisory until030 after taking app_state. TASK-030 owns coordinated db.bump_data_revision and source-change coalescing (schemas§7.2).

1. confirmed_schedule projects exact current profile fields§6.1; empty profile uses existing profile defaults. routine_occurrences calls existing domain.cycle.recurring_sessions with current profile and inclusive range; decorate strength occurrences with template by stable slot order, never shift date to default_weekday; preserve mobility and optional flags. Respect profile effective day and no hidden future extension.
2. Version=max all strength_routine_slots.version, zero if none. Current slots=maxversion AND active; keep every older row unchanged. replace_routine locks advisory71382413 then app_state, checks expected_version, inserts complete new version and marks source scope for030 coalesced bump. Empty replacement422 routine_empty; label nonblank≤40, weekday0..6, lower_body_cost low/moderate/high, duration null or positive integer, lift strings nonblank. Do not alter prior active flags (maxversion selects current).
3. GET when no template returns suggested=true/version0 and suggestion slots (id null allowed until persistence); source last56 inclusive days of resolved Strong workouts with no future dates. Group workout_name, top2 by count desc then name asc; modal weekday ties earliest; median known durations nearest300 half-up; top3 unique lower-body lift names by frequency desc/name asc using casefold keywords squat,deadlift,lunge,rdl,leg press,hip thrust,step up,leg curl. Cost moderate default. Pad Full body A Monday and Full body B Friday only as template suggestions. Confirmed schedule response still controls actual occurrence dates.
4. Slot assignment for routine_occurrences: enumerate each week's strength dates chronologically and alternate sorted template labels cyclically, resetting each Monday; templates never create extra days. For partial weeks compute position from full Mon–Sun recurrence to avoid shifting template assignment by query range. With no persisted templates omit strength_slot_id and label from suggestion index only for display, never silently confirm.
5. Goal POST creates version1/statusactive; PATCH requires expected_version, permits text/horizon/priority/status and preserves others. Text nonblank, priority≥1. Event name nonblank, date ISO, optional distance/result positive ints, priority/status enums. GET deterministic priority/date then id. Missing id404; version conflict409; extra fields422. Each mutation marks source scope for030; routes never compute metrics.
6. Blocks read latest active/consolidating version, plus ordered immutable history. No block writes here. Serialization uses schema field names and created_at; history wrapper{items}. API routers mounted030, no competing /strength/history route ownership.

## Tests and expected results
`cd backend && uv run pytest tests/unit/test_strength_routine.py`: two workouts A Mon3600 with Squat/RDL, B Fri3300 Deadlift/Lunge→these exact labels/days/durations/lifts; median3450→3600 half-up; frequency ties lexical. Empty input→two padded suggestions. No source value interpreted as known weight/unit.
`./scripts/with-mode test bash -c 'cd backend && uv run pytest tests/integration/test_planning_api.py -m integration'`: profile alternating WeekA2026-11-02 daysMon/Fri,WeekB Tue/Sat plus mobility→same occurrence dates before/after PUT templates; all profile fields byte-equivalent. PUT expected0 createsversion1; stale0→409; newversion2 leavesversion1 rows intact. Goal/event optimistic updates and empty block null/history wrapper. Legacy authority rejects writes but reads work.

## Acceptance checklist
- [ ] Confirmed recurrence source and editor preserved.
- [ ] Templates append-only by full version, optimistic concurrency enforced.
- [ ] Suggestions advisory and deterministic; no inferred exercise doses.
- [ ] Goals/events/read-only blocks match wire contracts.

## Completion report
List changed paths, exact test commands actually run and their outputs, fixture coverage, remaining device gates and blockers. No real athlete data, invented verification or design essay. Include baseline/runtime tag and resulting schema head when relevant.

## Escalation rule
If the pinned source or an exported contract differs, STOP with the exact path/signature and a short blocker. Do not invent schema, physiology, DTO, migration, UX, field observation or dependency. Historical handoff notes do not override this packet or schemas §§6–7. Tests use synthetic fixtures and a guarded disposable TEST_DATABASE_URL only; no real-mode startup, live Garmin or athlete DB. Planning approval is required before implementation begins.
