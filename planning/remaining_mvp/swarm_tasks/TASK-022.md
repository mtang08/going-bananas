# TASK-022 — deterministic structured-work interval execution
G2: canonical/synthetic contract frozen; device evidence pending, gates acceptance/release only.
Baseline: going-bananas main@5ebf981aa4517f4f73f3c97aa5d43232204466ce; supplied dependency-complete gb-mvp1-* tag; planning/remaining_mvp MVP-1.0
Wave / priority: P0-A; wave 2a (dependency_graph.md).
Dependencies: TASK-010, TASK-011, TASK-012
File ownership: create backend/app/metrics/intervals.py and backend/tests/unit/metrics/test_intervals.py
Forbidden changes: every other path; no auto interval detection, manual segments, new thresholds, composite score or physiology inference.

## Objective and observable end state
Plan4×300s speed3.80–3.95m/s, observed3.84/3.88/3.86/3.78 produces CV1.125%, last-first−1.563%, work1200s/4608m,targetcoverage.75. Watch5reps instead of4=>not_assessable WATCH_WORKOUT_MISMATCH. A stopped run with only original reps1–2 cannot produce original last-first change.

## Inputs and fixed contracts
This packet, metrics.md §§6–7 and schemas.md §6 are sufficient and authoritative; no external research file lookup required. Read schema6.2 canonical FIT fields,6.3 foundation; use services/calendar_structure.py:expand_structure. Metric ID work_interval_execution,method_version v1,WINDOW_DAYS=(),DEPENDS_ON=(). CONFIG exact rules: segment_source plan_plus_wkt_step_index; work_intensities [active,interval]; repeat_type repeat_until_steps_cmplt; max_record_gap_s10; speed_valid_mps[0,10];hr_valid_bpm[30,230];hr_exclude_first_s60;hr_min_step_timer_s180;target_scored_modalities[speed];required_speed_rule numeric_speed_target;cv_rule sample_sd_of_fully_completed_valid_reps;last_first_rule original_endpoints;subtotal_rule known_or_null.v1. E33 timer reconstruction flags come from canonical stream; no recalculation using different threshold.

Pure functions accept facts, not sessions/clock/network. ORM compute(session,subject_key)->list[MetricResultData] is separate. Rounding at final serialization only: seconds/meters/bpm1dp;speed/ratios/coverage/CV/change3dp. Use unrounded means for aggregates/status. No nonfinite input accepted as valid measurement.

### Complete pure input declarations
All classes frozen dataclasses. Fields before defaults are required; no additional implicit fields. None is unknown, not zero. Lists are caller-owned immutable-by-convention fixture values.

```python
@dataclass(frozen=True)
class PlanStep:
    step: int  # expanded_step, one-based
    type: str
    duration_type: str
    duration_value: float
    step_path: str
    repeat_index: int | None = None
    target_modality: str = "effort"  # null target maps effort/unscored
    target_low: float | None = None
    target_high: float | None = None

@dataclass(frozen=True)
class FitStep:
    message_index: int
    duration_type: str
    intensity: str | None = None
    duration_value: float | None = None
    target_type: str | None = None
    target_low: float | None = None
    target_high: float | None = None
    repeat_from: int | None = None
    repeat_count: int | None = None

@dataclass(frozen=True)
class LapIn:
    lap_index: int
    start_offset_s: float
    timer_s: float | None = None
    elapsed_s: float | None = None
    distance_m: float | None = None
    wkt_step_index: int | None = None

@dataclass(frozen=True)
class ExecStream:
    t_s: list[int]
    hr_bpm: list[float | None]
    speed_mps: list[float | None]
    timer_on: list[tuple[float, float]]
    quality_flags: tuple[str, ...] = ()
```

