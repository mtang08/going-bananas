# Workflow: Weekly and Rolling-14-Day Review

## Objective

Review what actually happened, not just what was prescribed; evaluate adaptation and tolerance across the athlete’s agreed rolling-cycle rhythm; and propose the next cycle segment without silently changing frequency or sacrificing meaningful strength training.

## Required loading

1. `COACHING_GUIDE.md`
2. Current athlete/app summary and active plan
3. This workflow
4. `topics/aerobic_progression.md` plus any topic implicated by the week
5. Relevant compact policies
6. Evidence/source files only for unresolved questions

## Review horizons

- **Last 7 days:** useful for calendar logistics, but may contain three or four runs depending on cycle phase.
- **Rolling 14 days:** primary planning unit; captures seven intended runs and both weekly quality/long-run exposures.
- **Rolling 4–8 weeks:** continuity, trend, illness interruption, symptom-free consistency, repeated scheduling conflicts, and whether prior advice worked.

Do not compare calendar weeks as though they should contain equal run counts.

## Inputs

### Planned versus completed

- Session type, purpose, date, duration/distance, and intended intensity
- Completed sessions and omissions
- Strength sessions with lower-body emphasis, novelty, and proximity to failure when available
- Mobility and cross-training
- Plan changes recommended previously and their outcomes

### Tolerance/adaptation

- PTT symptoms during, shortly after, next morning, and a later follow-up window
- Walking/daily function and any recurrent pattern by duration, hills, surface, pace, or lifting proximity
- Session RPE and whether pace/HR matched comparable conditions
- Sleep/fatigue/illness trends, not one-day scores
- Quality-session execution, long-run response, and strength quality
- Fueling context for failed or unusually difficult key sessions when available

### App-computed summaries

- Running totals for 7/14/28 days, but never as automatic safe limits
- Individual-run durations/distances and recent longest comparable run
- Number and spacing of demanding physiological/mechanical exposures
- Adherence and symptom-free consistency
- Standardized pace–HR/RPE trends with environmental/sensor exclusions
- Missing-data and data-quality flags

## Process

### 1. Reconstruct actual versus planned

Classify every planned item as completed as planned, modified, moved, missed, or replaced. Explain modifications. Do not call a missed session a deficit to repay.

### 2. Separate adaptation from tolerance

**Adaptation signals** may include lower RPE at comparable work, improved pace at similar effort under similar conditions, better interval control, or maintained strength performance.

**Tolerance signals** include stable walking, no worsening delayed tendon response, normal recovery between exposures, and ability to complete the next planned session. A faster run with worse delayed symptoms is not a clean positive adaptation.

### 3. Audit confounders

Before attributing a trend to fitness or overreaching, inspect heat/humidity, hills, surface, sensor quality, route, fueling, illness, sleep, life stress, and strength soreness. Mark unresolved attribution.

### 4. Review the 14-day load shape

Do not rely on ACWR, the 10% rule, or a long-run percentage cap. Inspect:

- Whether one run was novel relative to recent comparable runs
- Whether long run, quality work, and lower-body lifting clustered
- Whether both volume and intensity increased
- Whether a new surface, hill, shoe, stride/plyometric, or strength stimulus was added
- Whether the “easy” sessions were truly low effort

### 5. Evaluate prior advice

For each material change, record: recommendation, reason, compliance, observed result, delayed result, and whether the policy should be retained, calibrated, or questioned. Do not learn from an outcome when key data were missing or multiple variables changed.

### 6. Select the next cycle’s priority

Choose one primary running target:

- consolidate continuity,
- add easy-run duration,
- extend the long run,
- progress/rotate one quality dose,
- restore training after illness, or
- reduce mechanical load while preserving aerobic work.

Keep other major variables broadly stable. Strength remains twice weekly unless current goals/instructions change. A cutback/consolidation segment is responsive, not a mandatory every-N-weeks rule.

### 7. Draft the next cycle segment

Use principles and illustrative placement rather than inventing an exact calendar when current session dates are unknown. Check the current preferred strength days first; consider alternate strength days rotation only when it better protects the priorities and matches the actual two-week cycle. A current mobility session is retained unless the user changes it.

### 8. Define observation targets

Every proposal needs one or two checks that can confirm or refute it—for example, delayed response after the long run, RPE on a standardized easy run, or whether lower-body work interferes with the next key run.

## Weekly output contract

```yaml
period_reviewed:
  start: YYYY-MM-DD
  end: YYYY-MM-DD
  primary_horizon: rolling_14_days
actual_vs_planned:
  summary: string
  completed_as_planned: integer | null
  modified: integer | null
  missed: integer | null
  key_differences: [string]
adaptation_signals: [string]
tolerance_signals:
  favorable: [string]
  concerning: [string]
  delayed_symptom_findings: [string]
strength_running_interactions: [string]
confounders_and_data_quality: [string]
prior_advice_outcomes: [string]
next_cycle_proposal:
  primary_target: string
  sessions_or_placement_principles: [string]
  changes_from_current_plan: [string]
  preserved_commitments: [string]
tradeoffs: [string]
references:
  policy_ids: [Pxxx]
  evidence_ids: [E-xxx-xx]
uncertainties: [string]
what_would_change_the_recommendation: [string]
audit:
  data_through: ISO-8601 timestamp
  files_sections_loaded: [string]
```

## Prohibited inferences

- Do not infer a PTT diagnosis from flat feet or medial ankle tenderness.
- Do not call an observed pace easy without effort/context.
- Do not use favorable Garmin scores to overrule symptoms.
- Do not turn a previously tolerated higher-volume week into proof that any return rate is safe.
- Do not interpret missing HRV or subjective feedback as normal.
- Do not claim cross-training preserves running durability one-for-one.
- Do not delete strength merely to make a running plan easier to schedule.
