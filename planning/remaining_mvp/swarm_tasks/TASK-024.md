# TASK-024 — transparent source-partitioned recovery metrics
Baseline: /Users/mtang/dev/going-bananas; main@5ebf981aa4517f4f73f3c97aa5d43232204466ce + supplied dependency-complete gb-mvp1-* tag; spec MVP-1.0 planning/remaining_mvp.
Wave / priority: P0-A; wave 2a (dependency_graph.md).
Dependencies: TASK-011, TASK-013 (no G2 implementation dependency)
File ownership: create backend/app/metrics/recovery.py, backend/tests/unit/metrics/test_recovery.py
Forbidden changes: all other files; no adapters/migrations/routers/engine changes.

## Objective and observable end state
Return nightly separate sleep/HRV/RHR/subjective signals, explicit missing nights and w7 coverage. A 28-night RHR baseline14×48+14×52 with current55 yields z1.69/adverse=true. No readiness score.

## Inputs and fixed contracts
Read metrics.md §§2–10 and schemas.md §§2,6. MetricResultData/RunFact/registry/anchor/current-result signatures in schemas §6.3 are authoritative. All thresholds are versioned config; no hidden readiness/adherence score. Pure functions accept facts/clock, never DB or network. ORM compute(session,subject_key)->list[MetricResultData] is separate. Source refs carry immutable revisions/raw hashes/plan/anchor/upstream dependencies; engine completes row identity. Historical handoff prose does not override canonical contracts. G2 is device acceptance/release evidence only, synthetic implementation is not blocked. All arithmetic unrounded until serialization; seconds/meters/AU/bpm/hours1dp; ratios/coverage/speed/CV/change3dp; z2dp.

## Implementation procedure
1. Constants METRIC_ID='recovery_multisignal_summary', METHOD_VERSION='v1', WINDOW_DAYS=(7,), DEPENDS_ON=(). CONFIG={baseline_days:60,min_nights:14,established_nights:28,stale_days:14,stale_min_nights:7,robust_factor:.6745,adverse_z:1.5,subjective_fatigue:7,hrv_transform:'ln',statistics:{sleep:'main_sleep_duration',hrv:'last_night_average',resting_hr:'daily_resting'}}; include valid ranges from metrics §9 and partition rule identifier 'source_definition_device.v1'.
2. Frozen Observation(local_date:date,metric:str,value:float|None,partition:str,resolved:bool,source_refs:dict); Subjective(observed_at:datetime,id:str,fatigue:float|None,illness:str|None). `signal_outcome(metric:str,current:Observation|None,history:list[Observation],on_date:date)->dict` filters same partition, prior60 dates, latest resolved revision per date. Invalid/unresolved current status invalid; missing current missing. Invalid history omitted and counted. Partition is canonical serialized source account/source_kind/statistic/definition/device-generation (unknown explicit), no inferred cross-source merging.
3. Output signal keys status,value,baseline_state,valid_nights,z,adverse,baseline_median,baseline_mad,deviation,reason_codes,quality_flags,partition. Missing/invalid values remain null; below14 baseline ->partial BASELINE_INSUFFICIENT with z/adverse null. MAD0 ->partial MAD_ZERO, deviation retained. BASELINE_STALE flag prior14 count<7; unknown device flag. Otherwise available. Compute medians/MAD in transformed units; adverse HRV/sleep z<=−1.5, RHR>=1.5, compare full precision.
4. `night_outcome(on_date:date,observations:list[Observation],subjectives:list[Subjective])->dict`: three signal keys plus local_date,subjective_poor,discordance,fatigue,illness. Select latest nonnull fatigue and illness separately by observed_at,id on local D. Three-valued logic metrics §9. Row status missing if all signals missing and subjective unknown; partial if any signal missing/invalid/partial; otherwise available. Quality None when missing, limited when partial/flags, good otherwise. Preserve union reasons/flags. No recommendation or traffic light.
5. `summary_outcome(nights:list[dict])->dict`: exactly7 dated nights; nights_total7,nights_with_data count any valid signal,missing_dates; coverage=count/7, quality coverage_label; status missing if0,partial if<7,available if7. Empty absent nights explicitly synthesized, not dropped.
6. `compute(session,subject_key)` accepts night:ISO or w7:ISO; load RecoveryObservation model used by existing sync and source provenance, read selected v2 check-ins only; normalize per schemas §6. Load D−60..D inclusive for nightly signal, broader for seven nights. Row subject_type night/window, unit None; capture all chosen observation/source revisions including invalid/excluded baseline source IDs and checkin versions. No call to external API. Expose `night_outcome`, `signal_outcome`, `summary_outcome` for tests and engine; no commit.

## Tests and expected results
Pure test_recovery.py fixtures:
- test_rhr_baseline:14×48+14×52 on prior28 distinct dates,current55=>median50,MAD2,z1.69,established,adverseTrue.
- test_outlier: previous fixture +150 on another prior date=>median52,MAD4,z.51,adverseFalse.
- test_hrv:15×60+15×70,current50=>z−2.27,established,HRV adverseTrue.
- test_provisional:13×61.559,1×66.686,13×72.24,current60=>z−.89,provisional,adverseFalse.
- test_short_baseline:13valid=>none,z/adverseNone. test_mad_zero:28×50,current55=>MAD0,zNone,deviation5,partial.
- test_partition_change: old device28nights, current new=>valid_nights0, no borrowing. test_invalid_hrv0=>invalid.
- test_missing_two:5of7 dates with data=>coverage.714,qualitylimited,2 explicit missing_dates.
- test_subjective_unknown: fatigueNone,illnessNone=>None; fatigue7/illnessNone=>True; fatigue3/illnessnone=>False; fatigue3/illnessNone=>None. physiological anyTrue+subjectiveFalse=>discordanceTrue; all adverseNone=>discordanceNone.
- test_baseline_window: D−60 included,D excluded; 6valid prior14=>BASELINE_STALE. DST dates count local nights, not24h chunks.
Command: cd backend && uv run pytest tests/unit/metrics/test_recovery.py -q; uv run ruff check app/metrics/recovery.py tests/unit/metrics/test_recovery.py; uv run mypy app --ignore-missing-imports. No DB tests in this packet; partition provenance integration in030.

## Acceptance checklist
- [ ] Only owned paths changed; no migrations/dependency/runtime authority changes.
- [ ] Named fixtures pass with exact values; missing never silently zero/normal; no live services.
- [ ] Public signatures and result keys match schemas §6 and this packet; source provenance retained.
- [ ] Focused tests, ruff and mypy pass; report actual output, not assumed green.

## Completion report
Task/branch/base tag; files; exact commands/results; checklist; blockers. No design essay.

## Escalation rule
If the pinned code or dependency contracts differ, STOP with concrete blocker. Do not invent schema, thresholds, endpoints or fallback behavior.
