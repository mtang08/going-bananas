# Workflow: Training-Block Review

## Objective

Decide whether a multiweek running emphasis should **start, continue, extend, consolidate, transition, replace, or end**. A block is a reviewable planning hypothesis, not a promise that a fixed number of weeks will produce a specific adaptation. The workflow must preserve current clinical constraints, user commitments, and the approved calendar until a proposed change is accepted.

## Required loading

1. `COACHING_GUIDE.md`
2. Current athlete/app state, active block summary, and approved rolling plan
3. This workflow
4. `topics/periodization_and_training_blocks.md`
5. The recipe records relevant to the current or proposed objective
6. `topics/intensity_calibration_and_testing.md` when performance anchors are in question
7. `topics/races_tapers_and_transitions.md` only when a goal, benchmark, race, taper, or interruption is relevant
8. Existing symptom, recovery, progression, strength-scheduling, fueling, environment, or wearable topics only when triggered
9. Matching policy candidates; detailed evidence only for a consequential or disputed choice

Do not load the daily workflow, every recipe, or the full evidence corpus by default.

## Decision ID

`review_training_block`

Use `handle_goal_or_race_change`, `recalibrate_intensity`, or `assess_training_response` as related IDs when those are material subquestions.

## Inputs

### Minimum block definition

- `block_id` and version, or `null` if deciding whether to create one
- Primary objective stated as a decision-relevant capability or tolerance goal
- Start date, planned review date, and current status
- Maintained qualities and explicit non-goals
- Allowed session families and current progression dimension
- Completion indicators, review triggers, and constraints
- Approved 14-day plan and any provisional second-week intent

### Evidence of execution

- Planned versus completed sessions since the block began
- Number and quality of objective-relevant exposures
- Modifications, missed sessions, substitutions, and reasons
- Session execution: intended versus actual effort, repeat consistency, technique, and recovery
- Relevant volume, long-run, intensity, frequency, and strength-load context
- Prior recommendations and observed outcomes

### Evidence of adaptation and tolerance

- Comparable performance or submaximal-effort trends, with environmental and sensor quality flags
- Subjective effort and talk-test response where relevant
- Symptoms, function, and delayed response linked to exposures
- Recovery trends, illness, life stress, lower-body soreness, and fueling context
- Whether the next planned session remained possible after prior key exposures
- Benchmark/race result only with test conditions and uncertainty

### Changed context

- New, changed, postponed, or cancelled race/goal
- Travel, illness, injury-related interruption, clinician instruction, or schedule change
- Change in available run frequency or lifting commitment
- New evidence that the objective or intensity anchors were mis-specified

Missing observations remain `null` or `unknown`; absence of a recorded problem is not evidence that tolerance was good.

## Planning-layer authority

| Layer | May normally change | Should normally preserve | Escalate when |
|---|---|---|---|
| Daily check-in | Today's dose, terrain, mode, or placement; at most the next 1-3 days | Block objective, approved frequency, broader session sequence | Repeated modifications, function/symptom deterioration, or a change that cannot fit without pileup |
| Rolling-plan review | Concrete next 14 days, session order, one progression dimension, substitutions | Block objective and long-term direction | Several disrupted or failed objective-relevant exposures; goal/context change; block evidence no longer coherent |
| Block review | Objective, maintained qualities, eligible recipe families, progression strategy, review conditions | Long-term goals unless those changed | Major goal/season/context change or inability to define a useful block |
| Long-term direction | Goal priority, event sequence, broad future phases | Current approved plan until a narrower review translates the change | User decision or major context change |

The 14-day horizon and a typical 4-8-week block are product/coaching defaults, not validated physiological cutoffs.

## Review sequence

### 1. Confirm that routine block optimization is appropriate

Apply current clinician instructions and existing symptom/illness escalation guidance first. A block decision cannot convert progressive function loss, significant illness, or diagnostic uncertainty into a training optimization problem.

### 2. Reconstruct the block hypothesis

State, in one sentence:

> Given the current baseline and constraints, repeated exposure to **[session/tolerance emphasis]** while maintaining **[qualities]** is expected to improve **[observable capability]**, with review when **[date/condition]** occurs.

If the objective, baseline, or observable indicator cannot be stated, the proper outcome may be `replace`, `end`, or no explicit block. Do not infer an objective from the workout label alone.

### 3. Check exposure and data sufficiency

Separate three cases:

- **Enough relevant exposure to interpret:** several comparable objective-relevant sessions were completed with usable execution and follow-up data.
- **Too little exposure because the plan was not executed:** do not label physiological nonresponse; decide whether the objective remains feasible and whether to extend, consolidate, or replace.
- **Too little exposure because data are missing or incomparable:** lower confidence, collect a targeted observation, and avoid precise recalibration.

No universal number of sessions establishes sufficiency. Testing error, environmental differences, and within-athlete variability matter [E-CAL-04].

### 4. Separate objective status from tolerance

Classify objective status as:

- `achieved`
- `partially_achieved`
- `not_yet_resolved`
- `not_achieved`
- `not_assessable`

Then classify tolerance independently:

- `stable`
- `uncertain`
- `deteriorating`

A performance improvement with worsening function is not a successful block. Stable tolerance without measurable performance change may still justify continuation when the objective is durability, consistency, or technique.

### 5. Audit competing explanations

Before attributing success or failure to the block, check:

