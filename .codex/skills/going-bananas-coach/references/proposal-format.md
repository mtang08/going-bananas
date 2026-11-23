# Proposal writing format

Read this before writing proposal JSON or presenting a saved proposal. Populate
the format from the current snapshot and validated proposal; do not invent
missing facts.

## Saved fields and chat

The app shows only the saved short form; the athlete scans it there and accepts
or rejects changes. The chat carries the depth: the observations with their
numbers, the research, trade-offs, alternatives, and answers to questions.
Write each field from the decision itself. Never paste chat paragraphs into
fields, and do not fill a field with invented facts to satisfy a rule; an
unknown that matters goes in `uncertainty`.

## Proposal fields

Limits are enforced and count characters; a single number is a maximum. Each
field is one plain line: no Markdown, bullets, line breaks, or IDs (only
`coach_note` may use blank lines and `- ` bullets). Keep evidence, policy, and recipe IDs in their JSON arrays;
the app shows cited sources by title.

| Field | Holds | Limit |
| --- | --- | --- |
| `headline` | The decision and its purpose. | 1–100 |
| `why[]` | One reason each, with a `kind` (below). | 1–5 items; `text` 1–160 |
| `uncertainty[]` | The main unknowns. | 0–2 items of 140; at least 1 unless `confidence.decision` is `high` |
| `change_triggers[]` | Feedback that would change this decision: `when` an observable sign, `then` the action. | 0–3 rules; `when`, `then` 1–90 each; at least 1 except in exception reviews |
| `next_check` | `on`: the date to check in; `check`: what to report or look at. | `on` from today to today+14; `check` 1–120 |
| `coach_note` | Only what fits no other field; usually null. | 1–400, optional |
| `changes[].reason` | Why this session changes; do not repeat the `why` list. | 1–120 |
| Session `intent` | The session's purpose label, e.g. "Threshold control"; not the prescription. | 1–60 |
| Session `brief` | See "Session brief". | below |
| Step `target.effort_cue` | The step's target and essential cue; put RPE here with numeric `low`/`high` null. | 60 |
| Block `objective` | The block's aim in one phrase. | 1–80 |
| Block `why[]` | Reasons for this block, with a `kind`. | 1–4 items; `text` 1–160 |
| Block `indicators[]` | What the block review judges: `source` (`quality_progression`, `aerobic_efficiency`, `key_sessions`, `rpe_vs_intent`, `other`), `label` ("Tempo reps at the same RPE"), and `progress_when` ("pace 2% faster at RPE 7 or lower"). | 0–4; `label` 1–60, `progress_when` 1–100; at least 1 when `benchmark` is null |
| Block `maintained_qualities[]` | Qualities kept while the focus is elsewhere. | 0–5 items of 40 |
| Block `non_goals[]` | What the block deliberately leaves out. | 0–5 items of 60 |
| Block `constraints[]` | `kind` (a short tag) and `text`. | 0–5; `kind` 1–24, `text` 1–120 |
| Block `early_review_triggers[]` | Signs that call for an early block review. | 0–4 items of 100 |
| Block `build_outline[].emphasis` | One step's emphasis toward race day. | 1–60 |
| `anchor_changes[].conditions` | Test conditions that affect the anchor. | 120 |

`why` kinds keep observations, research, and inference apart. `observation` is
measured or reported data from the snapshot. `research` is KB evidence or
policy; cite its IDs in `evidence_ids` or `policy_ids`, or the reason fails.
`inference` is your reasoning about this athlete. `priority` is the athlete's
stated goal or constraint.

Validation returns every error at once. `V1.schema` at a path such as
`why.2.text` means that value is too long or malformed: shorten that field only
and resubmit. `V24.id_in_text` means an ID appears in prose: remove it from the
text. The `V24` and `V25` messages name the missing item.

## Session brief

The coach writes `brief`; the athlete writes `notes`. Never write `notes`: the
schema rejects the key, and coach changes leave the athlete's notes alone.

| Brief slot | Holds | Limit |
| --- | --- | --- |
| `effort` | `rpe_low`, `rpe_high` (1–10, low ≤ high) and `feel`, e.g. "controlled". | `feel` 1–40 |
| `focus[]` | Execution cues not already in the steps. | 0–2 items of 80 |
| `adjust_if[]` | `when` a sign during or before the session, `then` the change. | 0–2 rules; `when`, `then` 1–90 each |
| `why` | This athlete's reason for this session; not research. | 1–120 |

