# P0 implementation and verification

November 11, 2026. The [living workflow](running-coach-workflow.md) is the current
product contract. The user permits automatic activation of validated running
proposals. The installed Codex skill supplies AI reasoning; no separate model
API credential is needed. Weekly persisted plans and daily persisted decisions
are the current core. FIT analytics and further KB refinements are deferred.

## Implementation audit

- **Evidence/context:** the agent API retrieves current structured profile,
  actual sessions/HR summaries, recovery and baseline comparisons, check-ins,
  delayed feedback, strength context, plans, prior reviews, and selected KB.
  Notes may be stale; structured confirmed configuration is authoritative.
- **Weekly persistence:** a model-authored complete rolling 14-day proposal
  carries evidence hash, expected revision, review/rationale and KB source IDs.
  Validation/activation is atomic, retains accepted dates outside the horizon,
  and records immutable revision/session membership rather than deleting prior
  observations. Context and schema are inspectable without invoking a model.
- **Daily persistence:** start from the active weekly strategy and prescription;
  `sessions: []` confirms it, or patch affected run slots in the next 14 days.
  Retain unaffected sessions,
  strength commitments, completion links and history. No-change is a valid
  saved decision. Changed evidence and stale versions require a fresh review.
- **Skill and helper:** `today`, `review-week`, `schema`, `apply`, `inspect`,
  `revert`, reported check-ins, completion links and private scoped memory.
  The helper transports model-authored JSON; it does not invent a prescription.
- **Dashboard:** active prescriptions, revision diffs and uncertainty should be
  reviewed alongside the calendar; legacy rules retain separate provenance.
  Final browser verification belongs in the verified-evidence record below.

## Setup, use, inspect and undo

Follow [README](../README.md) for local PostgreSQL, migration, build and startup,
Garmin sync and skill installation. Normal invocations are
`$going-bananas-coach review-week` and `$going-bananas-coach today` in Codex.
The app must be running in real mode for athlete coaching. Invocations are
manual; no daily coaching scheduler is installed.

The skill's [app-access reference](../skills/going-bananas-coach/references/app-access.md)
documents context/schema inspection, proposal JSON, no-change calls, retry
semantics, completion links, and version-checked rollback. A successful save
must be verified in fresh context. A rollback records a new revision and does
not erase actual observations or feedback.

## Verification and current evidence

## Agent-plan completion checkpoint — November 11, 2026

The persisted weekly/daily running-coach workflow is complete for the documented
P0 scope. Weekly prescriptions, daily confirmations or adjustments, immutable
revision history, protected completion links, and version-checked rollback are
wired through the helper, API, and calendar. This work does not add FIT metrics,
blocks, intensity anchors, or an autonomous coaching scheduler.

Final verification on synthetic data: 68 backend tests, 24 frontend tests,
49 PostgreSQL integration tests, 13 helper tests, and nine browser acceptance
cases passed. Lint, type checking, and production build passed. Browser tests
ran against a separate demo app on port 8019 using `PLAYWRIGHT_BASE_URL`; the
existing app and real database were not stopped, migrated, or seeded.

Completion fixes reject malformed evidence reference lists with 422, require an
upcoming accepted running plan for daily confirmation, retain the revision
reviewed when opening Undo, and omit workout-completion controls for rest slots.
The load-test failure was a DST-sensitive fixture issue: prior runs are now
seeded at local noon on their intended dates. Existing load bounds are unchanged;
regressions cover equality, per-session excess, and aggregate excess.

The current user-facing contract is [running-coach-workflow.md](running-coach-workflow.md).
The v0.9 redesign remains a separate, partially supplied specification; its
missing task packets and Garmin inventory gates have not been implemented here.

Evidence below is scoped to what was actually executed, not the capabilities
promised by the contract.

- Before agent-plan migrations, the lead created
  `private/real/backups/pre-agent-plans-20261111.tar.gz` with 1,585 files.
- The existing real profile was read-only verified at version 4, confirmed
  November 10 run anchor and the alternating strength/mobility rotation. No
  synthetic coaching plan was inserted into the real database for testing.
- `python3 scripts/test_coach_skill.py`: 12 isolated helper tests passed. They
  verify mode-before-write, unchanged model-authored payload/idempotency key,
  version-conflict stopping, context routing, scoped memory preservation and
  rollback validation. They use synthetic mocked transport and make no app
  writes; they do not establish end-to-end persistence or coaching quality.
- The lead verified `make check`: 58 backend tests, 22 frontend tests, lint,
  type checking and build; the browser suite passed nine synthetic cases,
  including saved weekly rendering, daily patch, refresh, and rollback.
