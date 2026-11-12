# Live progress — finish the running-coach workflow

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

## Knowledge import checkpoint — November 11, 2026

Integrated the verified `1.1.0+privacy1` periodization extension: nine new files,
three replaced payloads, and 16 unchanged baseline payloads. All 28 manifest
checksums match. Original privacy provenance and the exact source/previous
manifests are preserved. The KB now includes optional-block, calibration,
recipe, and race-transition reference material, with 72 sources and 23 candidate
policies. The local knowledge helper can explicitly retrieve block research,
P019–P023, and selected recipe records. Daily/weekly default selection and saved
training remain unchanged; new product behavior awaits the user's implementation
plan. See [research integration](research-integration.md) for provenance and
retrieval limits.

Import verification passed 17 focused backend tests, 13 helper tests, Ruff, and
mypy for all 36 application files. Installed helper/reference files were backed
up, updated, and byte-verified. The restarted real API passed readiness and
read-only daily/weekly context checks with KB `1.1.0+privacy1` available, both
under the 70,000-character limit. Installed block/topic/P019/REC001/S057
retrieval also passed. No database or plan mutations were performed.


## Active P0 implementation — November 11, 2026

The resumed task supersedes the context-clear pause below. The latest user
instruction authorizes automatic persistence of validated AI running decisions;
older routine proposal-acceptance/no-auto-mutation requirements are retired.
The installed Codex skill is sufficient as the AI entry point. Focus on weekly
persisted 14-day plans and daily persisted confirmations/adjustments; detailed
FIT analytics and further KB refinements remain P1. See
[running-coach-workflow.md](running-coach-workflow.md) and
[p0-implementation.md](p0-implementation.md) for the revised contract and scoped
verification record.

Preserve all existing user work and private data. The lead verified the real
profile at version 4 and created the pre-agent-plan backup at
`private/real/backups/pre-agent-plans-20261111.tar.gz` (1,585 files). Skill/helper
changes pass 12 isolated synthetic transport tests and skill validation. The
lead verified 58 backend/22 frontend checks and nine synthetic browser cases;
the final database suite passed 31 integration tests. An actual Codex demo
exercise saved a concrete seven-slot weekly plan, retained it after isolated
low HRV, then shortened only the next run from 20 to 15 minutes after agreeing
three-day recovery decline and reported fatigue. Twenty-seven other accepted
sessions and weekly strategy stayed intact; identical retry replayed the same
revision. Calendar API and next review context verified persistence and an
exact historical completion/feedback link. See the P0 record for the inputs,
limitations and distinction between transport and model reasoning evidence.
No exhaustive A–H/FIT or all-15-KB-case validation is claimed. The lead restored
the real app at `http://127.0.0.1:8000` and passed read-only desktop/mobile
browser smoke. The installed helper returned real daily context with available
KB, seven opportunities and no active agent revision. No real coaching plan or
synthetic recovery fixture was written during verification.

## Earlier handoff and user assessment — November 11, 2026

**The user explicitly says the product is not usable yet.** The verified data,
schedule, and local-rule releases below are foundations, not completion of the
requested coaching product. The required next task was an integrated, useful running
recommendation workflow. The context-clear pause applied to that earlier
handoff; active work has resumed as recorded above.

Read [running-coach-workflow.md](running-coach-workflow.md) first on resume. It
defines the user journey, actual gaps, implementation order, and acceptance
criteria. It supersedes older statements that the coaching MVP is complete or
that model coaching is merely optional future work.

### Earlier handoff corrections and state

- Main's last verified release is `ac60c02` (recurrence and heuristic run labels).
  Preserve uncommitted work: `README.md`, `docs/backlog.md`,
  `scripts/test_coach_skill.py`, and `skills/going-bananas-coach/` were already
  modified/new before this handoff. Inspect Git status; do not discard or claim
  that this newer skill work has passed the earlier release checks.
- The user has now set the run anchor. A live read verified profile version 4,
  `cycle_anchor=2026-11-10`, `anchor_confirmed=true`. Older notes below saying
  the anchor is unknown are superseded. Read the current profile before edits;
  do not overwrite later user changes.
- The confirmed alternating strength/mobility pattern remains saved. Week A
  reference is Monday November 9, 2026: full-body Mon/Fri, gym mobility Wed;
  Week B: full-body Tue/Sat, gym mobility Thu. Sunday mobility is optional.
  Strength stays in Strong. Current implementation focus is running guidance,
  while respecting these commitments; a new strength prescription system is
  outside this phase.
