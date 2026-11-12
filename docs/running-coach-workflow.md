# Living plan — usable running-coach workflow

Updated November 11, 2026. The latest user instruction permits automatic
persistence of validated AI coaching decisions. This supersedes the older
proposal → routine athlete acceptance gate and the earlier no-automatic-plan-
mutation constraint. Read-only and exploratory conversations still do not
activate plans; goals, cadence, and strength configuration remain explicit
athlete decisions.

## Objective and product boundary

Deliver the daily/weekly running-coach loop: observed training and response →
AI reasoning from selected research → concrete dated prescriptions → validated
calendar persistence → actual/feedback linkage → next review. A conversation
beside a dashboard or generic “usual easy run” advice does not meet the goal.

The installed Codex skill is the AI entry point. Its invoking model performs the
reasoning; the app retrieves facts, computes metrics, validates proposals and
persists revisions. No external model API credential, dashboard chat product,
or autonomous coaching scheduler is required. Ordinary sync, labels, metrics,
calendar expansion and page views never invoke a model.

The current phase is running. Preserve full-body strength and mobility in the
confirmed Week A/B rotation, with Strong as the lifting workflow. Do not turn
running planning into a new strength prescription system.

## Four vertical slices and stopping point

1. **Weekly plan → persisted calendar.** Review actual running, prior exposure,
   response, recovery, strength and selected KB evidence. Prescribe every run
   opportunity in a rolling 14-day window. Validate/activate atomically, retain
   accepted dates outside the horizon and revision history, and expose diffs.
2. **Daily decision → persisted calendar.** Read the active weekly strategy,
   today's exact session, recent actuals and reported feedback. Save either a
   no-change confirmation or a proportional patch of affected run slots, then read the same
   active session in the app and the next review.
3. **Detailed FIT analytics.** Inspect supported source capabilities, then add
   canonical laps/streams/interval/zone/drift analysis with provenance and
   appropriate interpretation. This is P1 and deferred from the usable core.
4. **KB and coaching refinements.** Expand research or analytical sophistication
   only after the core loop works. Existing selective, hash-checked KB retrieval
   is required now; exhaustive new research and all behavioral cases are P1.

Stop at a usable, verified P0 consisting of slices 1–2. Do not claim detailed FIT
analysis or full behavioral coverage merely because endpoints/tests exist.
Existing whole-run HR/pace/distance/time and observed tolerance support useful
P0 prescriptions with explicit uncertainty.

## Intended athlete workflow

1. **Baseline once.** Read the current structured profile, confirmed anchor,
   durable goals and Week A/B commitments. Structured current configuration
   overrides conflicting stale free-text notes. Ask only for essential missing
   facts, without rebuilding the weekly schedule manually.
2. **Weekly review.** Invoke `$going-bananas-coach review-week`. Read the last
   7–14 days against a preceding baseline: completed/modified/unknown sessions,
   effort, delayed symptoms/function, recovery coverage, strength and prior
   advice. The agent chooses a coherent strategy and concrete next 14 days,
   including purpose, usable duration/distance or repetitions, effort, reasons
   for hold/progression/change, and feedback that would alter the decision.
3. **Persist automatically.** The skill submits its structured proposal with
   exact evidence hash and expected revision ID. The API validates it and
   atomically activates dated sessions. The app shows prescriptions, provenance,
   revision/diff and uncertainty. No copying from chat or per-date manual entry.
   Stale/conflicting evidence requires fresh reasoning, never blind acceptance.
4. **Daily check-in.** Invoke `$going-bananas-coach today`, reporting current
   symptoms/function and energy. The coach starts with the active weekly plan.
   One poor sleep score does not automatically cancel training; current
   function, restrictions, illness, accumulated fatigue and session demands
   justify proportional decisions. A no-change decision is valid and persisted.
5. **Record response.** Runs sync from Garmin; label overrides remain
   authoritative. Link an unambiguous actual to the intended session, or review
   the ambiguity. Record effort, modifications and later symptoms. Unlinked or
   absent observations remain unknown, not inferred misses. Optional mobility
   remains optional. Plan revisions retain actuals and completion links.
6. **Close the loop.** The next daily/weekly invocation reads the same active
   prescriptions, saved agent review, actuals, links and feedback. No retelling
   of the week or attaching skill outcomes to unrelated legacy local rules.

## Evidence and acceptance requirements

- The invoking Codex model authors the training decision. A deterministic
  fixture generator or rule-based card is not evidence of AI coaching quality.
  Preserve distinct `codex_skill.v1` and legacy `local_rules.v1` provenance.
- Weekly output covers all parity dates over 14 days, including justified rest
  prescriptions where appropriate. Long-run intent belongs on weekends;
  strength/mobility commitments remain visible and intact. Use the baseline and
  actual response to set doses, not a universal progression percentage.
- Daily output retains weekly strategy and unaffected sessions; changes may
  patch affected run slots within the rolling 14 days, including the next run
  after a rest-day check-in. Explicit weekly review handles broader strategy changes.
  Do not manufacture catch-up debt or alter completed/locked sessions.
- The revision audit cites real activity/check-in IDs or recovery dates and
  selected KB policy/evidence/source IDs for material claims, distinguishing
  observations from inference. Source validity is necessary but does not prove
  the athlete-specific conclusion. Store uncertainties and follow-ups.
- Validate stale/conflicting versions, parity, weekend long runs, completeness,
  protected sessions, plan boundaries, repeat/no-change calls, prior completion
  links, rollover between strength weeks, and rollback history. Broad server
  rejection guards are not automatic dose recommendations or injury clearance.
- Test helper → API → active calendar → completion/feedback → next context on
  synthetic data. Also inspect real profile/context read-only. Transport tests
  prove persistence mechanics; an actual Codex exercise from live-format
  synthetic evidence is separate evidence of reasoning and adaptation.
- Never seed a synthetic plan into real mode. Back up real schema changes and
  verify mode isolation. Keep private raw/proposal/profile data out of tracked
  examples. Do not promise all 15 KB cases have passed without executing them.

## What supports P0 and what stays uncertain

Existing foundations include Garmin summary activities/recovery and coverage,
Strong source-faithful history, deterministic labels/overrides, recurrence,
check-ins, manual plans/completion links, selective research and private memory.
The agent integration adds one plan/revision contract and a single daily/weekly
context path rather than a separate chat system.

Average HR is a whole-run summary. Intrarun zones, laps, interval detection,
HR drift and terrain/weather-adjusted adaptation are not established by it.
Missing recovery/check-ins and ambiguous actual links remain explicit. No
wearable metric establishes tendon tolerance, and this product does not diagnose
conditions or replace clinician restrictions. Detailed FIT work and additional
research/behavioral evaluation remain deferred.

See [P0 implementation and verification](p0-implementation.md) for the current
checkpoint; [live progress](live-progress.md) preserves release history and
verified evidence. Setup, invocation and rollback commands are in [README](../README.md)
and the skill's [app-access contract](../skills/going-bananas-coach/references/app-access.md).