- Real schema migration `0009_agent_plan` followed the backup. The new real
  agent context was read-only verified: profile v4; seven recent runs with
  average HR present on all seven; 35 baseline and six recent-seven recovery
  observations per sleep/HRV/resting-HR metric; seven upcoming run opportunities;
  available KB; no active agent revision. No real plan was created by testing.
- The updated five-file skill was installed to the existing Codex skills
  directory with backup and byte verification by the lead.
- An actual Codex weekly review read live-format demo context and selected
  KB policies/source records, then applied seven dated slots through the helper.
  With four observed runs (about 106 minutes/14 days), recent exposures of
  21.7/32.5/40 minutes, normal reported function, and missing HR/recovery, it
  chose consolidation: five easy/endurance runs of 20/25 minutes plus two rest
  slots, with no speed increase. The API returned the seven-date diff and the
  persisted plan. Exact minutes were labeled coaching inference, not research
  thresholds. Legacy conflicting synthetic strength entries were preserved and
  surfaced as uncertainty.
- Final PostgreSQL integration suite: 31 tests passed, including stale/version
  rejection, completion protection, rollback/replan cache behavior and repeated
  decisions; backend lint/types passed. These validate mechanics rather than
  the scientific quality of a model-authored dose.
- Actual Codex daily reasoning used 42 synthetic observed dates with 35 baseline
  and seven recent observations per metric. With isolated HRV 38 ms versus a
  prior mean of 60, stable sleep 8 hours/resting HR 50, and explicit normal
  function, it saved a no-change daily review (`edcabb70…`) and retained the
  next 20-minute run. Today itself was an off-cycle mobility day, so this does
  not prove same-day run execution.
- The scenario then changed to three days of sleep 6/5.5/5 hours, HRV 42/38/34
  ms, resting HR 56/58/60 bpm plus explicitly reported fatigue with normal gait
  and no symptoms. Codex reduced only the next run from 20 to 15 easy minutes
  (`a91718bd…`), preserving the weekly strategy and 27 other accepted sessions
  byte for byte. The calendar API and fresh context showed the saved 15 minutes.
  These exact doses were labeled proportional coaching inference, not score
  thresholds or a deterministic recovery formula.
- Reapplying the identical daily JSON/key returned the same revision with
  `unchanged: true` and `replayed: true`; fresh context retained that current
  revision. No duplicate or arbitrary calendar change occurred.
- The helper linked an exact November 6 synthetic planned run to the matching
  same-date recorded activity. The next weekly context contained that link,
  latest reported fatigue, prior AI daily review and retained weekly strategy.
  This checks a historical actual/feedback loop; it does not simulate completing
  tomorrow's newly prescribed run or substitute for a future longitudinal trial.

These executed behaviors cover the targeted accumulated-recovery, isolated-HRV,
repeat-invocation, weekly/daily consistency and missing-data cases (C/D/F and
parts of G/H). Transport tests and model reasoning are distinct evidence.
Comprehensive A–H acceptance, all 15 KB scenarios and detailed FIT cases are not
claimed. The lead restored the real app at `http://127.0.0.1:8000` and passed
read-only desktop/mobile browser smoke. The installed helper's `today` command
returned real daily context with KB available, seven upcoming opportunities,
and no active agent revision. No real coaching plan or synthetic recovery
fixture was written during verification.

## Practical synthetic exercise

Use demo/test mode only, after its migrations and synthetic fixtures. The helper
refuses mode mismatches before writes. Read `review-week`, `schema`, and relevant
KB with `--mode demo --base-url http://127.0.0.1:PORT`. Have Codex author the
weekly proposal from that actual context and save its JSON in ignored private
demo storage. `apply` it and inspect calendar/revision/fresh context. Record the
actual output and rationale; do not call a generic template AI evidence.

Next, save a reported synthetic check-in, retrieve `today`, and have Codex
confirm or adjust today's existing prescription proportionally. Apply and verify
unaffected sessions and strength stay intact. Link a synthetic actual to the active
session, record subsequent feedback, and inspect the next context for the
prescription → actual → response → prior-advice sequence. Exercise repeat calls,
invalid/stale proposals, rollover and rollback on the same isolated data.

## Explicit P0 limits

Whole-run HR/pace/distance/time are usable; FIT streams/laps, time in HR zones,
interval detection and drift are not delivered by this core. Missing observations
remain unknown. Manual review is still needed for ambiguous actual matches.
No automatic new research search, full 15-case KB evaluation, training scheduler,
strength prescription engine or external model service is claimed. Further
analytics and research refinements belong to later slices after the usable
weekly/daily loop is verified.
