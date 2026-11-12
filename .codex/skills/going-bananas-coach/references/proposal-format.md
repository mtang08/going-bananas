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
