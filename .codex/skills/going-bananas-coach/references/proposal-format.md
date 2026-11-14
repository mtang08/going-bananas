# Proposal writing format

Read this before writing proposal JSON or presenting a saved proposal. Populate
the format from the current snapshot and validated proposal; do not invent
missing facts. The goal is a compact, readable prescription with its reasoning
up front.

## Proposal fields

Keep the existing JSON schema. These are writing conventions, not new fields.
Use plain text; blank lines separate paragraphs and `- ` starts a bullet. Do not
put Markdown headings, bold markers, tables, or evidence tags in fields.

| Field | Populate with | Length target |
| --- | --- | --- |
| `summary` | The main training decision and its purpose; this is the opening focus sentence. | One sentence, at most 25 words. |
| `rationale` | One or two short, coherent prose paragraphs explaining the observations, plan implications, what stays in place, and material uncertainty. | 1–2 paragraphs; aim for at most 80 words total. |
| `changes[].reason` | A short reason for this specific session change. Avoid repeating the top-level rationale; include tradeoffs or uncertainty only when material. | Required by the schema; one concise sentence is usually enough. |
| Session `intent` | The session's purpose, not its entire prescription. | One short phrase. |
| Session `notes` | Execution cues or limits not already expressed by the structured workout. | Up to three short dash bullets. |
| `follow_up` | When to check in and which observation would guide the next decision. | One sentence, at most 30 words. |

Put workout durations, distances, and targets in the structured session fields.
Keep required evidence/policy/recipe IDs in their JSON arrays. Do not repeat
the workout or a research essay in the opening copy. Populate a concise reason
for every changed session. Keep it brief when the top-level rationale already
explains the decision; the app may collapse session-level details in its review
display.

## Exception, race, and benchmark fields

These fields appear only in exception, post-event, and benchmark block reviews.
The same plain-text rules apply.

| Field | Populate with | Length target |
| --- | --- | --- |
| `exception.triggering_evidence` | The observations that triggered the finding, in plain words. | At most 600 characters; aim for 2 sentences. |
| `exception.relevant_context` | Confounders and current safety status. | At most 600 characters. |
| `exception.confidence` | `low`, `moderate`, or `high`. | One value. |
| `exception.unchanged[].reason` | Why that committed session stays as planned. | At most 200 characters; one clause. |
| `monitor`, `return_criteria`, `escalate_criteria` | Observable signs to watch, conditions for returning to the plan, and conditions for escalating. | 1–3 items each; at most 200 characters per item. |
| `event_review.*` | Pacing, effort and limiter, conditions, symptoms, recovery observation, recalibration, and training implication. | One or two sentences each; at most 600 characters (`conditions` and `symptoms` at most 400). |
| `event_review.outcome`, `event_review.compared_with` | Block reviews only: the benchmark outcome and the prior result with the same protocol. | One value; `compared_with` at most 300 characters. |
| `patch_resolutions[].note` | What changed since the patch was set. | At most 300 characters. |

`exception.confidence` uses `moderate`, matching the top-level `confidence`.

## Repeated workout steps

Represent identical intervals with the schema's `repeat` block instead of
copying the same steps. Keep each step's `effort_cue` to its target and essential
execution cue; put session-wide explanation in the rationale and non-repeated
execution limits in session notes. Preserve different targets or progression
as distinct steps.

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

Use this order: focus sentence, one or two rationale paragraphs, concise table,
then next check-in. Put the reasoning before the table; use coherent prose, not
stream-of-consciousness bullets. Keep the prescription column to the workout
prescription and essential execution cues. Include a review link only when the
app returns one. Use the exact activity days, session names, and workout
prescriptions from the saved proposal.

```markdown
<summary — one short focus sentence>

<rationale paragraph 1>

<optional rationale paragraph 2>

Pending your review; nothing applied. [Review proposal](<returned app link>)

| Day | Session | Prescription |
| --- | --- | --- |
| <day, date> | <session> | <duration/distance, steps, target and essential cues> |

### Next check-in

<follow_up>
```

Keep the table limited to the actual scope: list proposed changes for a change
proposal, or the complete schedule when the proposal supplies the full plan.
Identify moved or removed sessions in the prescription where relevant. Omit
empty sections. For a no-change proposal, say “Keep the current plan” and
explain that the app records the athlete's acknowledgment. Use the pending
wording only after submission succeeds. Never imply that a proposal has been
applied.

## Exception and race templates

For an exception review, insert these blocks between the rationale paragraphs
and the "Pending your review" line of the base template. Use the labels the app
shows (for example, severity `caution` is "Caution" and `escalate` is "Needs
bigger review"). Omit lines whose field is empty.

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
- Patch relative to plan version <base_calendar_version>; days 8–14 untouched.
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
Caution: unexpected recovery disruption.
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
- Patch relative to plan version <base_calendar_version>; days 8–14 untouched.
- Wednesday: replace intervals — repeated fatigue, poor sleep, and an easy run above its intended effort.

Pending your review; nothing applied. [Review proposal](<returned app link>)
```
