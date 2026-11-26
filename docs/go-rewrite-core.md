# Workstream 1 · Application, training data and integration

**Owner:** the original Go rewrite session. **Branch:** `go/core`. The proposal-list demo and test backend, generators and lint checks are in `main` as of `dc15070`. The app and worker in real mode still run Python. [Implementation evidence](go-rewrite-readiness.md) · [Shared specification](go-backend-rewrite.md)

## Implemented in demo and test

The goal metadata edit is the first Go write. Settings sends `PATCH /api/v1/goals/{goal_id}` through a generated TypeScript contract. Go acquires the same PostgreSQL advisory lock as Python, checks the expected version, updates the goal and increments the data revision in one transaction. The calendar head and stored training metrics stay intact. Competing edits, an injected revision failure and HTTP comparisons against independent migrated schemas cover that behavior. [Transaction](../backend-go/internal/goals/store.go) · [Differential checks](../scripts/rewrite/compare_goals.py)

## Next assignment

Port manual calendar completion. Return the actual affected days and links from the command, then rematch and refresh within the same transaction. Prove retry, protected history, undo, savepoint rollback and whole-command rollback. Record the affected metric results alongside the existing completion benchmark. Publish the concrete transaction-bound query and refresh interfaces after these two commands exercise them. Streams 2 and 3 can build and merge their pure packages while this work proceeds. [Calendar](../backend/app/services/calendar.py) · [Completion benchmark](../backend/tests/integration/test_manual_completion_refresh.py)

## Remaining ownership

- Port profile, calendar, blocks, anchors, scheduled sessions, activity reads, manual completion, running interruptions, check-ins, the phone gateway, prompts, exception detection, metrics and weekly views. Preserve metric identities, civil dates, explicit zeros and existing phone receipts. Prove a complete synthetic training week, including a missed run, strength, recovery, DST and a replayed phone submission. [Calendar scenarios](../backend/tests/integration/test_calendar_api.py) · [Weekly digest](../backend/tests/integration/test_weekly_digest_api.py) · [Phone scenarios](../backend/tests/integration/test_phone_checkins.py)
- Own shared Go command/HTTP registration, SQL schema capture and migrations, generated-file wiring, Make targets, Vite routing and shared UI changes. Publish reviewed interfaces when another stream needs to join. Assess differences against an upgraded historical database, a fresh install and a restored backup with rows, raw files and sequences intact. [Schema upgrades](../backend/tests/integration/test_schema_upgrade.py) · [Restore verifier](../scripts/verify-restore.py)
- Integrate provider jobs from stream 2 and proposal decisions from stream 3. One coordinator owns the source write, revision advance, rematch, projection refresh and commit. Verify competing writers, job restart and a lost decision response. Rehearse backup, restore, phone replay, app startup, worker/CLI and macOS launcher before scheduling any real cutover with the owner. [Shared data handoff and rollback criteria](go-backend-rewrite.md#data-handoff-and-rollback)

**Outstanding pilot check.** Run `make test-proposal-go` with a native browser on a host that permits browser launch. The live APIs, three Home states and the Settings goal edit passed through Vite and jsdom. This check can run alongside all three workstreams.
