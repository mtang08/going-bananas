# Going Bananas — acceptance, fixtures, QA (MVP-1.0)

Defines how P0-A and P0-B are proven done (`prd.md` §8). Commands run from the repo root of the integration checkout unless stated. `T` = today in the profile timezone (America/New_York). Fixture behaviors below are binding; exact function names/paths are pinned in the owning packets. Readiness checks ensure each behavior has an assigned test.

## 1. Fixtures

### 1.1 Rules for all fixtures
- Synthetic only. Never copy real FIT bytes, Personal API responses, Strong CSV rows, check-ins, or GPS into the repo (`worker_instructions.md` §5).
- Metric fixtures are built **inline in the owning test file** with local helper functions (no shared fixture module, so no cross-task file ownership). Inputs are rows/dataclasses (`activity_streams`, `activity_laps`, `activity_workout_steps`, `DecodedFit`), not FIT bytes.
- FIT byte fixtures exist only in `backend/tests/fixtures/fit/` (TASK-004) and only exercise the decoder.
- Every fixture test asserts the Track A general contract (`going_bananas_metrics/validation_cases.md` "General test contract"): deterministic output on rerun, `source_refs` present, units, local-date assignment, `status`/`quality_status`, reason codes, raw rows unchanged, upsert idempotence.

### 1.2 Track A fixture → task map

| Fixture | P0 owner task / test file | Required P0 assertions (metrics.md wins over research text) |
| --- | --- | --- |
| A1 steady easy, 2,700 s timer, 3.0 m/s, HR 142→145 | TASK-021 `test_intensity.py::test_a1_steady_easy_all_easy`; TASK-020 `test_volume.py::test_a1_timer_duration_2700`; TASK-025 `test_planned_actual.py::test_a1_duration_met` | anchors hr_aerobic_upper 150, hr_threshold_lower 165 → hr easy_s = 2,700, moderate_s = high_s = 0, coverage good; volume duration 2,700 s; duration_ratio 1.0 → `met`. Decoupling/comparable-effort parts: P1, not tested |
| A2 HR drift / decoupling | — | P1 metric `aerobic_decoupling` not built |
| A3 8×60 s work / 90 s recovery | TASK-022 `test_intervals.py::test_a3_short_reps_hr_not_reported` | step_completion_ratio 1.0 → `met`; per-rep speed reported; HR summary absent for every rep (work step < 180 s); no fail from HR |
| A4 50 min elapsed / 40 min timer, one 20 s unexplained gap | TASK-021 `test_intensity.py::test_a4_gap_over_10s_unknown`; TASK-020 `test_volume.py::test_a4_uses_timer_not_elapsed` | duration 2,400 s (not 3,000); 20 s gap > `max_record_gap_s` 10 → 20 s `unknown`; easy+moderate+high+unknown = timer-on seconds ±1 s |
| A5 treadmill, HR present, no speed | TASK-021 `test_intensity.py::test_a5_treadmill_speed_not_assessable`; TASK-020 `test_volume.py::test_a5_missing_distance_not_zero` | speed modality `not_assessable` reason `NO_SPEED_SAMPLES` (defined in metrics.md); hr modality available; distance `missing`, never 0 |
| A6 hills/heat comparison | — | P1 (`comparable_effort_speed`) |
| A7 HR spike, GPS teleport | TASK-021 `test_intensity.py::test_a7_artifacts_excluded` | fixture uses HR 235 bpm (outside 30–230) and speed 12 m/s for 5 s each → samples `invalid`, excluded seconds reported, coverage label recomputed. The research's 220 bpm spike is **not** flagged until G2 plausibility thresholds (`metrics.md` §5) |
| A8 duplicate imports | TASK-010 `test_fit_ingest.py::test_a8_same_fit_twice_idempotent`; existing `tests/integration/test_flow.py::test_import_summary_feedback_and_privacy` | second ingest: 0 new `fit_files`/laps/streams rows; `fit_sha256` unchanged; one canonical activity in volume |
| A9 7-day window, 2 nights missing | TASK-024 `test_recovery.py::test_a9_missing_nights_not_zero` | 2 nights status `missing`, z = null; summary `quality_status=limited`; no readiness field in result |
| A10 DST + midnight crossing | TASK-002 `test_timezone.py::test_a10_dst_fall_back_local_date`; TASK-020 `test_volume.py::test_a10_window_bounds_dst` | runs at 2026-11-01T05:30Z (01:30 EDT) and 06:30Z (01:30 EST) → both local date 2026-11-01, both kept; run starting 2026-11-03T04:50Z (23:50 EST) → 2026-11-02; w7 as of 2026-11-03 = local dates 2026-10-28…2026-11-03 |
| A11 intervals, no workout steps | TASK-022 `test_intervals.py::test_a11_no_steps_not_assessable` | `not_assessable`; no reps inferred from HR |
| A12 planned 70 min long, stopped at 48 min, symptoms | TASK-025 `test_planned_actual.py::test_a12_symptom_modification`; TASK-023 `test_symptoms.py::test_a12_timeline_immediate_and_24h` | duration_ratio 0.686 → `partially_met`; with modification_reason `symptom_onset` → `completed_modified`; timeline shows 2 reports (`immediately_after`, `hours_24_48`); no composite score |
| D9 watch mismatch | TASK-022 `test_intervals.py::test_d9_watch_workout_mismatch` | plan 4 work steps, watch 5 → `not_assessable`, `WATCH_WORKOUT_MISMATCH`, both step lists in result |

