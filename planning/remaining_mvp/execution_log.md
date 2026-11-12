# MVP execution record — 2026-11-12

Current status: MVP implemented and released locally. All TASK003–070 dependency
work is integrated on main. Actual calendar cutover, matching helper install,
source preservation, pre/post restore checks and desktop/mobile smoke passed.
See docs/release-checklist.md for final evidence and implementation_overrides.md
for approved scope changes. No outstanding product decision; broad device
semantics and old undo adaptation are explicitly bounded follow-up work.
Unrelated docs/backlog.md and docs/research-integration.md remain untouched.

The entries below are historical checkpoints.

User signed off MVP-1.0; only highest-impact decisions require a question. Approved spec commit c5dfb0a. Main production application remains unchanged; unrelated docs/backlog.md and docs/research-integration.md are preserved.

Integration checkout: private/implementation-worktrees/mvp1, branch integration/mvp1. TASK003 checkout task-003, branch task/003, base gb-mvp1-task-003-base. TASK004 checkout task-004, branch task/004, base gb-mvp1-task-004-base. Both task bases currently c5dfb0a.

Dedicated synthetic cluster55439 verified. Existing synthetic garmin_test/garmin_demo retained as gb_pre_mvp1_test/gb_pre_mvp1_demo; fresh databases created plus mvp1_migration_test. Worker role is non-superuser, cannot create databases/roles, owns only fresh synthetic databases. Worker environments generated0600 without production credentials. Test/migration DB lease exclusively TASK003; TASK004 will use pure fixtures. Main cluster55432/runtime8000 untouched.

Root baseline make setup/check passed:68 backend fast,26 frontend, lint/typecheck/build. Historical release counts are not reused as new test claims.

Active: Astra mvp_data_lead supervises Sol low schema/migration worker and separate disjoint migration-test worker for003.004 is prepared; exactpacket only depends002 and is file-disjoint from003, so manager permits overlap when a slot frees (merge003 before004). Four-slot budget respected.

Next: finish/review003 preservation and full baseline integration; merge green task branch into integration/mvp1;004 decoder/inventory; then dependency waves. No real migration/cutover, installed helper change or push yet. A schema task must not be merged to running main without compatible database readiness or explicit staging; preserve app functionality.

User steering: backward compatibility and temporary-breakage constraints relaxed. implementation_overrides.md controls current priorities. Finish working end-to-end training workflow first, no unnecessary legacy rollout scaffolding. Preserve actual data; root owns backup/migration.

TASK003 complete: task commit423bf927c3aed4121c7f1bad2882ce80e59cf4b9; merged integration/main aad86dc. Gates71backend fast/52integration/26frontend pluslint/types/build, threefocusedmodel andthreemigrationtests. Root applied sixadditive migrations to real database after privatebackup pre-mvp1-foundation-20261112.tar.gz and verified separate restore garmin_mvp1_restore_test/private/mvp1-restore. All27tables matched preupgrade; all26legacydata tables matched postupgrade (versiontable intentionally advanced).1579rawreferences and8researchoriginals verified. APIreadiness+fullreadonlysmoke passed. Existinglaunchdschedule paused/restored; APIrestarted without extra syncworker (session80895).

Active004pure FIT decoder;011sharedmetric/anchors foundation ataad86dc with exclusive syntheticDBlease. Userpriorities still quickestusabletrainingflow andbatchonlyhighimpactdecisions. No unresolved userdecision currently.

TASK004 initial1bc6287 + real-file fixf1825da completed and integrated. Realprobe exposed numeric unknownSDKfield keys; syntheticregression added, privateprobe and seven-sample inventory then decoded successfully. G2evidence remains private underreal/g2; broader end-to-end mapping/recovery validation pending. TASK011 f8ac0ad completed(9pure/4integration) andTASK014 f670b7c completed(3pure/3integration). Combinedmain/integration2d62f24 passes93backend/26frontend pluslint/types/build. Newanchors/planningrouters notyetmounted (calendar/integration pending).

Active TASK012 base98966aa andTASK010 base2d62f24 under Astra mvp_data_lead withtwoSolLOWworkers. Lead serializes syntheticDBlease. Syntheticcredentialrotated aftertesttraceback, alltaskenvs updated; notrainingcredentials involved. Highest-impact userdecision queue remains empty.

TASK010 4fc6653 and TASK012 9417f7b reviewed and merged (integration9bc9bcd). FIT ingestion preserves last-good data on retry failure, manual RPE, account scope and timer provenance. Calendar has versioned bootstrap/edit/rollback, completion protection, strict structure and stale-head checks. Their focused synthetic tests and make check passed. TASK060 root implementation reviewed independently by Astra: exact saved research selection/digest, whole-package integrity, privacy and bounds; 48 focused tests and make check145backend/26frontend passed. Deferred legacy agent-plan integration check will run on shared DB after013 lease.

