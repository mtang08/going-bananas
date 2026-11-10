# Current handoff

Updated 2026-11-10. The local analytics MVP is implemented. Use README.md for
operation and `release-checklist.md` for executed evidence and limitations.
No remote repository or deployment has been created.

## State

- React/TypeScript/Vite frontend; Python/FastAPI; PostgreSQL only.
- Real Garmin Personal API activity/sleep/HRV/resting HR ingestion is configured
  privately. Initial 28-date import and repeated import verified. No secrets in
  source or frontend; raw files remain private and immutable.
- Overview/history/recovery charts, quick editable check-ins, temporal symptom
  associations, manual sessions, cycle drafts/acceptance/completion, conflict
  review, manual sync, and factual weekly summaries are implemented.
- Real calendar anchor and alternate strength mapping are unconfirmed. Keep
  real dates unscheduled until confirmed; never import synthetic profile setup.
- Lifting is tracked in Strong (confirmed 2026-11-10). Future separate CSV source,
  no parser/export now. All strength totals represent recorded sessions with
  incomplete history; absence does not mean missed lifting.
- Context export is local, versioned, and privacy-filtered. No runtime agent,
  research-derived prescriptions, readiness rule engine, or model calls.
- Demo/test/real databases and private directories are separated. E2E mutates
  demo only; integration tests require `_test` database targets.
- Sync has persistent checkpoints, independent dataset state, bounded retries,
  dedicated-connection locking, startup catch-up, and a local daily 08:30 schedule.
- Backup/restore verified into a new target. Latest local private release backup
  is under `private/real/backups/`; do not commit or print its contents.

## Verification

16 domain/config/ingestion tests, 12 PostgreSQL integration tests, 4 frontend
component tests, and 3 Chrome E2E tests pass. Lint, type checks, production build,
clean migrations, source comparisons, read-only real browser smoke, and backup
checks passed. A separate Sol-medium review led to corrections before release.
Check the release checklist rather than inferring all planned V cases were run.

One Garmin sleep record lacks an owner ID and is retained/reported partial.
Do not hide that status or replace missing values with zeros. Provider history
limits, rate quotas, pricing, and exact date boundary semantics remain qualified
in the capability inventory. Future source parser work requires actual samples.

## Next phase

The user will inspect the MVP. Address observed issues without expanding into
coaching. Later integrate `running_coach_kb/` by guide → relevant workflow →
relevant topic sections/policies. Preserve research prose, applicability,
uncertainty, and source context separately from dated profile and live data.
Use the KB's evaluation cases before activating substantive recommendations.
Keep meaningful twice-weekly strength alongside running, without invented lifting
or calorie targets. See `backlog.md` for deferred sources and product work.

## Collaboration

The user authorized Sol medium subagents, parallel implementation with coordinated
interfaces, sparse independent reviews, and direct commits to main. No additional
athlete input is needed for reversible development. Never request or print key
contents. Do not alter their Strong workflow or silently fill scheduling unknowns.
