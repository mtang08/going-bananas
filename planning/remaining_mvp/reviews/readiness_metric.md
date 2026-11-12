# TASK-022 readiness audit

**Verdict: NOT READY.** Two independent workers cannot reliably produce compatible arithmetic, status, and result provenance from this packet.

1. **Stopped-run oracle contradicts the rule.** TASK-022, “Reconciled edge behavior” requires `last_first_change_pct` to use the original first and last work reps, and metrics.md §7 explicitly forbids substituting an interior rep. In “Tests and expected results,” `test_stopped_after_two_reps` has only reps 1–2 of four but expects `last_first_change_pct≈1.042`. Change that expectation to `None`. This is a direct test failure for a compliant implementation.

2. **EX-1 distance fixture cannot be derived as written.** TASK-022, “Base fixture EX-1” says every lap distance is “speed × duration” but supplies four work speeds and only one speed (`3.0`) for all other times. That yields work distance `300×(3.84+3.88+3.86+3.78)=4608`, so the expected `completed_work_m=4608` is consistent; however the fixture must state the work-lap distance values or explicitly say to use the segment's stream speed for each lap. The phrase “distance = speed × duration” is ambiguous for the ten laps and permits workers to use different lap speed choices, though the asserted work total resolves the work laps. Make those four distances `1152,1164,1158,1134 m` explicit.

3. **Pure-input dataclasses are internally inconsistent.** TASK-022, procedure step 2 freezes `PlanStep` without `step_path` or `repeat_index`, `LapIn.start_offset_s` as `int`, and `ExecStream` without `quality_flags`. Procedure step 3 and “Reconciled edge behavior” then require these added fields and float lap offsets. Publish the complete final dataclass declarations (including field defaults and `ExecStream` array types) in one place. Specify that `PlanStep.step` is the one-based `expanded_step` and that repeat index is nullable.

4. **Required-speed rule is unresolved.** Procedure step 5(e,i) and metrics.md §7 say status depends on “required speed,” but neither defines which reps require it. `test_no_stream` expects partial for speed-target work, while `test_hr_target_not_scored` and `test_short_reps_hr_not_reported` do not settle whether effort/HR-target work needs speed. Define “required speed” explicitly by target modality (or for all completed work reps), and state the `speed_status`/reason and overall status when a non-speed-target rep has no valid speed.

5. **Result identity lacks required provenance.** TASK-022 procedure step 6 sets `source_refs` to activity ID, session UID and calendar version only. schemas.md §6.3 requires immutable FIT source revision/raw hash and a stable completion association/manual-input hash for dependency identity; absent required provenance is invalid. Specify exact `source_refs` keys and how this module obtains them from `Activity`/`FitFile`/`SessionCompletion` (or a named TASK-011 helper). The metric owns only its two files and cannot add a shared helper.

6. **Missing and null lap accounting remains open.** Procedure step 5(h) sums non-None lap timer/distance values; metrics.md §6 says all-unknown aggregates are null and missing durations are unknown, not zero. State whether partially known `completed_work_s/m` are known subtotals with a partial reason/flag, and whether all-unknown sums are `None`. Also state what a completed work lap with null `timer_s` does to `completion_ratio`, rep status and `n_completed`.

The cited B-spec `work_interval_execution.v1.md` is not present in the repository tree. Either include its exact path/content in the dependency-complete packet or remove the reference and declare TASK-022 plus metrics.md/schemas.md authoritative.

## Author dispositions — 2026-11-12 (original findings retained)

TASK-022 replaced as one consolidated executable contract, not appended overrides. (1) Stopped-two oracle last_first=None. (2) Full lap distance array explicit, work1152/1164/1158/1134. (3) Complete dataclasses include step_path/repeat_index, float lap/timer boundaries, all stream types/default flags. (4) Required speed explicitly numeric speedtarget only; optional HR/effort missing-speed tests available overall but not_assessable speed. (5) New TASK011 metric_source_refs/completion_association_hash exact helpers coordinated into schemas§7.2/011,022 consumes map; provenance missing reason INPUT_PROVENANCE_MISSING. (6) observed/fully_completed counts, null-required actual, partial/all-unknown work totals and exact tests now frozen. External research lookup removed;022+metrics+schemas are authority. metrics§7 reconciled to the same rules. No application tests or implementation performed; independent recheck pending.

## Independent recheck — 2026-11-12

**Verdict: NOT READY.** Original findings 1–6 and the missing B-spec reference are resolved in the revised packet and cited contracts. One new interface conflict remains:

- TASK-022 “Complete pure input declarations” defines `ExecStream.timer_on: list[tuple[float,float]]`, and procedure steps 3, 6–8 require clipping those ranges to float lap boundaries before calling `integrate_timer_on`. The authoritative schemas.md §6.3 signature is `integrate_timer_on(t_s:list[int], timer_on:list[tuple[int,int]], max_gap_s:int)`. A worker cannot preserve fractional lap boundaries and satisfy that signature; rounding them violates TASK-022’s float-offset rule and changes eligible seconds/HR lag. **Fix:** revise schemas.md §6.3 and TASK-011 to accept float timer interval endpoints (while retaining integer sample timestamps), with a fractional-boundary fixture, or supply a precisely named float-aware integration helper owned by TASK-011. Then TASK-022 can call that exact exported signature.

No implementation, tests, or live data were used for this recheck.

## Final recheck — 2026-11-12

**Verdict: READY for implementation.** schemas.md §6.3 and TASK-011 now export the same `integrate_timer_on(t_s:list[int], timer_on:list[tuple[float,float]], max_gap_s:int)` signature required by TASK-022. TASK-011 specifies finite float endpoints, integer record timestamps, preserved fractional clipping, and the `.25–1.75` fixture yielding two `.75 s` known portions. This resolves the sole remaining interface blocker. The prior findings and dispositions above remain as audit history; this final verdict supersedes the earlier NOT READY verdicts. Review only; no implementation or tests run.
