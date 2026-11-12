# TASK-070 — Integrate and verify the reviewed Codex coaching experience

Baseline: main `5ebf981aa4517f4f73f3c97aa5d43232204466ce` plus all dependencies.
Spec: planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag.
Wave / priority: P0-B; wave 13 (dependency_graph.md).
Dependencies: TASK-068; all earlier DAG dependencies remain required.
File ownership: `frontend/src/App.tsx` (route integration only), `frontend/tests/app.test.tsx`, `e2e/p0b.spec.ts`, `scripts/smoke.py` (additive v2 checks), `README.md`, `docs/operations.md`, `docs/api-runtime.md`.
Forbidden changes: migrations, authority/cutover service, installed skill, metrics, proposal transaction logic, legacy page deletion. No live data access except separately approved release acceptance.

## Objective and observable end state
After successful068 cutover, user can run the Codex skill, inspect a pending changeset, reject one item, accept the others, inspect lineage and request protected undo. Stale sources and invalid subsets cannot apply. Legacy history remains inspectable. App still never calls a model.

## Inputs and fixed contracts
066 component exports and exact labels;068 planning_authority/cutover result; acceptance.md P0-B binding test names; coaching_contract§5;065 install manifest. Route `#proposal/<uuid>` -> ProposalReview; `#block` -> Block. Invalid URI/hash safely falls back to authority default.

## Implementation procedure
1. Add block/proposal routes to050 authority-aware parseHash. Calendar authority nav includes Home, Calendar, Trends, Block, History, Strength, Data & settings and legacy coaching history link. Legacy authority keeps current Coach/Cycle and old modal. Import new components without deleting old pages. On authority transition invalidate all old/v2 caches and refetch before mounting active planning views.
2. Add e2e/p0b.spec.ts with acceptance binding names plus source freshness/replay/undo assertions. Isolated demo/test fixtures only; obtain today/head dynamically. CLI uses execFileSync argument arrays with explicit demo mode; proposal files remain private/demo/coach/proposals. Do not shell-interpolate user text.
3. Weekly: snapshot->submit pending; calendar unchanged; review c1/c2/c3, accept c1/c3; assert resulting state and immutable acceptance history. Daily proposal outside today..today+3 invalid. Stale manual edit and fresh symptom without head change both block acceptance. Empty and reject-all decisions create no calendar version. Identical decision retry returns same version. Invalid subset has no writes. KB unavailable produces defined failure without affecting dashboard.
4. Undo latest eligible change; assert future eligible sessions restored, locked/completed/history untouched; preceding no-change review does not hide undo. Verify imported pre-cutover eligible undo through068 adapter. Next snapshot includes prior proposal, accepted/rejected items, actual sessions and later symptoms.
5. Regression suite: existing history/Strength/sync/settings/legacy coach reads still work; old automatic mutation route cannot apply after cutover; old helper receives upgrade guidance. Verify mode badges, mobile navigation and local-only requests. No deleting tests to obtain green status.
6. Update operational docs with source skill location,068 explicit install/update procedure, manual review path, stale/retry handling, protected undo, immutable legacy reads, backup/restore and authority recovery. Remove documentation that promises automatic activation after cutover; retain pre-cutover behavior description. Explain G2 synthetic-vs-device gate accurately.

## Tests and expected results
`make check`; `make test-e2e` in disposable demo/test; existing/new helper unit suites; acceptance.md populated-cutover/export-restore suite. No live Garmin sync or database reset. Reports distinguish synthetic pass from pending G2; real P0-A acceptance cannot be declared until G2 evidence is approved.

## Acceptance checklist
- [ ] Every new changeset needs explicit user decision; no automatic bypass.
- [ ] Current data/history/recurrence survives068, latest eligible undo preserved.
- [ ] Source changes, retries, partial acceptance and protected undo covered.
- [ ] Codex installed entry point matches reviewed repo source; platform-neutral backend.
- [ ] G2 remains explicit until actual device evidence passes.

## Completion report
Changed files; test outputs; acceptance matrix with synthetic/device separation; cutover and installed-skill provenance; remaining gates. No secrets or raw athlete data.

## Escalation rule
Any authority, data-preservation or device-evidence mismatch blocks release. Return failing invariant; do not reset data, disable checks or substitute synthetic evidence.

## Isolated browser runtime (binding)
Synthetic gates use the manager-owned isolated demo environment/database. Run `make check` to build frontend, then serve that built frontend directly with `APP_PORT=18000 ./scripts/with-mode demo bash -c 'cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 18000'`. Run browser tests with `PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000`; no Vite dev proxy and no scripts/serve.py. Existing real app on8000 is untouched. Smoke uses `python3 scripts/smoke.py --mode demo --base-url http://127.0.0.1:18000`; synthetic verify-demo uses the same base URL. browser-smoke.mjs remains real read-only release verification at8000, never part of this synthetic gate.