## Implementation procedure
1. Export `expand_plan(structure:list[dict])->list[PlanStep]`: map expand_structure output exactly; step=expanded_step, preserve step_path/repeat_index. Numeric targets already schema-validated; effort/null has null bounds. Required speed means **target_modality=='speed' and finite ordered nonnull bounds**. HR/effort targets never require speed or HR for completion status, though optional speed/HR observations remain displayable.
2. Export `expand_fit(steps:list[FitStep])->list[FitStep]`: sort unique message_index, append ordinary steps recording start position. Repeat_until_steps_cmplt requires earlier existing ordinary repeat_from and integer repeat_count>=2; append expanded slice from that position repeat_count−1 times. Repeated references preserve original indices. Malformed/forward/duplicate message index=>ValueError('MALFORMED_REPEAT'); unsupported repeat*=>ValueError('UNSUPPORTED_REPEAT'). More than100 expanded watch steps=>ValueError('UNSUPPORTED_REPEAT'). No mutation of input.
3. Export `clip(timer_on:list[tuple[float,float]],a:float,b:float)->list[tuple[float,float]]` overlap with[a,b). Export `after_timer_seconds(timer_on,seconds:float)->list[tuple[float,float]]`: consume unioned timer time from earliest range until seconds consumed; preserve remaining suffix. Export `weighted_median(samples:list[tuple[float,float]])->float|None`: positive finite weight only, sorted values, first cumulative>=half; exacthalf averages current/next. Shared integrate_timer_on counts all uncovered edges with i=None and long gaps unknown; guard index before sample lookup.
4. Export `execution_outcome(plan_steps:list[PlanStep],fit_steps:list[FitStep],laps:list[LapIn],stream:ExecStream|None)->dict` common keys status,quality_status,value,reason_codes,quality_flags. Early results valueNone/qualityNone: zero plan work=>not_applicable NO_WORK_STEPS; malformed repeat=>not_assessable matching reason; expanded watch work count or time/distance type mismatch=>not_assessable WATCH_WORKOUT_MISMATCH. Watch work intensities active|interval. Laps sorted by lap_index, indices must be unique; retained laps with wkt_step_index must be exact prefix of expanded watch indices, otherwise LAP_STEP_ORDER_MISMATCH. Any unindexed lap between first/last indexed laps also fails; unindexed outside prefix ignored. Map work rep to corresponding expanded position, never guessed nearest lap.
5. Per planned work rep, `observed` means matching lap exists; `fully_completed` means actual (timer for time plan,distance for distance plan) known and actual/planned>=1. Missing lap => statusmissing, observedFalse,fully_completedFalse,lap_indexNone,actual/ratio/all trace valuesNone,speed_statusmissing,reason_codes[WORK_STEP_NOT_RECORDED]. Observed null required actual=>completion_ratioNone,statuspartial,reason COMPLETION_VALUE_MISSING. Observed actual/planned<1=>statuspartial,reason INCOMPLETE_WORK_STEP. Known actual0 is ratio0, not missing. Plan denominator always positive from validation.
6. For observed lap, bounds a=start_offset; b=a+elapsed if elapsed known, else next chronological lap start if present, else unknown. Never substitute timer for elapsed. b<=a=>unknown with LAP_BOUNDS_INVALID; b unknown=>LAP_END_UNKNOWN. Trace usability requires stream, known valid bounds and absence of TIMER_EVENTS_MISSING,TIMER_EVENTS_AMBIGUOUS,TIMER_MISMATCH. Unusable trace speed_statusnot_assessable,reason respective flag/NO_STREAM/LAP_END_UNKNOWN/LAP_BOUNDS_INVALID; speed/HR/target outputsNone.
7. Usable trace speed: integrate clipped timer; eligible=sum all overlaps, valid=sum known finite0..10 sample weights, distance_integral=sum(v*weight). No eligible=>speed_statusnot_assessable NO_TIMER_ON_DATA; eligible>0/valid0=>speed_statusnot_assessable NO_SPEED_SAMPLES, speed_coverage0, meanNone. Otherwise mean=distance_integral/valid,coverage=valid/eligible; speed_statusavailable atcoverage>=.90 elsepartial LOW_COVERAGE. Required numeric speed target gets target_valid_s=valid,target_in_range_s=sum valid inclusive low<=v<=high weights,in_target=inclusive mean check; valid0=>target fieldsNone. HR/effort target fieldsNone always, HR_TARGET_NOT_SCORED flag forHR. Optional speed unavailable/partial never changes rep/session completion status; retains speed_status/reason independently. Required speed unavailable=>rep partial COMPONENT_NOT_ASSESSABLE; required partial=>rep partial LOW_COVERAGE. No lap-summary speed fallback.
8. HR: only when known lap.timer_s>=180 and trace usable. Remove first60 timer-on seconds from clipped union, then duration-weighted median of valid known HR30..230 intervals. Missing HR=>None without completion penalty. Known timer<180=>None,HR_NOT_REPORTED_SHORT_STEP. Null timer=>None,HR_TIMER_UNKNOWN. HR never changes status/quality. Rep fields exactly: rep,planned_step,step_path,repeat_index,lap_index,observed,fully_completed,status,reason_codes,planned_duration_type,planned_value,actual_timer_s,actual_distance_m,completion_ratio,mean_speed_mps,speed_status,speed_reason_codes,speed_coverage,target_modality,target_low,target_high,target_valid_s,target_in_range_s,in_target,hr_median_bpm,flags.
9. Aggregate n_planned, n_observed(count laps), n_completed(count fully_completed), step_completion_ratio=n_completed/n_planned. completed_work_s/m sum each measurement across **observed** work laps, including underfilled laps: no observed laps=>0.0 known no observed work; observed laps but all field unknown=>None; some known/some unknown=>known subtotal plus PARTIAL_WORK_TIMER/PARTIAL_WORK_DISTANCE. Missing planned reps independently INCOMPLETE_WORK_STEPS. Missing any observed work field makes overall partial WORK_MEASUREMENT_MISSING (both all-unknown and partially-known cases). No sum from stream substitutes missing lap values. planned_work_s/m sums when all work steps same corresponding type elseNone. CV uses unrounded means from fully_completed reps with speed_statusavailable; >=2 and mean>0 needed, otherwiseNone. Last-first only original first/last planned reps both fully_completed/speed_statusavailable and firstmean>0; otherwiseNone. Zero denominator flag ZERO_SPEED_DENOMINATOR when at least2eligible means but mean0, or both endpoints eligible with first0. target_coverage=sum inrange/sum valid for observed numeric-speed reps with valid>0, elseNone; incomplete observed target coverage remains descriptive and cannot imply whole workout completion.
10. Session status partial if n_completed<n_planned (INCOMPLETE_WORK_STEPS), any observed required completion unknown (COMPLETION_VALUE_MISSING), any observed lap timer/distance unknown (WORK_MEASUREMENT_MISSING), any required speed not_assessable (COMPONENT_NOT_ASSESSABLE) or partial(LOW_COVERAGE); elseavailable. Reasons sorted unique, quality_flags sorted union rep flags + subtotal/zero-denominator flags. Quality coverage_label(sumvalid,sumeligible) over numeric-speed-target observed reps with usable trace only; if any required speed unassessable, quality at mostlimited (None when no usable required denominator). HR/effort-only session qualityNone. Optional speed does not downgrade session. value keys reps,n_planned,n_observed,n_completed,step_completion_ratio,cv_speed,last_first_change_pct,completed_work_s,completed_work_m,planned_work_s,planned_work_m,target_coverage.
11. Register compute. Invalid UUID=>ValueError invalid_subject_key; absent/non-run=>[]; excluded/unresolved=>not_applicable ACTIVITY_EXCLUDED. Load completion link and current nondeleted run plan at head; none=>NO_PLAN_LINK; structureNone=>NO_STRUCTURED_PLAN; no expanded work=>NO_WORK_STEPS; no watch steps=>NO_WATCH_WORKOUT. Load laps orderedlap_index and stream flags. Offset origin is decoded session/activity.start_at, never firstlap; `(lap.start_at-activity.start_at).total_seconds()` remainsfloat. Numeric canonical decoder fields are not rescaled.
12. **Provenance:** call TASK011 `app.metrics.contract.metric_source_refs(session,activity_id,session_uid=...,calendar_version=...)->dict`; pass returned map unchanged as source_refs. Keys activity,fit,plan,completion_association_hash are defined in schema §7.2 (foundation extensions), including immutable canonical/raw/FIT revision hashes, selected plan revision and stable association/manual-input hash. This task does not create helper or guess model field paths. Null source fields are allowed only when genuinely missing (e.g.no FIT); helper records explicit missing markers. When a FIT-dependent calculation has decoded data but missing required raw/FIT identity, resultinvalid INPUT_PROVENANCE_MISSING,valueNone. Add config hash and unitNone; engine supplies dependency_hash/timezone/calculated_at. Add session_uid/calendar_version to nonnullvalue. Never use only IDs as provenance; never include derived completion status/version.

