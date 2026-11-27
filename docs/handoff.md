# Historical handoff — persisted running-coach workflow

This handoff records checkpoints from the earlier Python runtime. For the
current Go application, see [Architecture](architecture.md) and
[Local operations](operations.md).

## AC-1 checkpoint — adaptive coaching and lean UI

The loop: the Sunday weekly review rolls 14 days (days 1–7 committed, days 8–14 provisional). Between Sundays, the exception detector raises findings, and caution or hold findings lead to an exception review that patches only the committed week. Each block ends with a benchmark that drives the block review, which also handles findings that need a bigger review. Other races get a post-race review. The legacy coach (`local_rules.v1`), daily guidance (`local_rules.v2`), legacy agent plans, the `skills/` package, `make context`, and the History, Strength, and Coaching history pages are removed; their tables remain. Older sections are historical context.

Final cleanup verification (Gate E) passed on application source
`f7aec5b15638ebb2ad52be37354d8d6b9822d53b`, reviewed against pre-cleanup
`8a2e13fdaa1bedf7a2e684cf623a44871de5be0f`. `make RUN=env check` passed
497 backend and 203 frontend tests plus lint, types, and build;
`make RUN=env test-integration` passed 162 PostgreSQL tests; the helper suite
passed 18 tests. A fresh guarded synthetic demo was migrated and seeded directly
with `seed-demo --calendar-preview`, then rebuilt: all 20 Google Chrome cases
and `scripts/verify-demo.py --base-url http://127.0.0.1:18000` passed. Every
acceptance command exited 0. The only gate changes correct the guide's benchmark
card title, repair the current skill-reference link, and record this evidence;
the three guide tests and six-document local-link check also passed. Validator
goldens are unchanged, active-block selection is shared, and all eight formatted
API/type files match exact Prettier output with equivalent TypeScript ASTs.
No real data or configuration was read or changed. Nonfatal KB-budget and build
chunk-size warnings remain. O2 and O3 below remain deferred product follow-ups.

Earlier AC-21f acceptance passed on candidate `9e69ef7e152c15633b33538ad7f0d23a49db8446`:
`make check` passed 491 backend and 203 frontend tests plus lint, types, and build;
`make test-integration` passed 153 tests; the coach-helper suite passed 18 tests.
All 20 Google Chrome acceptance cases passed (p0a: 8, p0b: 8, p1-exceptions: 4),
followed by `scripts/verify-demo.py`. The required documentation scan found no
obsolete navigation or daily-guidance terms in README, the user guide, or the API
runtime guide. All verification commands exited 0. The fresh synthetic demo used
the guarded calendar-preview initializer without planning cutover; no real data
was read or changed. Browser logs still include nonfatal KB-budget warnings.
This evidence-only handoff update leaves the tested application and suites unchanged.
Next: O2 and O3 in [backlog](backlog.md).

## Agent-plan completion checkpoint — November 11, 2026

The persisted weekly/daily running-coach workflow is complete for the documented
P0 scope. Weekly prescriptions, daily confirmations or adjustments, immutable
revision history, protected completion links, and version-checked rollback are
wired through the helper, API, and calendar. This work does not add FIT metrics,
blocks, intensity anchors, or an autonomous coaching scheduler.

Final verification on synthetic data: 68 backend tests, 26 frontend tests,
49 PostgreSQL integration tests, 13 helper tests, and nine browser acceptance
cases passed. Lint, type checking, and production build passed. Browser tests
ran against a separate demo app on port 8019 using `PLAYWRIGHT_BASE_URL`; the
real database was not migrated or seeded. The local API was started with its
existing real-mode configuration after port 8000 was found unavailable;
readiness and read-only desktop/mobile navigation passed. Only the API was
started; verification did not launch an automatic sync worker.

Completion fixes reject malformed evidence reference lists with 422, require an
upcoming accepted running plan for daily confirmation, retain the revision
reviewed when opening Undo, and omit workout-completion controls for rest slots.
The load-test failure was a DST-sensitive fixture issue: prior runs are now
seeded at local noon on their intended dates. Existing load bounds are unchanged;
regressions cover equality, per-session excess, and aggregate excess.

The actual helper also passed a demo API check: a no-change daily decision
persisted, the calendar stayed identical, and retrying the same JSON/key
returned the same revision. The behavior-preserving frontend split now lives
on main too: current recurrence controls, saved prescriptions, rest handling,
and revision history were preserved, with two additional shared-Modal tests.

The current user-facing contract is [running-coach-workflow.md](running-coach-workflow.md).
The v0.9 redesign remains a separate, partially supplied specification; its
missing task packets and Garmin inventory gates have not been implemented here.

