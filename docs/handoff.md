# Current handoff — Strong and local coaching MVP

Updated November 10, 2026 (November 11 UTC). The local release is implemented
and verified; see [release checklist](release-checklist.md) for executed evidence
and [README](../README.md) for tomorrow's user flow. No remote or deployment is
configured.

## State

- React/TypeScript/Vite frontend, FastAPI/Python 3.12, PostgreSQL 17. Local
  real app runs on 127.0.0.1:8000. Test/demo/real databases and private roots
  are separate. Migrations are at `0007_coaching_selection`.
- Garmin API plus inspected account export provide 179 activities (163 runs)
  and 1,282 recovery observations. Export coverage is partial; unsupported
  fields remain raw. Existing profile/Garmin/user rows matched the pre-change
  backup exactly after this extension.
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
- The real run-cycle anchor and alternate strength mapping are unconfirmed.
  No symptom check-in, plan, or outcome was fabricated in real data. The user
  can check in, confirm schedule when known, generate tomorrow's option, and
  record their response.

## Verification and operations

`make check`, `make test-integration`, and six demo browser tests pass. The
production real app passed 18 read-only API GETs, foreign-origin rejection,
and desktop/mobile Coach/Strength browser smoke. A post-change backup was
restored to a new isolated target; eleven table counts, new table row content,
raw checksums, and research original files match. The previous backup was
restored separately to prove old user/Garmin rows unchanged. Backups and
screenshots are ignored/private. Local daily Garmin sync remains at 08:30.

Run `make doctor`, `make db-start`, `make migrate`, `make build`, `make start`
from repo root to restart. `make start` uses the protected `.env`. Do not print
keys, import synthetic demo state into real, or overwrite an existing restore
DB. See [operations](operations.md) for mode/restore details.

## Next work

Exercise all 15 supplied behavioral cases through runtime, improve delayed
symptom and previous-period metrics, and calibrate progression/strength
placement only with current user responses and confirmed scheduling. Keep
Strong as the workout workflow, every-other-day running intent, and meaningful
twice-weekly full-body strength. No invented lifting equivalence or calorie
logging target. See [backlog](backlog.md).