Every run dated in days 1–14 that a change adds, or modifies in anything other
than `slot`, `locked`, or `brief`, needs a `brief` (`V25.brief_required`). Days
15 onward carry only `recipe_id`, `intent`, and `planned_duration_s`; the
review that brings a run into days 8–14 adds its structure and brief together.
The snapshot shows each session's current `brief`; carry it over unchanged when
it still fits. Do not restate the steps, durations, or paces in the brief.

## One-time strength omissions

Use one selectable change per omitted lift in a strength-editing review. Set its `material_flags` to `["strength_omission"]` and use `reason` (1–120) to explain that occurrence, for example athlete travel, recovery after a key session, or preparation for a race. An omission is not a run, so it carries no `brief`.

- For an accepted future strength session, use `op: "delete"` and its calendar `session_uid`.
- For a lift still to be planned, use the date and lift label from `goals_and_constraints.confirmed_strength_sessions`. Use `op: "add"` with only `local_date`, `kind: "rest"`, and the lift label as `intent` in `after`; any other field, `brief` included, makes the change invalid. The app displays this flagged entry as **Skip lift** and records the decision without adding a rest workout.
- Carry forward accepted omissions shown in `goals_and_constraints.accepted_strength_omissions`. Create a new change only for a new omission. Keep the remaining lifts and subsequent weeks on their usual pattern. A makeup lift is optional.

## Exception, race, and benchmark fields

These fields appear only in exception, post-event, and benchmark block reviews.
The same plain-text rules apply.

| Field | Populate with | Limit |
| --- | --- | --- |
| `exception.triggering_evidence` | The observations that triggered the finding, in plain words. | 300 |
| `exception.relevant_context` | Confounders and current safety status. | 300 |
| `exception.confidence` | `low`, `moderate`, or `high`. | One value. |
| `exception.unchanged[].reason` | Why that committed session stays as planned. | 120 |
| `monitor`, `return_criteria`, `escalate_criteria` | Observable signs to watch, conditions for returning to the plan, and conditions for escalating. | 1–3 items each; 120 per item |
| `event_review.pacing`, `effort_and_limiter`, `recovery_observation`, `training_implication` | One or two sentences each. | 240 each |
| `event_review.conditions`, `event_review.symptoms` | Race conditions; symptoms during or after. | 160 each |
| `event_review.outcome`, `event_review.compared_with` | Block reviews only: the benchmark outcome and the prior result with the same protocol. | One value; `compared_with` 120 |
| Block `benchmark` | `protocol` (repeatable), `progress_if`, `consolidate_if`. | `protocol` 1–160; the others 1–120 |
| `patch_resolutions[].note` | What changed since the patch was set. | 160 |

`exception.confidence` uses `moderate`, matching the top-level `confidence`.

## Repeated workout steps

Represent identical intervals with the schema's `repeat` block instead of
copying the same steps. Keep each step's `effort_cue` to its target and essential
execution cue; put session-wide cues in the brief's `focus`. Preserve different
targets or progression as distinct steps.

Prescribe recovery count explicitly. For five work intervals with recovery
only between them, encode four repeats of `[work, recovery]`, followed by the
fifth work interval. Do not encode five work/recovery pairs unless recovery
also follows the final interval. The app can consolidate either form without
changing the saved workout. In the chat prescription, write for example
“12 min warm-up; 5 × 3 min work, 2 min recovery between reps; 8 min cool-down,”
then state the work and recovery cues once. Use the actual durations, targets,
and counts from the proposal; this is a formatting example, not a workout
recommendation.

## Written proposal in chat

Use this order: headline, depth paragraphs, pending line, table, later days,
what would change the decision, then the next check-in. The depth paragraphs
may run longer than the saved `why`: say what was observed, what the research
says, and what you infer for this athlete, and name the main uncertainty.
Use coherent prose, not stream-of-consciousness bullets, and show no IDs or
evidence tags. Include a review link only when the app returns one. Use the exact days, session names, workout
prescriptions, and efforts from the saved proposal.

```markdown
<headline>

<depth paragraph: observations and what they mean>

<optional one or two paragraphs: research, trade-offs, alternatives, uncertainty>

Pending your review; nothing applied. [Review proposal](<returned app link>)

| Day | Session | Prescription | Effort |
| --- | --- | --- | --- |
| <day, date> | <session> | <duration/distance, steps, target and essential cues> | <RPE low–high, feel> |

Days 8–14 (provisional):
- <day, date> — <session>: <duration and main set>

Later weeks (provisional):
- Week of <Monday date>: <key sessions and their purpose, one line>

### Would change this
- <when> → <then>

### Next check-in

<weekday, date>: <check>
```

