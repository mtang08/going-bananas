# Workflow: Post-Event Review

**Status:** reviewable candidate guidance for package 1.2.0+privacy1; not an activated rule or medical instruction.

## Scope and entry

- Run when a race review is due for a `target`, `benchmark`, or `supported_exposure` event in the last 7 days. The block's culminating benchmark belongs to block review; see `adaptive_coaching/race_and_benchmark_policy.md`. (product heuristic)
- For the event as exposure and observation, see `topics/races_tapers_and_transitions.md` › Core position.
- Scope is committed days 1–7. Never edit days 8–14; weekly review owns them.
- The 1–3 days after are an observation window, not a fixed rest prescription; see `adaptive_coaching/race_and_benchmark_policy.md` › Post-event review. (coaching convention)

## Review sequence

1. Reconstruct pacing, effort, limiter, and conditions: heat, course, wind, fueling, sleep, and travel.
2. Collect response from event day to day +3: symptoms and gait, illness, fatigue, and recovery nights. Mark missing observations as unknown.
3. Classify cost from the whole response, not distance alone.
4. Choose easy movement, rest, cross-training, or short consolidation from the observed response. Resume progression only once ordinary running and symptoms are stable. Use the lowest level in `adaptive_coaching/exception_policy.md` › Minimal-change ladder; keep protective changes inside the committed window.
5. Choose recalibration: `none`, `propose_anchors` only from a comparable, credible performance (P020), or `defer` if confounded or response is unknown.
6. State one training implication for the block objective. If the objective changed, escalate to block review; do not rewrite it here. Distinguish operation `escalation` from finding severity and P018 clinical referral.
7. Resolve related open patches. Give the criteria supporting each resolution; identify committed sessions explicitly unchanged with reasons in the review narrative.

## Output contract

```yaml
event_review:
  event_id: <event uuid>
  activity_id: <activity uuid or null>
  outcome: null
  compared_with: null
  pacing: <text>
  effort_and_limiter: <text>
  conditions: <text or null>
  symptoms: <text or null>
  recovery_observation: <text>
  recalibration: none | propose_anchors | defer
  training_implication: <text>
anchor_changes: [<only when recalibration is propose_anchors>]
changes: [<committed days 1–7 only>]
patch_resolutions: [{patch_id: <uuid>, status: resolved | escalated, note: <text>}]
```

- `event_id` is required here; `outcome` stays null (it is for the block review).
- `anchor_changes` only when `recalibration: propose_anchors`.
- `changes` only inside committed days 1–7.

## Prohibited inferences

- That one race identifies every zone or supports automatic conversion to every intensity anchor.
- That a poor race proves the block failed, without considering execution, conditions, or training response.
- A fixed number of recovery days.
- That performance overrides worsening symptoms.
- That a low-priority race must be run maximally.
- Adding race-specific intervals at once because a race result is available.

## Evidence and policy links

- `topics/races_tapers_and_transitions.md`: event interpretation and transition.
- `adaptive_coaching/race_and_benchmark_policy.md`: benchmark and post-event context.
- `adaptive_coaching/exception_policy.md`: minimal-change ladder and medical scope.
- P006, P013, P018, P020, P021, P026, P027.
- E-CAL-04, E-DATA-02.