### 1.3 Demo seed (`make seed-demo`; owned by TASK-050, `backend/app/cli.py` seed only)
Rerunning on a seeded DB changes no row counts. All rows `source_kind=demo_fixture`, account scope `synthetic-demo`. Required state (relative to `T` at seed time):

| Item | Required content |
| --- | --- |
| Profile | timezone America/New_York; cycle anchor `T−28`, confirmed; `weekly_review_weekday` 6 |
| Strength routine | 2 slots: "Full body A" Mon, "Full body B" Fri, `lower_body_cost=moderate`, 3,600 s |
| Runs | one activity on each cycle day `T−28 … T−2` except `T−4` (13 runs), `timer_s` set, easy 1,800 s at 2.8 m/s; plus an off-cycle **extra** run `T−1`, 1,800 s, ending 08:00 local, no RPE |
| Long run | `T−2`, 4,800 s, linked to a REC 002 session |
| Structured | `T−6`: REC 003 plan 10 min warm-up, 4×300 s work / 120 s recovery, cooldown; laps carry matching `wkt_step_index`; rep speeds 3.6, 3.6, 3.4, 3.6 m/s |
| Mismatch | `T−12`: plan 4 work steps, watch steps 5 → `WATCH_WORKOUT_MISMATCH` |
| Garmin RPE | `T−10` run has raw FIT `workout_rpe`40, imported CR10 value4.0 (`session_rpe.source=garmin_fit`) |
| Treadmill | `T−20`: HR present, no speed/distance samples |
| Missed | `T−4` planned run, no activity; dataset coverage recorded through `T−1` → `NO_ACTIVITY_FOUND` + `missing_activity` prompt |
| Recovery | nights `T−42 … T−1`; `T−4`, `T−6` missing; all others near-constant (baseline `established`, no adverse flags) |
| Symptoms | exception check-in `T−5`: left posterior tibial, severity 2.0, `next_morning` |
| Calendar | head covers `T−14 … T+13`; ≥ 2 versions (v1 `bootstrap`); every past planned run linked or `unknown` |
| Anchors | none (intensity `not_assessable` until the e2e records one) |
| Coach | no proposals, no block, KB present |

Prompts open at `T` (at least): `rpe` (T−1 run), `delayed_symptom` (T−1 run: symptom report within 14 days; opens `T 00:00` local), `missing_activity` (T−4).

