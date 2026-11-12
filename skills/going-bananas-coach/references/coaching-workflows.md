# Daily and weekly coaching

Use this when the athlete invokes `today`, a morning check-in, `review-week`, or
weekly planning. You, the invoking Codex agent, perform the AI reasoning. The
helper only retrieves and persists; it has no generic dose generator.

## Shared evidence

Use `data.context` in the agent context response. Read computed recent/prior
period comparisons, comparable runs and average HR availability, coverage,
check-ins and delayed timing, accepted plan/session links, unlinked/ambiguous
actuals, strength history/schedule, and prior agent revisions/reviews. Fields
that are absent, null, stale, or incomplete remain explicitly uncertain.
Do not reconstruct all load arithmetic from raw history if app summaries exist.
Do not count Strong/Garmin duplicates twice or compare unknown lifting units.

Read the guide and selected workflow prose in `data.prose`. Load extra topics
and policy/source records with `knowledge` only where they affect this decision.
Typically weekly planning needs aerobic progression and hybrid scheduling;
quality sessions need intensity/method guidance; long-run or tendon concerns
need the corresponding topic. Cite actual activity/check-in IDs or recovery
dates for athlete claims, and real policy/evidence/source IDs for research
claims. Explain the inference connecting them. Do not cite a wearable score as
proof of tendon tolerance or a paper as proof of this athlete's fitness.

## Review the week and prescribe the next two

1. Retrieve `review-week` and sync status. Sync if requested, reusing active
   jobs; poll briefly with updates, and mark incomplete datasets provisional.
2. Review the last 7–14 days against the preceding baseline and prior planned
   exposures. Distinguish completed/modified/explicitly skipped from unknown;
   inspect delayed response and what happened after prior advice. Separate
   adaptation signals from tolerance and missing reports.
3. Choose a weekly strategy, with an explicit reason to hold, progress,
   redistribute, or reduce. Preserve the alternating strength/mobility rhythm.
   Use recent comparable session duration/distance/effort and response to anchor
   actual prescriptions. No arbitrary percentage progression or a default
   “usual easy run” in place of a usable dose. If data is sparse, choose a
   conservative concrete exposure within observed tolerance, state why that
   choice is provisional, and name the feedback needed to refine it.
4. Author every parity run date in the rolling `as_of` through `as_of + 13`
   window. Rest/cross-training alternatives may occupy a scheduled run date
   when justified, without moving the cadence or accumulating debt. Long-run
   intent is limited to Saturday/Sunday. Include easy/quality/long purpose,
   usable duration or distance, effort guidance, and a complete warm-up/main/
   recoveries/cool-down structure when prescribing repetitions. Explain
   strength interactions and hold/modify logic for the second week. Do not
   prescribe strength sets or overwrite its rotation.
   For a completed or locked slot, copy its existing target exactly, omitting
   only server `provenance`/`revision_id` metadata. Rephrasing its reason or
   prescription counts as changing it; put any new interpretation in the review.
5. Build the structured proposal with the unchanged evidence hash and current
   revision ID from this context. Follow `schema`, including `review` fields and
   uncertainty/follow-up. Keep a concise `weekly_strategy` that a later daily
   invocation can preserve. Populate `review.evidence` with the actual IDs/dates
   and KB references behind the material decisions, not decorative citations.
6. `apply` the proposal; server validation activates it automatically. Inspect
   the returned diff and fresh context. Report concrete dated prescriptions,
   progression rationale, strength interaction, uncertainty, and what to watch.
   If nothing changed, say the existing prescriptions were retained and why.

Do not move or replace completed historical sessions. Preserve existing accepted
sessions outside the rolling window. Never overwrite a later revision after a
conflict. Re-read and reason again when new actuals/check-ins change the evidence.

## Coach today

1. Retrieve `today`, active weekly strategy and session, current observations,
   and sync status. If there is no active weekly plan, perform the weekly
   workflow first when the request authorizes planning; otherwise explain the
   missing prerequisite and give clearly provisional conversational guidance.
2. Save the reported check-in where authorized. Ask only for essential missing
   symptom/function/energy or restriction information; do not invent a report.
   Fresh context after the check-in supplies the proposal's evidence hash.
3. Compare today's prescription with recent execution, delayed symptoms,
   recovery trends and the demands of today's strength/mobility. A good
   wearable score never clears worsening function. One poor night with normal
   reported function need not change a well-tolerated session. Several days of
   deterioration, illness, or meaningful symptom change may justify a more
   material reduction. Explain why the chosen adjustment is proportional.
4. Save a daily proposal with `sessions: []` to retain the plan, or replace the
   smallest affected set of run slots within the rolling 14-day window. This
   permits adjusting the next run after a rest-day check-in. Keep the weekly
   strategy and every unaffected prescription.
   Rest days and optional mobility do not become catch-up runs. If the weekly
   strategy itself needs revision, use an explicit weekly review instead of
   silently rewriting the horizon through a daily call.
5. Verify the saved revision/context. Reply with today's exact session, change
   or confirmation, concise evidence, uncertainty, and what to observe during
   and after it. State what changes would warrant reassessment.

## Close the loop

Runs sync as actual observations. Completion is linked through the app's plan
completion flow; review ambiguous matches instead of silently assigning them.
Use reported effort, modification notes, immediate and next-day feedback as
observations. Missing feedback stays unknown. The next invocation reads the
same active session, prior agent revision/review, check-ins, and actual links.
If a linkage is unavailable, disclose it and retain the actual observation;
do not attach the outcome to unrelated legacy rule-generated advice.