- adherence and whether the intended dose was actually delivered;
- heat, hills, terrain, wind, treadmill/track differences, and sensor quality;
- sleep, illness, life stress, fueling, and lower-body strength soreness;
- whether the intensity anchor was wrong;
- whether several variables changed at once; and
- whether the test or comparator was sensitive enough to detect the expected change.

Record unresolved attribution rather than choosing the most convenient explanation.

### 6. Check whether the planning context changed

A new high-priority race, large interruption, new clinical constraint, or changed available frequency may invalidate the original block even when the training itself was working. Route to `handle_goal_or_race_change` when applicable.

### 7. Choose exactly one block outcome

| Outcome | Use when | Do not use as |
|---|---|---|
| `start` | Baseline is adequate, objective is narrow and observable, prerequisites are met, and an explicit block will reduce decision ambiguity | A requirement to invent distant daily workouts |
| `continue` | Objective remains appropriate; adherence/tolerance are adequate; evidence is favorable or still too early but interpretable | Automatic continuation to a preset end date |
| `extend` | Progress is partial, objective remains valuable, and more comparable exposure is justified without simply repeating a failing plan | A way to avoid deciding why progress is unclear |
| `consolidate` | Recent load, symptoms, recovery, or execution suggest holding/reducing novelty while preserving the same objective | A mandatory every-N-weeks deload |
| `transition` | Objective is sufficiently achieved, race demands now deserve emphasis, or another quality becomes the higher-value next focus | Simultaneous progression of every quality |
| `replace` | The goal, constraints, available frequency, interruption, or original premise changed enough that a new objective is needed | A punishment for missed sessions |
| `end` | No explicit block is useful now, the objective is no longer appropriate, or routine coaching should pause; success is not required | A declaration of permanent nonresponse or failure |

### 8. Translate the outcome into the rolling plan

Specify only what the next 14 days need:

- primary target and maintained qualities;
- eligible recipe IDs;
- one main progression or consolidation lever;
- session-spacing and strength constraints;
- committed first-week intent;
- provisional second-week intent and the observation that will confirm it;
- what is deliberately not being progressed; and
- next review date and trigger conditions.

Do not create a workload pileup to compensate for missed sessions. Do not activate a recipe whose prerequisites are unmet.

### 9. Define a falsifiable follow-up

Choose one or two observations that could change the decision, such as repeatable execution at the intended effort, delayed response after a long run, comparable submaximal pace-effort response, or resolution of a scheduling conflict. Avoid an unbounded request to "monitor everything."

## Observable fact -> interpretation -> candidate action

Every material conclusion should use this structure:

- **Observable fact:** e.g., two of four planned threshold sessions were completed; both became uncontrolled in the final repetition; heat was materially higher in one.
- **Interpretation:** objective exposure is insufficient and partly confounded; this does not establish nonresponse.
- **Candidate action:** consolidate or extend with a smaller, effort-anchored recipe and a comparable follow-up; do not increase total hard work.

## Output contract

```yaml
operation: block_review
decision_id: review_training_block
block:
  block_id: string | null
  prior_version: string | null
  objective: string
  status_before: planned | active | paused | completed | ended | null
period_reviewed:
  start: YYYY-MM-DD | null
  end: YYYY-MM-DD
hypothesis_review:
  objective_status: achieved | partially_achieved | not_yet_resolved | not_achieved | not_assessable
  tolerance_status: stable | uncertain | deteriorating
  adherence_and_exposure_sufficiency: sufficient | insufficient_execution | insufficient_data | uncertain
  observable_facts: [string]
  interpretations: [string]
  confounders: [string]
outcome: start | continue | extend | consolidate | transition | replace | end
outcome_rationale: string
maintained_qualities: [string]
proposed_next_emphasis: string | null
rolling_14_day_implications:
  committed_intents: [string]
  provisional_intents: [string]
  eligible_recipe_ids: [RECxxx]
  progression_or_consolidation_lever: string | null
  preserved_constraints: [string]
  explicitly_not_progressing: [string]
review_plan:
  planned_review_date: YYYY-MM-DD | null
  completion_indicators: [string]
  early_review_triggers: [string]
references:
  policy_ids: [Pxxx]
  evidence_ids: [E-xxx-xx]
uncertainty:
  confidence: high | moderate | low
  missing_or_incomparable_inputs: [string]
  competing_explanations: [string]
approval:
  requires_calendar_change: boolean
  proposal_only: true
audit:
  data_through: ISO-8601 timestamp
  files_sections_loaded: [string]
  prior_decision_outcomes_used: [string]
```

## Prohibited inferences

- Do not call a block effective because one race or workout improved without considering conditions and measurement variation.
- Do not call an athlete a nonresponder from one block, one test, or poor adherence.
- Do not treat four, six, or eight weeks as a biological completion rule.
- Do not import elite volumes, double-threshold structures, or multiple weekly key days into a 3-4-run schedule.
- Do not let a race date justify cramming missed work.
- Do not change an approved calendar or block status without the product's approval/versioning step.
- Do not use a favorable wearable score to overrule symptoms or function.

## Evidence and policy links

- Periodization evidence and limits: E-PER-01 to E-PER-05; S056-S061
- Response/noise: E-CAL-04; S067-S068
- Interruption: E-TRANS-01; S072
- Taper/race transition: E-RACE-01 to E-RACE-02; S062-S063
- Candidate policies: P019, P021, P022, P023
- Existing progression/tolerance policies: P005-P009, P013-P016, P018