- All 164 runs inspected had stored average HR. The classifier uses summary
  HR/pace/distance/time deterministically. The inspected coaching context had
  no top-level per-activity HR fields or dedicated HR trend summary. Intrarun
  HR series, zones, laps, interval patterns, and drift are not implemented;
  provider access to richer data has not been verified.
- `going-bananas-coach` now exists both in the uncommitted repo skill directory
  and in `/Users/mtang/.codex/skills/going-bananas-coach/`. It can read live
  context and selected KB prose, write reported check-ins, and append confirmed
  memory to profile facts. Inspect its SKILL.md and helper before extending.
  It cannot persist its running proposals as app recommendations/plans or
  link subsequent outcomes to its own advice. The app Coach tab still runs
  `local_rules.v1`; its output is separate from the skill conversation.
- Current app was left at `http://127.0.0.1:8000` (last reported server session
  81233). Verify actual readiness/current code on resume; do not assume a
  long-lived server reflects subsequent source changes.

### Standing working preferences

Use less expensive Sol implementation subagents; lead oversees and reviews
targeted blockers. Keep user-facing explanations and progress concise. Routine
development permissions were already authorized; commits directly to local main
were authorized earlier. No remote/deployment exists.

Routine sync, labels, metrics, calendar expansion, and app use must be
deterministic and require no model tokens. The intended model use is a daily
coaching invocation plus a weekly review/planning invocation covering the next
one or two weeks, using recent actual training/response and selected KB research.
Manual label overrides take precedence. Long-run proposals belong on Saturday
or Sunday; other run types are the coach's responsibility. Do not make the user
build weekly manual plans or copy conversational advice into dated sessions.

## Historical release evidence (foundation only)

Updated for the recurring schedule and historical run-label release on November 11, 2026. The prior in-progress checkpoint
has been consolidated into [handoff.md](handoff.md), [release-checklist.md](release-checklist.md),
and [research-integration.md](research-integration.md). Preserve the current
local real database and ignored private files. No remote or deployment exists.

## Delivered

- Reviewed research library with selective hash-checked loading. Original
  research, manifest, and dated athlete context stay under ignored
  `private/real/research-imports/`.
- Separate Strong CSV source, historical drilldown, source-faithful sets, and
  the preceding 18-calendar-month running context. Real import: 512 workouts,
  8,168 sets, 118 unknown normalized durations. No guessed weight unit or
  dumbbell conversion.
- Coach Today/Tomorrow/Weekly views with explicit generation, provisional
  alternatives, uncertainty/references, saved-input visibility, stale advice,
  accept/decline/completion feedback, and append-only outcome events. Runtime
  is a bounded local evidence-guided rule flow; no external model or automatic
  plan mutation.
- Migrations through `0008_strength_schedule` in test/demo/real. The real
  versioned profile contains the confirmed Week A/B full-body strength and
  mobility pattern; the unknown run anchor is preserved. Historical run labels
  use deterministic, past-only relative heuristics with manual override. All
  local release checks and isolated backup restore passed. The real app is available
  at `http://127.0.0.1:8000` after final production restart.

## Verified evidence

`make check`: 58 backend tests, 17 frontend component tests, lint, types and
build pass. `make test-integration`: 24 PostgreSQL tests pass. Eight demo browser
cases and read-only real desktop/mobile browser smoke pass. Eighteen real API
GETs and foreign-origin mutation rejection pass. Strong source rows/sets/duration
and preserved CSV bytes match; the 18-month cutoff yields 143 sessions.
Pre-change isolated restore row digests prove two profiles, 179 Garmin activities,
1,282 recovery observations, and empty check-in/plan/manual tables unchanged.
Post-configuration isolated restore matches 11 table counts, full profile and
new-table row content, 1,577 raw checksums, and six private research originals. See the release
checklist for scope and limitations.

## Prior release scope and remaining work

The prior release verified local-rule cards and recurring calendar projections.
It did not deliver the full research-coach workflow. The run anchor is now
confirmed as recorded above. The 15 supplied
behavioral examples have not all been executed end to end. Exact personalized
progression, delayed multi-day response analysis, and full event chronology in
weekly review remain gaps. The active next phase is in
[running-coach-workflow.md](running-coach-workflow.md), with other ideas retained
in [backlog.md](backlog.md).