When the proposal reaches past day 7, keep the table to days 1–7, list days 8–14
concisely, and give each later Monday–Sunday week one line naming its key
sessions and purpose; the app shows every session's details. Omit a section the
proposal does not reach. Leave the effort cell empty for a session without a
brief. Omit "Would change this" when `change_triggers` is empty.

For a block change, name the goal race with its date and the weeks to race day,
and give the build outline as one line, for example "4 wk threshold durability,
then 5 wk half-marathon-specific endurance, then 4 wk race-specific sharpening,
taper, race". When the block has no target, say there is no upcoming event, or
why the target is unchanged.

Keep the table limited to the actual scope: list proposed changes for a change
proposal, or the complete schedule when the proposal supplies the full plan.
Identify moved or removed sessions in the prescription where relevant. Omit
empty sections. For a no-change proposal, say “Keep the current plan” and
explain that the app records the athlete's acknowledgment. Use the pending
wording only after submission succeeds. Never imply that a proposal has been
applied.

## Exception and race templates

For an exception review, insert these blocks between the depth paragraphs and
the "Pending your review" line of the base template; its "Plan impact" block
replaces the table. Use the labels the app shows (for example, severity
`caution` is "Caution" and `escalate` is "Needs bigger review"). Omit lines
whose field is empty.

```markdown
### Exception classification
- Category: <category label>
- Severity: <severity label>
- Triggering evidence: <triggering_evidence>
- Relevant context: <relevant_context>
- Confidence: <confidence>

### Plan impact
- Sessions affected: <day, date — session>
- Exact changes: <one line per change: was → now>
- Patch window: <start>–<end> (<ladder label>)
- Sessions explicitly unchanged: <day, date — session — reason>

### Reassessment
- What to monitor: <monitor>
- Return conditions: <return_criteria>
- Escalation conditions: <escalate_criteria>

### Plan history
- Patch relative to plan version <base_calendar_version>; provisional days untouched.
- Reason per change: <day, date — changes[].reason>
```

For a post-event review, insert this block in the same place. For a block review
with a completed benchmark, title it `### Benchmark review` and include the
outcome and compared-with lines; omit them otherwise.

```markdown
### Race review
- Outcome: <outcome label>
- Compared with: <compared_with>
- Pacing: <pacing>
- Effort and limiter: <effort_and_limiter>
- Conditions: <conditions>
- Symptoms: <symptoms>
- Recovery observation: <recovery_observation>
- Recalibration: <recalibration label>
- Training implication: <training_implication>
```

Example; use the saved proposal's real values.

```markdown
Replace Wednesday's intervals with easy running or rest while fatigue settles.

Tuesday's easy run was substantially harder than intended, fatigue has remained elevated for two days, and sleep has been below normal. No injury symptoms are reported. Replace Wednesday's interval session with easy running or rest, retain Friday's plan provisionally, and reassess after Wednesday's response. Do not move the interval session automatically to Thursday.

### Exception classification
- Category: Fatigue and recovery
- Severity: Caution
- Triggering evidence: Tuesday's easy run felt much harder than its expected effort; fatigue elevated for two days; sleep below normal.
- Relevant context: No injury symptoms reported.
- Confidence: Moderate

### Plan impact
- Sessions affected: Wednesday — interval session
- Exact changes: Wednesday: intervals → easy running or rest
- Patch window: Wednesday (Next session only)
- Sessions explicitly unchanged: Friday — retained provisionally; Thursday — the interval session is not moved there

### Reassessment
- What to monitor: Wednesday's response, fatigue, sleep
- Return conditions: fatigue and sleep back to usual after Wednesday's easy response
- Escalation conditions: fatigue or poor sleep persisting past Wednesday, or any symptom or illness

### Plan history
- Patch relative to plan version <base_calendar_version>; provisional days untouched.
- Wednesday: replace intervals — repeated fatigue, poor sleep, and an easy run above its intended effort.

Pending your review; nothing applied. [Review proposal](<returned app link>)

### Next check-in

Thursday, 26 November: Wednesday's effort, fatigue, and last night's sleep.
```
