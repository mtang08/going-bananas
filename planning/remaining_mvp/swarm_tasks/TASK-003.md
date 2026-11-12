# TASK-003 — Add preservation-safe schema foundation without disabling the current app

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce; manager-supplied dependency-complete gb-mvp1-* tag; planning/remaining_mvp MVP-1.0
Wave / priority: P0-A; wave 0 (dependency_graph.md).
Dependencies: TASK-001 and TASK-002 already delivered; do not rerun
File ownership: Integration owner only: modify backend/app/models.py, backend/app/main.py, backend/migrations/env.py, backend/app/api/core.py (profile authority serialization only); create backend/app/migrations_head.py, backend/app/fit_models.py, backend/app/checkin_models.py, backend/app/calendar_models.py, backend/app/planning_models.py, backend/app/metric_models.py, backend/app/coach_v2_models.py; create backend/migrations/versions/0010_ingest_fit.py, backend/migrations/versions/0011_checkins_v2.py, backend/migrations/versions/0012_calendar.py, backend/migrations/versions/0013_blocks_goals.py, backend/migrations/versions/0014_anchors_metrics_prompts.py, backend/migrations/versions/0015_coach_v2.py; create backend/tests/unit/test_schema_models.py and backend/tests/integration/test_schema_upgrade.py.
Forbidden changes: No old migration edits, drops/renames, legacy model removal, frontend stubs, router deletion, test deletion, application-data import, lockfile changes, CLI edits or live DB operations. Existing agent_models/coaching_models stay.

## Objective and observable end state
Upgrade a populated synthetic0009 database to0015 with every legacy row/reference/payload unchanged and current app routes still functioning. New state starts authority legacy/head0. No feature cutover occurs.

## Inputs and fixed contracts
- schemas§§0–2,6–7 are normative. Distinct physical checkins_v2/checkin_v2_revisions avoid old names; new coach classes in coach_v2_models, not old coaching_models.
- Classes: FitFile,ActivityLap,ActivityWorkoutStep,ActivityStream; Checkin,CheckinRevision,SymptomReport,SessionRpe in checkin_models; CalendarVersion,CalendarSessionRevision,SessionCompletion,LegacyImportRun,LegacyImportMap,LegacyUndoRequest in calendar_models; Block,BlockVersion,BlockDecision,Goal,Event,StrengthRoutineSlot,IntensityAnchor in planning_models; MetricConfig,MetricResult,Prompt in metric_models; CoachSnapshot,CoachProposal,CoachProposalChange,CoachDecisionKey,DailyGuidance in coach_v2_models.
- Every table has UUID id via existing uuid_pk unless explicitly activity_id PK. Unqualified text means Text; dates Date, instants timezone-aware DateTime; number/version counters Integer; enum strings sized per schema (unsized categorical strings40); payload/confidence/source_refs JSONB. All fields NOT NULL unless schema says null; booleans/default arrays server defaults as well as ORM defaults. Numeric(3,1,asdecimal=False). events.name String100.
- Source provenance: fit_files additionally zip_sha256 String64, last_attempt_at timestamptz nullable,last_error String100 nullable; successful fit_sha256/profile/sdk/decoded payload must survive failed retry. These retain §6.2 metadata with stream quality_flags text[]. Snapshot/decision fingerprints, coach_decision_keys and legacy_undo_requests (§7.3) and import mappings are required now.

## Implementation procedure
1. Inspect existing migration0009 and source models; verify no local app edits. Add migration0010 down_revision0009_agent_plan. Add remaining five exact chained revisions; no parallel heads. Preserve all0001–0009 checksums.
2. Add Activity nullable timer/end/FIT/RPE fields and fit_status default not_fetched; AppState calendar_head_version Integer default0 and planning_authority default legacy, both NOT NULL. Do not change data_revision behavior.
3. Implement new tables/models exactly schemas. Model ForeignKey only within own module or models.py; add ALL cross-module real database FKs at correct later migration: Activity.fit_file_id0010, checkins_v2.prompt_id0014, calendar block/strength0013, proposal/calendar references0015. StrongWorkoutRow references exist only in migrations. Old CoachPlanRevision.plan_id remains valid.
4. Add named ck_<table>_<column> enum/range checks. Enforce RPE exactly one subject; completion ≤1 subject and zero only skipped/unknown (import linked unknown allowed); unique subject links; context tag subset; anchor unit/kind ranges; prompts NULLS NOT DISTINCT unique; metric historical expression uniqueness and partial current index per§6.3. Names uq_prompts_kind_activity_session, uq_metric_results_identity, uq_metric_results_current.
5. Late type defaults: metric strings metric_id60/method_version40/subject_key120; proposal operation32/status20; all unspecified hashes64; daily guidance decision24; timestamp defaults now() only created/recorded fields. Add profile strength schedule unchanged, no new recurrence source. No metric config seed.
6. Import modules in migrations/env.py and main.py metadata initialization without registering unfinished new API routers. Add migrations_head.EXPECTED_HEAD and change readiness literal to it. All existing routers/read APIs remain registered. Add GET/profile data.planning_authority readonly per schemas§7.2; ProfileInput ignores a supplied planning_authority field for backward-compatible GET/spread/PUT clients; authority always comes from AppState and is never writable through profile. Add test that a supplied opposite authority leaves it unchanged while ordinary profile edit succeeds. Include no-profile response.
7. Implement empty-schema downgrade guard before any destructive operation in EACH revision; if any added table has rows or added Activity/AppState fields contain nondefault data, raise RuntimeError('restore_required_nonempty_mvp_schema'). Then reverse only own additions, latest-first. Never delete legacy rows.
8. New test fixture seeds0009 profile with alternating schedule, two plans with cross-plan active_session_ids, completion link, checkin+revision, coach history and Strong workout. Snapshot source row IDs/counts/payload hashes; upgrade; compare exact equality. Run existing baseline integration flows against migrated schema.

## Tests and expected results
- `cd backend && uv run pytest tests/unit/test_schema_models.py`: unique Alembic head0015_coach_v2; all required models imported; metadata constraints present.
- `./scripts/with-mode test bash -c 'cd backend && uv run pytest tests/integration/test_schema_upgrade.py -m integration'`: guarded temporary database0009→0015, readiness200, legacy reads/writes intact, all fixture payloads identical; new authority legacy/head0.
- Fixture inserts two nullable-subject duplicate prompts → IntegrityError; RPE zero/two subjects → IntegrityError; correct one→success; completion skipped no subject→success; completed no subject→IntegrityError.
- Empty upgrade/downgrade/reupgrade works; populated new-table downgrade raises before any table changes. `make check` and `make test-integration` retain existing tests; no deletion to obtain green.

## Acceptance checklist
- [ ] Six additive revisions, single head, old data and references retained.
- [ ] Legacy app/agent/strength/checkin flows still work.
- [ ] Import/authority remains dormant; full baseline tests preserved.
- [ ] All required uniqueness/check constraints exercised, no app data touched.

## Completion report
List changed paths, exact test commands actually run and their outputs, fixture coverage, remaining device gates and blockers. No real athlete data, invented verification or design essay. Include baseline/runtime tag and resulting schema head when relevant.

## Escalation rule
If the pinned source or an exported contract differs, STOP with the exact path/signature and a short blocker. Do not invent schema, physiology, DTO, migration, UX, field observation or dependency. Historical handoff notes do not override this packet or schemas §§6–7. Tests use synthetic fixtures and a guarded disposable TEST_DATABASE_URL only; no real-mode startup, live Garmin or athlete DB. Planning approval is required before implementation begins.