## Historical foundation handoff

The following is retained as prior release history; its older implementation
status and schema statements do not override the completion checkpoint above.

# Current handoff — Strong and local coaching MVP

> **Superseded product status, November 11, 2026:** the user says the app is not
> usable as a running coach yet. Start with [live-progress.md](archive/live-progress.md)
> and [running-coach-workflow.md](running-coach-workflow.md). The release below
> verified foundations, not the complete coaching workflow. The run anchor is
> now confirmed (`2026-11-10`, live profile version 4 when inspected); an initial
> installed Codex skill also exists, but its advice still cannot become app
> proposals/plans through an integrated flow. Preserve newer uncommitted work.

Updated November 11, 2026. The local release is implemented
and verified; see [release checklist](release-checklist.md) for executed evidence
and [README](../README.md) for tomorrow's user flow. No remote or deployment is
configured.

## State

- React/TypeScript/Vite frontend, FastAPI/Python 3.12, PostgreSQL 17. Local
  real app runs on 127.0.0.1:8000. Test/demo/real databases and private roots
  are separate. Migrations are at `0008_strength_schedule`.
- Garmin API plus inspected account export currently provide 180 activities
  (164 runs) and 1,282 recovery observations. The additional run arrived through
  normal scheduled sync after the previous release. Export coverage is partial;
  unsupported fields remain raw. The earlier source baseline comparison is
  recorded in the prior release checklist; this release intentionally adds a
  profile version.
- The inspected Strong CSV is imported: 512 workouts, 8,168 sets, 118 unknown
  normalized durations. Original bytes/source rows are preserved privately.
  Historical sets remain exact. Source timezone, weight unit, and dumbbell
  convention transition are unknown. The past 18 calendar months only enter
  running context; older workouts remain browsable. Same-day cross-source
  candidates are withheld from combined counts pending review.
- The reviewed research corpus is tracked under `running_coach_kb/`; private
  originals and dated athlete context stay under `private/real/research-imports/`.
  Loader checks hashes and selects guide → workflow → topic prose/policies.
- Coach explicitly generates daily or weekly local evidence-guided options,
  stores input snapshots and source references, marks stale advice, and records
  append-only outcome events. No external model call or plan mutation. The
  flow has conservative branches and known depth gaps; read the release
  checklist and `research-integration.md` before extending its claims.
- The real profile now holds the user-confirmed alternating pattern, saved as
  version 3: Week A reference Monday November 9, full-body strength Mon/Fri,
  required gym mobility Wed; Week B full-body strength Tue/Sat, required gym
  mobility Thu; optional Sunday mobility in both weeks. New projections begin
  at profile effective date, with no retrospective completion debt. Explicit
  accepted dated plans override recurrence where covered. The run-cycle anchor
  remains unconfirmed; its previous value was preserved. No symptom check-in,
  manual plan, or outcome was fabricated.
- Historical run labels come from deterministic 12-week relative heuristics
  when enough prior data exist; manual/source labels take precedence. Current
  aggregate: 51 easy, 12 quality, 30 weekend-long suggestions, 71 unknown
  among 164 runs. This uses no per-activity model tokens and no HR zones or
  intrarun drift/interval claims.

## Verification and operations

`make check` passes 58 backend and 17 frontend tests, lint, types, and build.
`make test-integration` passes 24 PostgreSQL tests; eight demo browser tests
pass. The production real app passed read-only API checks and desktop/mobile
browser smoke. A post-configuration backup was restored to a new isolated
target; eleven table counts, full profile/new-table row content, 1,577 raw
checksums, and six research original files match. A pre-configuration backup
was saved before the real profile update. Earlier isolated comparison proved
original user/Garmin rows unchanged before this new version was added. Backups and
screenshots are ignored/private. Local daily Garmin sync remains at 08:30.

Run `make doctor`, `make db-start`, `make migrate`, `make build`, `make start`
from repo root to restart. `make start` uses the protected `.env`. Do not print
keys, import synthetic demo state into real, or overwrite an existing restore
DB. See [operations](operations.md) for mode/restore details.

## Next work

Exercise all 15 supplied behavioral cases through runtime, improve delayed
symptom and previous-period metrics, and calibrate progression only with current user responses and confirmed
scheduling. Future daily skill invocation and weekly recap/planning are design
work; the active Coach remains a local rule flow. Keep Strong as the workout workflow, every-other-day running intent, and meaningful
twice-weekly full-body strength. No invented lifting equivalence or calorie
logging target. See [backlog](backlog.md).