### 1.4 G2 real-data inventory (GATE-G2, user-run after Wave 0)
Representative FR265 runs that must appear among the inventoried activities (`fit-inventory --limit 20`), or be recorded as `unverified` (missing representative evidence is not proof of absent fields): easy outdoor run; long run; structured watch workout with repeats; treadmill run; pause-heavy run (≥ 3 timer stops); run with watch RPE entered. Personal API: one sleep range containing a non-worn night, HRV summaries, daily HR, one activity summary.
Output (redacted, no personal record values): device/firmware identity, SDK version/options, source kind, raw-content hashes, capability states verified|unsupported|unverified; FIT message names and counts; per message the field names present, units, scale, % non-null; record interval histogram; presence of session fields 192/193, lap field 71, event timer messages, workout_step messages; Personal API JSON key paths for timer duration, sleep duration, overnight HRV, resting HR. Saved to `private/real/g2/inventory-<date>.json`; data/metrics leads review capability predicates and manager records signoff (integration_and_release.md §3); synthetic implementation does not wait for this evidence.

## 2. P0-A acceptance journey (no LLM)

### 2.1 Automated (demo data) — gate for Wave 6
All commands run on owner-provisioned synthetic environments (worker_instructions §2; integration_and_release §1). Never reset shared 55432 or use the running real service for browser tests.

| Step | Check | Pass |
| --- | --- | --- |
| 1 | make check | backend lint/typecheck/fast tests, frontend lint/typecheck/tests/build pass |
| 2 | make test-integration under exclusive synthetic DB lease | migrations and integration tests pass |
| 3 | Isolated demo upgraded, seeded twice by 050 fixture procedure | second seed no duplicate rows; deterministic supplied clock |
| 4 | Demo smoke/verify-demo then make test-e2e against isolated ports | local-origin protections and all P0-A journeys pass |
| 5 | Dependency/source review | no embedded model credentials, backend model SDK/calls or external browser requests |

