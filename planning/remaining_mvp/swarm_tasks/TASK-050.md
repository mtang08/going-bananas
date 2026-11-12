# TASK-050 — Stage P0-A pages without replacing the current planning experience

Baseline: main `5ebf981aa4517f4f73f3c97aa5d43232204466ce`; spec planning/remaining_mvp MVP-1.0; supplied dependency-complete gb-mvp1-* runtime tag.
Wave / priority: P0-A; wave 6 (dependency_graph.md).
Dependencies: TASK-040,041,042,043,044,045 and earlier DAG dependencies.
File ownership: `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/tests/app.test.tsx`, `e2e/p0a.spec.ts`, `scripts/smoke.py`, `scripts/verify-demo.py`, `scripts/browser-smoke.mjs`, `backend/app/cli.py` (seed-demo only), `backend/app/demo_seed.py`.
Forbidden changes: existing page files, api.ts, backend services/models/migrations/routers, existing dashboard e2e deletion. No installed skill changes.

## Objective and observable end state
Legacy authority keeps working Overview/Coach/Cycle/Settings/check-in navigation. Disposable demo/test fixtures with calendar authority expose Home/Calendar/Trends/activity and new planning forms. No real authority switch occurs before068. Existing tests remain, new synthetic tests are additive.

## Inputs and fixed contracts
schemas§§6–7 authority/envelope;039 helper/DTOs;040 Home(unit,onCheckin);041 Calendar(unit);042 Activity(activityId,unit,onCheckin);043 Trends(unit);044 PlanningSettings(unit,setUnit,onCheckin);045 CheckinModalV2(request,close). Existing Settings/CheckinModal/Coach/Cycle stay unchanged. G2 gates device acceptance, not synthetic implementation.

## Implementation procedure
1. App reads `profile.data.data.planning_authority` from GET/profile (TASK003) before choosing planning views. Legacy retains existing page list and old modal. Calendar authority gets Home, Calendar, Trends, History, Strength, Data & settings; Data & settings renders PlanningSettings alongside existing Settings for sync/profile/rotation management. New forms use CheckinModalV2; legacy handlers keep old modal. No URL-only authority bypass. Readiness/mode/unit/mobile behavior stays.
2. Export `parseHash(hash,authority)` returning page/id. Legacy supports overview,coach,cycle,history,strength,settings; calendar supports home,calendar,trends,history,strength,settings,activity/<encoded-id> plus coach read-history compatibility. Unknown/malformed URI -> authority default; catch decodeURIComponent errors. Listen/unlisten hashchange; clicks update route/hash and close menu. Route on startup only after authority resolves.
3. Add scoped styles for today-card,14-day strip,calendar-day,session-row,version-row,trend-grid and new forms using existing CSS tokens. Grid7columns desktop,2below700px. Preserve current page selectors. Add accessible names/test IDs from page packets; no new CSS framework.
4. Extend App tests with separate legacy/calendar-authority fixtures. Legacy confirms Coach/Cycle/current check-in unchanged. Calendar checks Home, deep-link Activity,unknown hash,nav/hash,modalV2 and existing Settings controls. Use expected DTOs fromschemas§6, no404-as-empty guidance.
5. Demo seed below is only for disposable calendar-authority demo fixtures. Preserve old seed behavior under legacy authority; use a `--calendar-preview` flag on seed-demo to select new fixture. This flag rejects real mode and any populated legacy dataset. Seed profile/calendar once; repeated invocation returns identical totals. No automatic user-database reset.

