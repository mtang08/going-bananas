# Integration and release — MVP-1.0

Planning only until user approves finished spec and swarm plan (handover §H). No commands in this file run during planning. After approval, root owns integration and can merge complete reviewed green tasks to main under the user's standing authorization. No push authorized. Real data must be preserved; schema downgrade/drop/rebuild is not a rollback strategy.

## 1. Provision and baseline

Start from main5ebf981aa4517f4f73f3c97aa5d43232204466ce plus approved spec commit on a new integration/mvp1 branch. Preserve unrelated changes. Never reset historical integration/p0 or reuse old tags. For each task record exact prerequisite-complete SHA with gb-mvp1-task-<ID>-base[-rN], and isolated worktree as worker_instructions §2.

Provision a dedicated disposable PostgreSQL17 cluster at 55439 and explicit synthetic demo/test databases. Existing 55432 remains untouched. Generate 0600 sanitized env rather than copying real config. Owner verifies host, port, database, private path and mode before any migration/reset. Supply exclusive lease for integration commands; no worker dropdb/initdb. Do not reinitialize an existing unidentified directory. Cache reuse is allowed, data reuse is not. Browser tests serve the built frontend directly from uvicorn on18000 with APP_PORT=18000 and PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000, synthetic demo settings and a fixed clock; use smoke/verify-demo --base-url. Do not use the hard-coded8000 serve.py/Vite proxy for this isolated gate; never stop a running real service merely to claim its port.

## 2. Merge and verification

Use dependency_graph wave order and each packet ownership. Root/Astra reviews actual diff, interfaces, acceptance evidence and privacy before merging. Text conflicts or semantic failures route to owning worker/lead; routine implementation repair stays within authorized scope, contract changes require versioned amendment. No destructive shared reset or deleting worker worktrees with unpublished work. Use a revert for a bad integrated commit, retain evidence and rerun affected gates.

Every task: make check. DB-facing task: make test-integration on isolated leased DB.050 and 070: make test-e2e plus smoke scripts against staged demo. Full gate after 030,050,068,070 checks cross-task wiring. TASK 068 migration tests begin from populated 0009, not empty database only. Healthy existing API/Coach/Cycle/Settings/Strength/history remains a gate before production cutover.

Do not merge partial functionality that breaks the running app. New schema is additive; new workflow remains behind persisted authority until 068 succeeds. P0-A is a useful demonstrated vertical slice in isolated demo; production switches only when P0-B review/history/rollback is complete. Remaining packet requirements, not old test counts, determine completion.

## 3. G2 evidence gate

After 004 exists, integration owner coordinates private real inventory, using existing credential handling; never request/copy secrets into chat. Read-only observation does not require application cutover. Export redacted field names/types/counts/units, capability verification results and hashes only; keep raw training files private. Evidence set and predicates are acceptance §1.4 and TASK 004.

Data/metrics Astra leads review mapping and timer/repeat/RPE/source semantics. Record per-capability verified|unsupported|unverified plus reason. Missing representative samples remain unverified. Canonical SDK decode behavior and synthetic tests do not prove real-device population. Full P0-A real acceptance requires evidence; otherwise request explicit scope reduction. Changes to canonical mappings/heuristics require spec patch, affected task tests and re-pin; workers never choose a fallback physiology model.

## 4. Backup, migration and authority cutover

No destructive rebuild premise applies. Before any real migration or 068 activation, owner records code/schema head and redacted table-count/hash manifest, backs up database plus private raw objects with existing app.cli backup, and proves restore into a NEW isolated target through app.cli restore and scripts/verify-restore.py. Use scripts/with-mode real for backup only when authorized implementation stage reaches this gate; never print database URLs or raw records. Verify the backup includes all new/legacy models, raw files and lineage before treating it as recoverable.

Quiesce writers (app mutations, sync worker and scheduler), record prior process state, then run additive upgrade and 068 dry-run. Dry-run must enumerate no unmapped/lost IDs and preserve counts/digests/active membership/confirmed recurrence/links/history/eligible undo. Resolve every mapping failure; never skip unknown data. Apply under advisory+app_state locks in one transaction, persist mapping/import marker and authority calendar. Repeat is no-op; failure leaves authority legacy and zero partial import. Verify read-only API/UI and export/restore on resulting state before restoring writers. New legacy-mutation requests must adapt to review workflow or return explicit upgrade response; never continue invisible automatic activation.

Rollback before activation: transaction rollback. After activation: preserve failed-state backup and restore verified backup to NEW target with matching code, validate before switching app configuration. Do not overwrite failed data or downgrade Alembic. Preserve newly recorded facts; owner evaluates whether an application forward repair is preferable to restoring older data. Existing logical calendar rollback remains a new revision and protects completed/historical/locked facts.

## 5. Release evidence

Required: all relevant packet gates, P0-A/P0-B end-to-end journeys, no-model usefulness, partial approval with persisted calendar changes, no-change/reject-all semantics, stale observation and decision replay, legacy import and newest eligible undo, exported restore parity, KB integrity/privacy, explicit missing-data behavior, local origin protections, browser reload/navigation/accessibility, fixed-zone/DST fixtures. G2 state separately recorded; never label unverified evidence passed.

Retain a small release report: exact code/spec SHA, commands/exits, fixture counts, gate outcomes, G2 capability matrix, backup/restore verification (private paths only), manual coaching evaluation results, remaining limitations. Prior tests are historical evidence, not new pass claims. End-to-end real Codex coaching submission is a manual evaluation in an approved implementation phase; acceptance is still explicitly reviewed in the app.

No second blanket merge permission is needed after planning approval because user authorized complete functional tasks to main. Stop only for concrete unresolved scope/evidence or destructive recovery requiring a decision. Push/publish remains outside scope.
