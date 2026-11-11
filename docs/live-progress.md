# Live progress — Strong and local coaching MVP

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

## User flow and remaining work

Record a current check-in, review the saved strength rotation, confirm the
run-cycle anchor if known, generate tomorrow's guidance, review its uncertainty and alternative,
and record the response afterward. The unknown run anchor and current symptoms are
honest user inputs; they do not block provisional options. The 15 supplied
behavioral examples have not all been executed end to end. Exact personalized
progression, delayed multi-day response analysis, and full event chronology in
weekly review remain follow-ups in [backlog.md](backlog.md).