### D. Demo seed — `backend/app/demo_seed.py` (create) and `backend/app/cli.py`
1. `cli.py`: delete `_demo_records()`. Replace the body of the `seed-demo` branch with: demo-mode check unchanged; `from app.demo_seed import seed_demo`; `today = local_date(datetime.now(UTC), ZoneInfo("America/New_York"))` (`app.services.timezone.local_date`); `with SessionLocal.begin() as session: counts = seed_demo(session, settings.private_dir, today)`; `print(json.dumps(counts, sort_keys=True))`. Remove imports that become unused (ruff).
2. `seed_demo(session: Session, private_dir: Path, today: date) -> dict[str, int]`. `T = today`; `tz = ZoneInfo("America/New_York")`; `at(d, hh, mm)` = local `d hh:mm` in `tz` converted to UTC. All rows from the demo account use `account_scope="synthetic-demo"`, `source_kind="demo_fixture"`. Exact imports: app.models AppState,ProfileVersion,Activity,RecoveryObservation,CoverageInterval; app.fit_models ActivityLap,ActivityWorkoutStep,ActivityStream; app.checkin_models Checkin,SymptomReport,SessionRpe; app.calendar_models CalendarVersion,CalendarSessionRevision,SessionCompletion; app.planning_models StrengthRoutineSlot; app.metric_models MetricResult,Prompt. No table-name introspection.
3. `first_run = (AppState.calendar_head_version == 0)`. Steps 4, 5, 8, 9, 10 run only when `first_run`. Steps 6, 7 are idempotent (insert-if-absent) and run every time. Steps 11, 12 run every time (idempotent per QA "Repeated invocations").
4. Profile: add `ProfileVersion(version = latest+1 or 1, effective_at=now, timezone="America/New_York", cycle_anchor=T−28, anchor_confirmed=True, strength_days_confirmed=True, scheduled_strength_days=[0, 4], facts=<latest facts or {}>, preferences={**latest preferences, "weekly_review_weekday": 6}, unknowns=<latest or []>)`.
5. Strength routine (`strength_routine_slots`): "Full body A" `default_weekday=0`, "Full body B" `default_weekday=4`; both `lower_body_cost="moderate"`, `typical_duration_s=3600`, `main_lower_body_lifts=[]`, `active=True`, `version=1`.
6. Activities via `import_activity_page(session, private_dir, records, account_scope="synthetic-demo", source_kind="demo_fixture")`. `activityId = 3000 + days_ago`. Runs: every cycle day `T−28, T−26, …, T−2` except `T−4` (13), plus the extra run `T−1`. Start `at(T−n, 7, 0)`; `T−1` starts `at(T−1, 7, 30)`. Record keys: `activityId`, `startTimeGMT` (ISO `…Z`), `activityType.typeKey` (`running`; `treadmill_running` for `T−20`), `distance` (omit for `T−20`), `elapsedDuration` = `movingDuration` = timer seconds. Then on each `activities` row set `timer_s`, `end_at = start_at + elapsed_s`, `fit_status="decoded"` (`fit_file_id` stays null). Per run:

   | Day | Timer s | Speed m/s | HR bpm | Extra rows |
   | --- | --- | --- | --- | --- |
   | easy runs (all others) | 1800 | 2.8 | 140 | 1 lap |
   | `T−2` long | 4800 | 2.8 | 140 | 1 lap |
   | `T−20` treadmill | 1800 | none (speed/distance null) | 140 | 1 lap, `distance_m` null |
   | `T−10` | 1800 | 2.8 | 140 | `activities.workout_rpe = 4.0 (decoded canonical value; raw FIT fixture is 40)`; `session_rpe` (`source="garmin_fit"`, `rpe=4.0`, `collected_at=end_at`, `collection_delay_s=0`) |
   | `T−6` structured | 2880 | per lap | per lap | 10 laps + 5 workout steps (below) |
   | `T−12` mismatch | 3300 | per lap | per lap | 12 laps + 5 workout steps (below) |
   | `T−1` extra | 1800 | 2.8 | 140 | 1 lap; no RPE |

   - Single lap: `lap_index=0`, `start_at`, `timer_s`, `elapsed_s` = timer, `distance_m` = timer × speed (null for treadmill), `avg_speed_mps` = speed, `avg_hr_bpm` = `max_hr_bpm` = HR, `lap_trigger="session_end"`, `wkt_step_index=None`.
   - `T−6` laps in order: warm-up 600 s @2.8 HR 140 (`wkt_step_index` 0); then for reps k = 1…4: work 300 s @ [3.6, 3.6, 3.4, 3.6][k−1] HR 156+2k (idx 1), recovery 120 s @2.5 HR 140 (idx 2); cool-down 600 s @2.8 HR 140 (idx 4). `lap_trigger` `"time"`, last lap `"session_end"`; `start_at` cumulative.
   - `T−6` workout steps (`activity_workout_steps`): mi0 `step_name="Warm up"`, `intensity="warmup"`, `duration_type="time"`, `duration_value=600`; mi1 `"Work"`, `"active"`, `"time"`, 300, `target_type="speed"`, `target_low=3.4`, `target_high=3.8`; mi2 `"Recover"`, `"recovery"`, `"time"`, 120; mi3 `step_name=None`, `intensity=None`, `duration_type="repeat_until_steps_cmplt"`, `duration_value=None`, `repeat_from=1`, `repeat_count=4`; mi4 `"Cool down"`, `"cooldown"`, `"time"`, 600.
   - `T−12`: same, but 5 reps at 3.5 m/s (HR 158) and mi3 `repeat_count=5`.
   - Streams (`activity_streams`, every run): `t_s = 0…timer−1`; per second the `hr_bpm` and `speed_mps` of the lap covering it; `distance_m` cumulative sum of speed (null arrays for treadmill speed/distance); `altitude_m` and `cadence` all null; `timer_on=[[0, timer]]`; `sample_count=timer`; `max_gap_s=1`.
   Insert laps/steps/streams/RPE only when the activity has none yet.
