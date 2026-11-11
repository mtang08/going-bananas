# Live progress — Strong and local coaching MVP

Completed November 10, 2026 (November 11 UTC). The prior in-progress checkpoint
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
- Migrations through `0007_coaching_selection` in test/demo/real. All local
  release checks and isolated backup restore passed. The real app is available
  at `http://127.0.0.1:8000` after final production restart.

## Verified evidence

`make check`: 45 backend tests, 15 frontend component tests, lint, types and
build pass. `make test-integration`: 22 PostgreSQL tests pass. Six demo browser
cases and read-only real desktop/mobile browser smoke pass. Eighteen real API
GETs and foreign-origin mutation rejection pass. Strong source rows/sets/duration
and preserved CSV bytes match; the 18-month cutoff yields 143 sessions.
Pre-change isolated restore row digests prove two profiles, 179 Garmin activities,
1,282 recovery observations, and empty check-in/plan/manual tables unchanged.
Post-change isolated restore matches 11 table counts, full new-table row content,
1,573 raw checksums, and six private research originals. See the release
checklist for scope and limitations.

## User flow and remaining work

Record a current check-in, confirm the run-cycle anchor and strength placement
if known, generate tomorrow's guidance, review its uncertainty and alternative,
and record the response afterward. Unknown real scheduling and symptoms are
honest user inputs; they do not block provisional options. The 15 supplied
behavioral examples have not all been executed end to end. Exact personalized
progression, delayed multi-day response analysis, and full event chronology in
weekly review remain follow-ups in [backlog.md](backlog.md).
