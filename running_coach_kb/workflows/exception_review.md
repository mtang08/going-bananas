# Workflow: Exception Review

**Status:** reviewable candidate guidance for package 1.2.0+privacy1; not an activated rule or medical instruction.

## Scope and entry

- Run when the app recommends `exception_review`: an open `caution` or `hold` finding, or a due patch reassessment. `observe` findings wait for Sunday review unless the athlete asks. (product heuristic)
- This is a narrow interrupt; weekly review remains the normal control loop. (product heuristic)
- Scope is the committed window (days 1–7). Never edit days 8–14.
- If another operation has an open proposal, ask the athlete to decide on it or discard it first. Never take it over.
- For `escalate`, route to block review through `escalation` or recommend clinical input per policy. Finding severity, operation routing, and P018 clinical referral remain separate. (product heuristic)

## Review sequence

1. Read findings' evidence, not only summaries. Use category and severity as given; never re-grade them.
2. Check safety first: symptoms and function, gait, illness, clinician restriction (`COACHING_GUIDE.md` §3, Decision hierarchy).
3. Name confounders and converging signals. Distinguish observed evidence from interpretation and missing context.
4. Choose the lowest ladder level: current session → next session → next days → committed window → block via escalation. See `adaptive_coaching/exception_policy.md` › Minimal-change ladder.
5. Change only sessions inside the patch window; list each committed session left unchanged with a reason. Make the sessions explicitly unchanged reviewable alongside the changes.
6. Set the reassess date (within 7 days), what to monitor, return criteria, and escalation criteria. State observations that would change the response.
7. Resolve or escalate any due patch via `patch_resolutions`, explaining which criteria support the decision.
8. A no-change exception review is valid when the finding needs monitoring only. (product heuristic)

## Output contract

```yaml
exception:
  finding_ids: [<finding uuid>]
  category: symptoms_illness | training_response | accumulated_fatigue | calendar_disruption
  severity: observe | caution | hold | escalate
  confidence: low | moderate | high
  triggering_evidence: <text>
  relevant_context: <text or null>
  ladder_level: current_session | next_session | next_days | committed_window | block
  patch_window: {start: <date>, end: <date>}
  unchanged: [{session_uid: <uuid>, reason: <text>}]
  reassess_on: <date>
  monitor: [<text>]
  return_criteria: [<text>]
  escalate_criteria: [<text>]
changes: [<changes inside the patch window only>]
patch_resolutions: [{patch_id: <uuid>, status: resolved | escalated, note: <text>}]
escalation: review_training_block | null
```

The window is at most 3 days for observe/caution and at most 7 for hold/escalate. (product heuristic)
Reassess within 7 days; use the patch's own return and escalation criteria to explain the next decision. (product heuristic)

## Prohibited actions

- Editing days 8–14.
- Adding sessions or changing run frequency.
- Moving, adding, or deleting strength sessions.
- Making up missed sessions.
- Raising severity from one raw metric.
- Restoring hard work because one metric normalized, without checking the patch's return criteria.
- Diagnosing a condition or treating a finding category as a diagnosis.
- Taking over a different open draft or silently changing its operation.

## Evidence and policy links

- `adaptive_coaching/exception_policy.md`: category meanings, evidence requirements, minimal-change ladder, return criteria, escalation, and spacing.
- P001–P006, P013, P015, P018, P024–P026.
- E-DATA-01, E-DATA-02, E-REC-02, E-REC-04.