7. Recovery and coverage (insert-if-absent): `account = _account(session, "garmin", "synthetic-demo")`. For `i` in 1…42, `d = T−i`, skipping `T−4` and `T−6`: `recovery_observations` rows (`source_record_id=None`, `source_revision="demo-seed-v1"`, `source_date=d`): sleep `25200 + (i % 3) * 300`; hrv `60 + (i % 3)`; resting_hr `52 + (i % 2)` (sleep:s/main_sleep_duration/garmin_sleep_calendar_date; hrv:ms/last_night_average/garmin_hrv_calendar_date; resting_hr:bpm/daily_resting/garmin_heart_rate_calendar_date). `coverage_intervals` for `activities`, `sleep`, `hrv`, `resting_hr`: `start_date=T−42`, `end_date=T−1`, `observed_start/observed_end` same, `status="complete"`, `completed_at=now`, `reason=None`, `fully_enumerated=True`.
8. Check-in (`checkins_v2` + `symptom_reports`): `kind="exception"`, `observed_at=at(T−5, 8, 0)`, `idempotency_key="demo-seed-checkin-t5"`, `context_tags=[]`, other fields null; symptom `site="posterior tibial tendon"`, `side="left"`, `severity=2.0`, `timing="next_morning"`.
9. Prepare `history_edits` as one add operation per item below: `{op:"add",session_uid:str(uuid5(NAMESPACE_URL,f"going-bananas-demo:{local_date}:{kind}:{slot}")),fields:...}` using uuid.uuid5 and uuid.NAMESPACE_URL; duplicate UIDs are an error. No random historical identity. Each operation has fields {local_date,slot,kind,recipe_id,custom:False,intent,planned_duration_s,planned_distance_m:None,structure,strength_slot_id,notes:None}.
10. Only on first_run call `app.services.calendar.seed_demo_calendar(session,anchor_date=T−28,start_date=T,now=at(T,12,0),history_edits=history_edits)`. TASK012 helper creates v1 bootstrap and v2 historical fixture edits; explicitly demo/test-only, permits these historical dates, requires calendar authority and empty head. Do not call apply_edits for historical setup. Exact items:
    - Runs (slot 0) on `T−14, T−10, T−8, T−4`: `REC001`, intent `"Easy run"`, 1800, `structure=None`; `T−2`: `REC002`, `"Long run"`, 4800; `T−12` and `T−6`: `REC003`, intent `"Threshold 4 × 5 min"`, 2880, structure `[{"type":"warmup","duration_type":"time","duration_value":600,"target":{"modality":"effort","low":None,"high":None,"effort_cue":"easy"}}, {"type":"repeat","count":4,"steps":[{"type":"work","duration_type":"time","duration_value":300,"target":{"modality":"effort","low":None,"high":None,"effort_cue":"threshold"}}, {"type":"recovery","duration_type":"time","duration_value":120,"target":{"modality":"effort","low":None,"high":None,"effort_cue":"easy jog"}}]}, {"type":"cooldown","duration_type":"time","duration_value":600,"target":{"modality":"effort","low":None,"high":None,"effort_cue":"easy"}}]`.
    - Strength (slot 1): every Monday in `[T−14, T−1]` → slot "Full body A", every Friday → "Full body B"; `kind="strength"`, `recipe_id=None`, intent = slot label, 3600, `strength_slot_id` = that slot's id.
