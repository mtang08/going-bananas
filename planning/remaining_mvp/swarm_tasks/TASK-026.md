# TASK-026 — idempotent timed prompts with explicit answers
Baseline: /Users/mtang/dev/going-bananas; main@5ebf981aa4517f4f73f3c97aa5d43232204466ce + supplied dependency-complete gb-mvp1-* tag; spec MVP-1.0 planning/remaining_mvp.
Wave / priority: P0-A; wave 2d (dependency_graph.md).
Dependencies: TASK-012, TASK-013, TASK-020, TASK-023, TASK-025
File ownership: create backend/app/services/prompts.py, backend/tests/unit/test_prompts.py
Forbidden changes: check-in API/GET filtering (013), models, engine, migrations; no scheduler/live worker.

## Objective and observable end state
Long run ending2026-11-15T14:00Z creates delayed prompt immediately with opens11-16T06:00Z/closes11-17T14:00Z; visible only in that interval; rerun never duplicates.

## Inputs and fixed contracts
Read metrics.md §§2–10 and schemas.md §§2,6. MetricResultData/RunFact/registry/anchor/current-result signatures in schemas §6.3 are authoritative. All thresholds are versioned config; no hidden readiness/adherence score. Pure functions accept facts/clock, never DB or network. ORM compute(session,subject_key)->list[MetricResultData] is separate. Source refs carry immutable revisions/raw hashes/plan/anchor/upstream dependencies; engine completes row identity. Historical handoff prose does not override canonical contracts. G2 is device acceptance/release evidence only, synthetic implementation is not blocked. All arithmetic unrounded until serialization; seconds/meters/AU/bpm/hours1dp; ratios/coverage/speed/CV/change3dp; z2dp.

## Implementation procedure
1. Export `prompt_changes(facts:dict,existing:list[dict],now:datetime)->dict` pure, and `generate_prompts(session,now:datetime)->dict[str,int]` ORM wrapper counts created,expired,answered. facts keys activities (known end + effective RPE + long classification), checkins, completions, planned_actual, local_today,timezone. No reads of clock inside pure helper.
2. Apply exact metrics §9 timing/qualification/answers. RPE valid0 counts answered. Delayed explicit delayed_followup activity/prompt counts even empty symptoms; unrelated or exception checkin does not. Missing/unmatched completion unknown only answers when match_method user_marked and explicit user resolution, not derived unknown. Valid linked subject answers regardless computed completion quality.
3. Stable dedupe identity kind+subject (`activity:{uuid}` for rpe/delayed; `session:{uid}` for unmatched/missing), schema unique key; one record forever, no duplicate after dismissal/expiry. Match candidate IDs belong payload/source refs, not dedupe. Insert future opens_at now if qualification known, never wait for future write. No timed prompt with unknown end. RPE opens at end, closes48h; no prompt before end. Expire open closes<=now. Recompute expired->answered on explicit later evidence; never reopen. Preserve dismissed.
4. Missing_activity for stored current NO_ACTIVITY_FOUND reasons on run dates[today−7,today−1], ignore certainty; unmatched_session for AMBIGUOUS_MATCH or MOVE_CANDIDATE on[today−7,today]. Old matched/removed plans expire remaining open match prompts. Empty absent metric results never fabricate missing-activity prompts.
5. ORM wrapper uses current results/association helper, race-safe unique insert, updates only changed state, no commit or independent source data_revision bump (derived prompts). GET /prompts visibility stays TASK013 opens<=now and closes>now; tests here validate predicate expectation,030 tests actual route.

## Tests and expected results
Pure test_prompts.py: test_future_delayed_created opens/closes example; test_visibility_boundary false at05:59:59Z,true06:00Z,false at11-17T14:00Z; test_unknown_end no timed row; test_rpe_zero_answered; test_empty_delayed_answer yes; test_unrelated_checkin no; test_derived_unknown_completion not answered; test_user_marked_unknown answered; test_dismissed_not_recreated; test_retry_same_keys no create; test_missing_provisional included; test_delayed_late_expired_answer sets answered without reopening. Assert exact transition counts. DST uses elapsed UTC16/48h, independent of day length.
Command: cd backend && uv run pytest tests/unit/test_prompts.py -q; uv run ruff check app/services/prompts.py tests/unit/test_prompts.py; uv run mypy app --ignore-missing-imports. DB uniqueness/route timing tests in030.

## Acceptance checklist
- [ ] Only owned paths changed; no migrations/dependency/runtime authority changes.
- [ ] Named fixtures pass with exact values; missing never silently zero/normal; no live services.
- [ ] Public signatures and result keys match schemas §6 and this packet; source provenance retained.
- [ ] Focused tests, ruff and mypy pass; report actual output, not assumed green.

## Completion report
Task/branch/base tag; files; exact commands/results; checklist; blockers. No design essay.

## Escalation rule
If the pinned code or dependency contracts differ, STOP with concrete blocker. Do not invent schema, thresholds, endpoints or fallback behavior.