`e2e/p0a.spec.ts` (TASK-050), test names: `p0a: home shows today and 14-day strip` (14 day cells T…T+13; Today card shows today's session or "No session"), `p0a: prompts on schedule` (RPE prompt for T−1 run, delayed-response prompt, missing-activity prompt for T−4), `p0a: manual edit versions` (move one session → version list shows new `manual_edit`, head +1; rollback to previous → `rollback` version, unprotected state equals the earlier version; completed/historical/locked facts preserved), `p0a: structured workout per-rep` (T−6 activity page shows 4 rep rows, rep 3 speed 3.4 m/s; T−12 shows `not_assessable` and both step lists), `p0a: check-in exception guidance` (fatigue 7 → guidance `modify`, "coach review suggested" visible), `p0a: trends explicit missing` (recovery panel shows T−4, T−6 as missing; intensity shows "No anchor"), `p0a: anchor enables intensity` (enter hr anchors 150/165 in Settings → Trends intensity shows hr distribution), `p0a: only local requests` (every browser request host is 127.0.0.1).

### 2.2 Real-data acceptance after safe cutover

Preconditions: both software slices green, G2 evidence reviewed, verified backup/restore, TASK 068 dry-run/import checks and authority cutover complete under integration_and_release §4. This is implementation/release work, never planning. Existing populated plans are imported, not replaced by bootstrap version1.

Owner performs redacted before/after counts and source hashes, approved FIT backfill/recompute, then repeats to prove idempotence. Existing sync/export/Strong/conflict/history workflows remain operational. Read-only scripts/verify-real.py and smoke.py must pass. Browser shows imported plans/completions/history/confirmed recurrence; future calendar changes require explicit user action. Normal use must show per-rep comparison for a verified structured workout, RPE prompts when absent and delayed symptoms within16–48h. Missing data renders explicitly. Do not create artificial live check-ins or move real sessions just to test; synthetic journeys already cover those writes.

## 3. P0-B acceptance journey

### 3.1 Automated (scripted proposal, demo data) — gate for Wave 13
All checks in §2.1, then `make test-e2e` runs `e2e/p0b.spec.ts` (TASK-070). The spec invokes the CLI with Node `execFileSync('./scripts/with-mode', ['demo','bash','-c','cd backend && uv run python -m app.cli coach <args>'], {cwd: repoRoot})`, builds proposals from the snapshot JSON (session_uids by `local_date`), writes them to `private/demo/coach/proposals/`, and submits.
| Test name | Steps | Pass |
| --- | --- | --- |
| `p0b: weekly untick one accept rest` | snapshot `review_rolling_plan`; proposal c1 modify T+2 `planned_duration_s` +300, c2 modify T+4 `intent`, c3 modify T+8 `planned_duration_s` −300; submit; Home → Pending proposal → untick c2 → Accept | submit exit 0 `pending`; new head = base+1, kind `proposal_accept`, actor `coach`; proposal `partially_accepted`; T+2, T+8 show changed markers with lineage (revision 2, `changed_by_version` = new head); T+4 unchanged |
| `p0b: daily exception scope` | check-in modal: gait change yes → guidance shows "coach review suggested"; snapshot `proceed_or_modify_today`; proposal c1 modify T+2 `planned_duration_s` −600 | exit 0; a second proposal touching T+4 → exit 2, error code for V5 at `changes.0`; a third increasing T+2 duration → exit 2, V12 |
| `p0b: stale cannot be accepted` | submit valid proposal; move a session in Calendar | proposal shows `stale`, Accept disabled; `POST /coach/proposals/{id}/decision` → 409 `proposal_stale` |
| `p0b: next snapshot carries outcomes` | snapshot `review_rolling_plan` after the first test | `payload.prior_decisions` contains the first proposal id with c1, c3 `accepted`, c2 `rejected` |
| `p0b: block start` | snapshot `review_training_block`; proposal `block_change.decision=start`, eligible REC 001, REC 002, REC 003; accept with block change | Home block card shows objective, "week 1"; Block page history has 1 `start` decision |

### 3.2 Real skill run (manual, user) — P0-B done
1. Backup (`integration_and_release.md` §4). 2. `./scripts/with-mode real python3 scripts/serve.py`. 3. Invoke the current Codex going-bananas-coach entrypoint for a weekly review, using the repo-controlled helper from 065. 4. Pass: skill ran exactly 1 `coach snapshot`, ≤ 3 `coach query`, ≤ 3 `coach submit`; final submit exit 0; skill report ends "Review in the app: Home → Pending proposal". 5. In the browser untick one change, accept the rest. 6. Pass: `curl -s 'http://127.0.0.1:8000/api/v1/calendar/versions?limit=1'` → kind `proposal_accept`; `GET /api/v1/coach/proposals/{id}` → `partially_accepted`. 7. Record `approx_tokens` of the snapshot (`select operation, approx_tokens from coach_snapshots order by generated_at desc limit 1`) in the release notes. 8. Run one daily exception (Codex daily review after an exception check-in) → proposal dates ⊆ T…T+3.

## 4. QA checklist (brief §7)

| Item | Test location (task · file::test or e2e step) | Expected result |
| --- | --- | --- |
| 4/3 rhythm across weeks | 012 `test_calendar.py::test_bootstrap_cycle_crosses_week_boundary`; 061 `test_proposals.py::test_v8_off_cycle_run_requires_flag`; 020 `test_volume.py::test_frequency_window_spans_week_boundary` | anchor 2026-11-02, start 2026-11-02: runs 2,4,6,8,10,12,14 Nov; week Nov 2–8 = 4 runs (long Nov 8, quality Nov 2), Nov 9–15 = 3 (long Nov 14, quality Nov 10); strength Nov 2, 6, 9, 13; every 7-day window has 3 or 4 runs; off-cycle add without flag → V8 error |
| Idempotent Garmin import | 010 `test_fit_ingest.py::test_a8_same_fit_twice_idempotent`, `::test_fit_backfill_rerun_noop`; 030 `test_metrics_flow.py::test_recompute_idempotent`; §2.2 repeated import | 0 new rows on rerun; `metric_results` count and `data_revision` unchanged |
| Missing / stale data | 024 `::test_a9_missing_nights_not_zero`; 021 `::test_a4_gap_over_10s_unknown`, `test_intensity.py::test_no_anchor_not_assessable`; 020 `test_long_run.py::test_return_from_break_flag`; 062 `test_snapshot.py::test_data_quality_flags_stale_dataset`; 013 `test_coaching.py::test_no_checkin_no_downgrade` | missing never 0; `ANCHOR_MISSING`; `RETURN_FROM_BREAK` after 14 run-free days; stale dataset flagged in `data_quality`; no check-in + planned easy run → `proceed` |
| Isolated poor sleep | 024 `test_recovery.py::test_isolated_poor_sleep_discordance`; 013 `test_coaching.py::test_poor_sleep_tag_alone_proceeds` | one night sleep z ≤ −1.5, HRV/RHR normal, fatigue 3 → flags `[sleep]`, `subjective_poor=false`, `discordance=true`, no score; check-in tag poor_sleep + fatigue 3 → `proceed`, `coach_review_suggested=false` |
| Sustained fatigue | 024 `test_recovery.py::test_sustained_adverse_with_fatigue`; 013 `test_coaching.py::test_fatigue_7_modifies_and_suggests_review` | 3 nights HRV z ≤ −1.5 + fatigue 7 → flags each night, `discordance=false`; easy run day → `modify`, review suggested |
| Symptoms despite favorable HRV | 013 `test_coaching.py::test_symptom_overrides_favorable_recovery`; 024 `test_recovery.py::test_symptoms_not_averaged`; 061 `test_proposals.py::test_v12_blocks_increase_after_severity_6_5` | severity 4 with normal recovery → `modify`, review suggested; recovery result has no symptom-combined field; severity 7 within 72 h → change increasing T+1 duration rejected (V12) |
| Delayed post-long-run symptoms | 026 `test_prompts.py::test_delayed_prompt_window_long_run`; 023 `::test_a12_timeline_immediate_and_24h`; e2e `p0a: prompts on schedule` | long run ends 2026-11-08T14:00Z → prompt opens 2026-11-09T06:00Z, closes 2026-11-10T14:00Z; none at 2026-11-09T05:59Z; one prompt per run |
| Missed / reordered sessions | 025 `test_matching.py::test_no_activity_unknown_not_skipped`, `::test_move_candidate_requires_confirmation`, `::test_two_same_day_candidates_ambiguous`; 026 `test_prompts.py::test_missing_activity_prompt`; 061 `::test_v10_move_cannot_increase_quality_count`; 012 `test_calendar.py::test_missed_session_not_auto_rescheduled` | status `unknown` + `NO_ACTIVITY_FOUND`; ±1-day run → candidate `moved`, unlinked until confirmed; 2 candidates → `ambiguous`; no new version written by a miss |
| Overlapping strength / running | 025 `test_spacing.py::test_lower_body_strength_within_48h_of_quality`; 061 `::test_v9_week_keeps_two_strength`, `::test_v9_daily_cannot_move_strength`, `::test_v9_strength_move_requires_flag`; 062 `test_snapshot.py::test_strength_trigger_adds_hybrid_topic` | hours between lift end and quality start reported; Strong without duration → range, `confidence=low`; V9 errors as named; `topics/hybrid_strength_and_scheduling.md` in excerpts |
| Manual edits | 012 `test_calendar_api.py::test_edit_creates_version_with_actor_reason`, `::test_edit_head_moved_409`; 064 `test_coach_cli.py::test_manual_edit_stales_pending_proposal` | new version `manual_edit`/`user`/reason; wrong `expected_head` → 409 `calendar_head_moved`; pending proposal → `stale` in same transaction |
| Repeated invocations | 064 `test_coach_cli.py::test_resubmit_same_file_idempotent`, `::test_snapshot_twice_same_payload_hash`; 013 `test_checkins_api.py::test_checkin_replay_200`, `test_coaching.py::test_daily_guidance_upsert_by_input_hash`; 026 `::test_generator_idempotent` | same proposal_id, 1 row; equal `payload_sha256`; replay 200 with same id; 1 guidance row; no duplicate prompts |
| Revisions / approval / rollback | 061 `::test_partial_accept_revalidates_subset`; 063 `test_coach_api.py::test_partial_accept_writes_version_with_lineage`, `::test_reject_all_recorded`, `::test_accept_stale_409`; 012 `test_calendar_api.py::test_rollback_writes_new_version_restoring_state`; e2e `p0b: weekly untick one accept rest` | subset invalid → 422, nothing written; reject-all → status `rejected`, no calendar version; rollback restores eligible target state with new number and preserved protected facts |
| Block continuity | 061 `::test_v13_start_only_without_active_block`, `::test_v6_recipe_must_be_eligible`; 063 `::test_accept_block_change_appends_decision`; 014 `test_blocks_api.py::test_history_append_only`; 062 `::test_block_projection_includes_history` | second `start` → V13; ineligible recipe → V6; decision rows only appended |
| Invalid structured output | 061 `::test_v1_unknown_field_rejected`, `::test_v2_snapshot_older_than_24h`, `::test_v4_session_in_two_changes`, `::test_v5_daily_scope_today_plus_4`, `::test_v7_two_runs_same_date`, `::test_v11_unknown_policy_id`, `::test_v14_anchor_low_gt_high`, `::test_v15_non_quality_slot`; 064 `::test_submit_invalid_exit_2_nothing_written`, `::test_submit_stale_exit_3` | each returns `{code, path, message}`; status `invalid` exit 2 (V3 → `stale` exit 3); calendar head unchanged |
| KB retrieval failures | 060 `test_knowledge.py::test_manifest_1_0_rejected`, `::test_sha_mismatch_integrity_error`, `::test_missing_heading_integrity_error`, `::test_path_traversal_rejected`, `::test_p011_never_routed`; 064 `::test_snapshot_kb_integrity_exit_4`, `::test_kb_failure_does_not_affect_metrics_api` | `KnowledgeIntegrityError`; CLI exit 4; `/metrics/windows` still 200 |
| No spurious LLM / context growth | §2.1 step 5; e2e `p0a: only local requests`; 063 `test_coach_api.py::test_no_snapshot_or_submit_routes`; 062 `::test_daily_route_minimal_c26`, `::test_payload_size_bounded_by_projection`, `::test_no_vendor_scores_in_payload` | no LLM deps; POST `/coach/snapshot` → 404; daily excerpts only from `COACHING_GUIDE.md`, `workflows/daily_recommendation.md`, daily policy map, in-scope recipes, none from `avoid_routinely`; daily `approx_tokens` ≤ 6,000 (regression guard); 365 vs 28 days history → `approx_tokens` within 5%; no `vo2max`, `training_status`, `body_battery`, `readiness` keys |

## 5. Coaching evaluation (skill quality)

Automated retrieval-miss checks across all cases are **P1** (`prd.md` §7); only C26 routing is automated in P0 ( §4).
**P0-B manual protocol** (evaluator = user or integration owner, after §3.1 passes): for each required case, reset + seed demo (the TASK-050 isolated demo seed procedure), stage the state via the app UI/API as listed, run the skill in demo mode, and score four binary checks: (a) `coach submit` exit 0 within 2 retries; (b) decision direction matches the case's "Expected behavior"/"Appropriate reasoning"; (c) no "Prohibited inference"; (d) `coach_snapshots.kb_routes` contains the case's required routing and none of its "avoid" items. Pass = all 4 on all 7 cases. Results go in `private/eval/<date>-<case>.md` (never committed). TASK 065 takes explicit requested mode; this evaluation always uses demo. No evaluation mutates live training state.

| Case | Op | Stage | P0-B |
| --- | --- | --- | --- |
| C1 one poor night | daily | exception check-in fatigue 4, tag poor_sleep (no device-sleep write API in P0) | required |
| C3 symptoms vs favorable data | daily | check-ins severity 2 (T−3) then 5 (T), left PTT | required |
| C4 delayed tenderness after long run | rolling | `delayed_followup` for T−2 long run, severity 4, `hours_24_48` | required |
| C8 missed sessions, no make-up | rolling | mark two committed runs in T−6…T−2 `skipped` | required |
| C15 favorable progression | rolling | none | required |
| C16 first block, incomplete baseline | block | none (no block, no anchors) | required |
| C26 routine daily, minimal context | daily | set today's session REC 001 if not already | required |
| C2, C5, C11, C13, C14 (recovery trends) | daily/rolling | need recovery staging command | P1 |
| C6, C7, C9, C10, C12 | rolling/daily | stage via strength/calendar/check-ins | P1 |
| C17–C25 | block/quality/calibration/race | need block history or events | P1 |

Track B: B1→C15, B2→C5, B3→C3+A12, B4→C7, B5→C4, B7→C1/C13, B8→C2/C14, B10→C11 (evaluate with the mapped case); B6, B9 cover P1/excluded metrics → only the automated `test_no_vendor_scores_in_payload` applies in P0.

## 6. Current-baseline preservation and review guards

These are release blockers, not optional regression checks.

| Scenario | Owner | Required evidence |
| --- | --- | --- |
| Populated 0009 migration |003/068 | Every legacy/raw row retained; additive upgrade; no old migration edits; rollback of failed import leaves source and authority unchanged |
| Cross-plan membership |068 | Latest revision active_session_ids includes prior-plan session; imported UID and completion preserved; not merely latestplan_id rows |
| Confirmed recurrence |014/068 | Alternating strength/mobility survives; unconfirmed suggestions cannot overwrite it |
| Prose legacy prescription |068 | Raw fields archived; minutes→seconds/km→meters only where numeric; legacy_unstructured explicit; no invented recipe/steps/severity |
| Import replay/undo |068 | Same import marker gives no-op; newest eligible prior changed revision undo works while protecting completed/locked/historical facts |
| Staging |050/064/068 | Existing Coach/Cycle/Settings/check-in/Strength/history and helper work before authority switch; replacement writes inaccessible under legacy production authority |
| Source freshness |061–063 | Activity/check-in/recovery/profile/anchor/KB edit after snapshot causes explicit stale response at submit and acceptance even without calendar head change |
| Atomic decision |061/063 | Identical accepted selection replay returns original result; differing terminal selection conflicts; subset revalidated as whole; race accepts once; no partial writes |
| Empty/rejected proposal |061/063/066 | Review recorded, calendar head unchanged; accepted unchanged proposal does not hide last changed undo |
| Timer gaps/unknowns |021/022 | Unknown beginning/end count in timer-on coverage; no last-sample extrapolation, no lap-speed scoring fallback; all-unknown aggregate null |
| Correction propagation |030 | Recovery correction refreshes following 60-night baselines; anchor succession/timezone/plan/rematch invalidates old+new scopes; rollback leaves no derived writes |
| Completion authority |025/030 | Recompute every explicit/confirmed/auto link; no vacuous completed_as_planned; manual skip and explicit move retained |
| Restore/export parity |068/070 | Backed-up restored NEW synthetic target preserves new and legacy rows/raw objects/lineage/authority and passes verification |

Readiness audit selects at least one metrics packet, one data/API packet, and one calendar/coach/frontend packet for fresh-agent execution simulation. Findings and disposition live in reviews/. Planning completeness is assessed separately from later implementation test results.