11. Call app.services.metrics.engine.recompute(session, 'all:'+ (T−42).isoformat()), then TASK030 ensure_windows(session,as_of=T). No commit inside services. Assert T−6 planned session links to T−6 activity through canonical matching; mismatch fails the seed test.
12. Call app.services.prompts.generate_prompts(session, now=datetime.now(UTC)); no commit inside service.
13. Return totals (whole-table `count(*)`, not deltas), keys sorted: `activities`, `activity_laps`, `activity_streams`, `activity_workout_steps`, `calendar_session_revisions`, `calendar_versions`, `checkins_v2`, `coverage_intervals`, `metric_results`, `prompts`, `recovery_observations`, `session_completions`, `session_rpe`, `strength_routine_slots`.


6. Add e2e/p0a.spec.ts using acceptance.md exact eight binding names and fixture§1.3. Tests query dynamic today/head; check14days,scheduled prompts,manual edit/protected undo,matching and mismatched structured workouts,persisted exception guidance,recovery missing nights,anchor-enabled intensity and local-only requests. Protected undo compares eligible future sessions and preserved historical/completed/locked IDs, never all-row byte equality. Seeded missing run T−4,manual/decoded Garmin RPE subject T−10; missing recovery nights T−4/T−6 remain independent.
7. Keep existing dashboard.spec.ts and legacy coverage. smoke.py branches on planning_authority: existing paths remain; calendar adds calendar/versions,prompts,coach/v2/daily,metrics/windows,recovery,anchors,goals,events,routine,blocks. Privacy canaries apply all responses. browser-smoke.mjs retains real read-only release use only; synthetic browser gates use Playwright18000.
8. Add --base-url to scripts/verify-demo.py (default existing loopback8000), validate loopback and derive API base plus Origin header from the supplied base URL; synthetic gate passes18000. verify-demo adds wrong-head409,edit/undo lineage,bootstrap conflict,check-in replay and guidance reload,structured reps/RPE bounds. Use /v2/checkins and pure GET /coach/v2/daily. Old context/agent/history checks remain in legacy mode.

## Tests and expected results
Frontend App tests/build; make check; existing dashboard e2e on legacy fixture; eight p0a tests on separate calendar fixture; smoke/verify-demo on each disposable mode. Seed twice -> equal totals; snapshot state not reset between retry tests. No real data or G2 inference.

## Acceptance checklist
- [ ] Current legacy pages/writes remain operational until068.
- [ ] Calendar preview requires explicit isolated fixture authority.
- [ ] Guidance persists across reload; repetitions interleave; missing prompt within7days.
- [ ] Old and new suites pass; no deleted legacy tests.

## Completion report
Changed paths; test outputs; both seed totals; exact authority fixture; pending real-device gate.

## Escalation rule
Stop on missing DTO/service or authority mismatch; do not change runtime source authority or discard existing data.

## Isolated browser runtime (binding)
Synthetic gates use the manager-owned isolated demo environment/database. Run `make check` to build frontend, then serve that built frontend directly with `APP_PORT=18000 ./scripts/with-mode demo bash -c 'cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 18000'`. Run browser tests with `PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000`; no Vite dev proxy and no scripts/serve.py. Existing real app on8000 is untouched. Smoke uses `python3 scripts/smoke.py --mode demo --base-url http://127.0.0.1:18000`; synthetic verify-demo uses the same base URL. browser-smoke.mjs remains real read-only release verification at8000, never part of this synthetic gate.