## Tests and expected results
Pure test_intervals.py only; no ORM/network. EX-1 plan=[warmup600,repeatcount4[work300 speed3.8..3.95,recovery120],cooldown600]. Fit msg0warmup600,msg1active300,msg2recovery120,msg3repeatfrom1count4,msg4cooldown600. Laps0..9 wkt indices[0,1,2,1,2,1,2,1,2,4], offsets[0,600,900,1020,1320,1440,1740,1860,2160,2280], timer=elapsed=[600,300,120,300,120,300,120,300,120,600], distances=[1800,1152,360,1164,360,1158,360,1134,360,1800]. Stream t0..2880 inclusive step1,timer[(0,2880)],work speed3.84/3.88/3.86/3.78,other3.0;workHR160/161/162/163,other140.
- test_ex1: available/good, n_observed=n_completed4,ratiosall1,means[3.84,3.88,3.86,3.78],in_target[T,T,T,F],HR[160,161,162,163],lap[1,3,5,7],planned_step[2,4,6,8],step_path1.steps.0,repeat_index[0,1,2,3],CV1.125,last_first−1.563,work1200s/4608m,planned1200s/None m,target.75,step1.
- test_stopped_two: EX-1 laps0..3 only =>partial INCOMPLETE_WORK_STEPS,n_observed=n_completed2,step.5,reps3/4missing,CV.733,last_firstNone,work600s/2316m,target1.0.
- test_partial_final: EX-1 finalworktimer150,elapsed150,distance567 =>n_observed4,n_completed3,ratiofinal.5,step.75,partial,last_firstNone,work1050s/4041m; speed integration clips last rep at2010.
- test_null_required_timer: EX-1 firstworktimerNone,elapsed300,distance1152 retained =>rep ratioNone,partial,fully_completedFalse; n_observed4,n_completed3,step.75,worktimer900 knownsubtotal,PARTIAL_WORK_TIMER,WORK_MEASUREMENT_MISSING; HRNone/HR_TIMER_UNKNOWN; last_firstNone. All4worktimersNone=>completed_work_sNone,not0,n_completed0. All4workdistancesNone=>completed_work_mNone,ratios1 fromtimers,n_completed4,overallpartial WORK_MEASUREMENT_MISSING. All worklaps absent=>n_observed0,n_completed0,work_s/m0,partial INCOMPLETE_WORK_STEPS.
- test_required_speed_no_stream: EX-1 streamNone =>all completionratios1,n_completed4,means/HR/targetNone,speed_statusnot_assessable NO_STREAM,overallpartial COMPONENT_NOT_ASSESSABLE,qualityNone.
- test_optional_speed_no_stream: same laps/plan but targethr150..165 or effort/null=>overallavailable,qualityNone,ratios1,speed_statusnot_assessable NO_STREAM,means/targetNone; HR_TARGET_NOT_SCORED only forHR. Optional missing speed is explicit but not a completion failure.
- test_valid_speed_absent: EX-1 all speedNone =>coverage0,meanNone,NO_SPEED_SAMPLES,overallpartial; speed25 on[700,705) only=>rep1coverage.983,mean3.84,available.
- test_weighted_hr: post-lag samples(150,1s),(170,9s)=>170; equalweights=>160. Timer ranges[(0,30),(90,270)] after60=>[(120,270)],not[(90,270)]. Shortwork60s witheffort target/no stream and valid lap measurements=>available,HRNone/HR_NOT_REPORTED_SHORT_STEP (short-step flag irrespective trace).
- test_mismatch:repeatcount5 orworkdurationtypedistance=>WATCH_WORKOUT_MISMATCH; reorderedlaps=>LAP_STEP_ORDER_MISMATCH;unsupportedrepeat=>UNSUPPORTED_REPEAT;forwardrepeat=>MALFORMED_REPEAT;zerowork=>NO_WORK_STEPS. All earlyvalueNone.
- test_nested_watch_repeat: msg0active,msg1recovery,msg2repeatfrom0count2,msg3rest,msg4repeatfrom0count2=>indices[0,1,0,1,3,0,1,0,1,3].
- test_distance:3×1000m effort targets,lapdistances1000/990/1010 with known timers =>ratios1/.99/1.01,n_completed2,step.667,partial,planned_work_m3000,planned_work_sNone.
- test_zero_speed: complete speed-target laps withvalidspeed0=>CV/changeNone,ZERO_SPEED_DENOMINATOR; test_missing_original_endpoint=>last_firstNone even if2interior eligible means.
- test_timer_flag: each canonical timer error flag suppresses trace; EX-1 summary ratios still1,overallpartial for speedtargets; efforttargets remainavailable. Trace edge eligible denominator follows foundation fixture, no extrapolation.
ORM provenance tests belong030: complete FIT/plan helper map survives explain, changed raw/FIT hash changes dependency, derived completion status does not, required identity missing=>invalid INPUT_PROVENANCE_MISSING. TASK011 helper foundation tests verify exact keys; no DB access added to these unit tests.
Commands: cd backend && uv run pytest tests/unit/metrics/test_intervals.py -q; uv run ruff check app/metrics/intervals.py tests/unit/metrics/test_intervals.py; uv run mypy app --ignore-missing-imports. make check after focused checks.

## Acceptance checklist
- [ ] Only owned files changed; dataclasses/exports exactly match packet.
- [ ] Named numeric/null/status fixtures pass; HR/optional speed never fail completion.
- [ ] Uncertain mapping not_assessable; unknown lap totals remain unknown/subtotals, no guessed values.
- [ ] source_refs uses foundation helper; no external research/live calls; actual check outputs recorded.

## Completion report
Task/branch/base tag; files; commands/results; checklist and blockers. No device validation claim.

## Escalation rule
STOP on exact contract mismatch. Do not invent schema, dependencies, heuristics, source provenance or alternative mapping. Implementation follows planning approval.