Active013 exception check-ins/daily guidance and039 static frontend contract under Astra; root021 intensity metrics. User decision queue empty. Latest priorities permit static contract tasks before eventual runtime wiring, retaining contract reconciliation and full release checks. Production authority remains legacy; no generated training proposal accepted on user's behalf.

Further completed and reviewed: TASK013 1b54cf7 plus51db2e4 (5 integration tests after bounded answered-RPE prompt flow fix); TASK039 3fd7779 frontend types; TASK021 544afa6 intensity (31 focused, combined177backend37frontend); TASK024 2261aa8 recovery (31 focused incl immutable loader partition mapping, combined215backend37frontend before added focused regression); TASK022 8895febe interval execution; TASK023 ce14d0e effort load/symptoms; TASK020 626c477 volume/long exposure; TASK040 90fe952 Home (10 focused,185backend47frontend); TASK041 7826202 Calendar (19 focused plus static checks; priorfull216backend55frontend); TASK045 27550c3 check-in UI (11 focused,244backend58frontend). All integrated by e33f9a9. Shared011 follow-up bfc5faec ignores finite zero-length timer intervals and isolates registry tests. TASK060 deferred legacy agent-plan DB integration check passed25. No active synthetic DB lease.

G2 read-only additional evidence: private/real/g2/source-semantics-20261112.json paired latest and pause-heavy activity summaries with FIT: both flat duration timer matches and both detail directWorkoutRpe/10 matches passed. Sleep/HRV/RHR shapes fetched with no errors. Non-worn-night evidence remains explicitly unverified; repeat/lap capability review remains pending. API duration fallback remains disabled; FIT-first is working. No real DB records changed by probes.

Current active: Astra lead oversees025 matching/planned-actual and042 activity page; root044 PlanningSettings at e33f9a9 uncommitted with12focused tests+TS/lint passed, fullgate ongoing. Root owns user coordination/integration; no unresolved user decision. Remaining026/030 full metrics integration,043 trends,050 app shell/demo,061–066 Codex proposal/review path,068 real authority import,070 release. Existing Settings is composed inside PlanningSettings;050 must not duplicate its old panels. Reconciled actual interfaces: GoalCreate omitsstatus(active default); AnchorCreate includes valid_from; completion reason writes omit server-derived status. 025 worker base e33f9a9;042 base0f614dd. Do not reset/drop real data. Main still d5e8c80 pending next reviewed batch; real API remains legacy authority and schema0015.

TASK042 86470e7 Activity, TASK043 df625e7 Trends, TASK044 eac0497 PlanningSettings, TASK025 c3f75e7 matching/planned-actual, TASK026 6f01d96 prompts, and source-writer lock follow-up015 97d21ab are complete and merged. TASK030 e380322 reviewed by Astra and merged main/integration a6127c4: atomic metrics refresh and provenance history, savepoint-safe coalesced source revisions, metrics/execution routes, source-write serialization, operational CLI. Final gates91DB integration/283backend fast/108frontend plus Ruff/mypy/lint/types/build; new13 integration tests include two-connection writers, rollback, corrections, immutable explanations and CLI. Earlier service-seam fixtures explicitly suppress automatic refresh while testing injected matching/assessors; new integration tests retain actual listeners. Actual DB authority remains legacy pending068; no athlete coaching changes accepted by manager.

Active061 proposal collection/validation/acceptance and050 shell/demo under Astra lead; root proceeds063/064 API/CLI integration. Lead owns synthetic DB lease scheduling. After050 worker proceeds068 cutover; after061 worker proceeds062 snapshots, then066 review UI. Latest user priorities waive elaborate old undo/helper compatibility rollout; preserve every real source/history row, current cross-plan membership and links, immutable new review lineage, manual acceptance, atomic authority and backup. No unresolved user decision. Source notes projection remains a small frontend integration follow-up. G2 real non-worn-night/repeat mapping evidence remains explicitly incomplete.


Final integration: 050 shell/demo, 060–066 verified research/snapshots/CLI/manual
proposal review, and 068 populated cutover completed under Astra review with
Sol implementers. Root070 integrated routes, archived read-only coaching,
Activity notes, documentation, helper staging and actual release. Final full
gates:322 backend fast /133 PostgreSQL integration /132 frontend /16 browser
cases, plus23 helper contracts and static/build checks. The source-provenance
compactness fix32fd023 preserves full stored evidence and canonical freshness;
37 focused plus9 CLI integration checks passed. Real daily/rolling snapshots
are now approximately12k/27k tokens, versus396k/411k before the fix.

Real authority is calendar, head1, no fabricated proposal/plan. API8000, one
worker and daily launchd schedule resumed. Both pre/post cutover backups restore
all56 tables exactly;1655 archived files verified. Full source preservation
covers17 named tables. FIT backfill49/49 succeeded; remaining device caveats are
reported without claiming synthetic coverage proves them. No remote push.
