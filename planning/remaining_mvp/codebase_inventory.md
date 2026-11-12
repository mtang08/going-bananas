# Current code inventory — MVP-1.0

Baseline main `5ebf981aa4517f4f73f3c97aa5d43232204466ce`, four commits ahead of origin at planning start. Unrelated dirty `docs/backlog.md`, `docs/research-integration.md` are outside this work. Evidence: static current-source audits in `reviews/`; earlier verified runtime results recorded in progress.md. No new runtime verification performed during planning.

| Area | Current state | Remaining work |
| --- | --- | --- |
| Stack | FastAPI/SQLAlchemy/Alembic/PostgreSQL17; React/Vite/TanStack; loopback protections | Extend existing stack |
| Schema | Existing migration head0009_agent_plan;0008_strength_schedule already exists | Add0010–0015, preserve old rows;003/068 |
| Frontend | App shell, pages and components extracted (TASK 001 complete) | Add new views with authority staging;039–050/066 |
| FIT dependency | garmin-fit-sdk21.221.0 locked (TASK 002 complete) | Decoder/inventory/ingestion;004/010 |
| Timezone/test infrastructure | services/timezone.py; integration markers; Makefile separation | Reuse, fix remaining import/sync callers;010 |
| Garmin summaries/recovery | personal.py, normalize.py, services/sync.py; provenance and coverage tracking; API duration intentionally not timer | FIT canonical durations and G2 field evidence |
| Strong/manual sessions | CSV import, history UI, manual sessions | Preserve; connect matching/spacing and confirmed routine |
| Existing plan workflow | api/agent.py, services/agent_plans.py, agent_models.py; weekly/daily persisted reviews, immutable revisions, rollback, selected evidence | Manual proposal workflow with no guard regression |
| Calendar membership | plan_data reads revision payload.active_session_ids, which can include sessions from older plan IDs |068 must import logical membership, never only latest plan_id |
| Concurrency | advisory lock71382413, app_state row lock, expected revision/source hash, idempotency | Preserve across submit/accept/cutover |
| Existing history/undo | Before/after snapshots; latest changed revision undo, protected completed/historical/locked sessions | Immutable archives plus equivalent eligible undo |
| Strength schedule | Confirmed weekly or alternating recurrence, strength/mobility | Preserve through bootstrap and import; no fixed defaults over confirmed choices |
| Legacy consumers | agent_plans imports core.get_context; summary/load_knowledge used by current coach | Keep interfaces until every caller adapted; no premature deletions |
| Knowledge | KB1.1.0+privacy1, selective loader, source integrity/privacy already shipped | Residual operation/heading routing only;060 |
| Codex helper | Current installed going-bananas-coach entrypoint and helper with13 prior passing tests | Repo-controlled source, review-first adaptation and installation check;065 |
| New product modules | Full deterministic metrics, logical session calendar, v2 check-ins, optional blocks/anchors and reviewed proposal API absent |003–070 |

Environment at handover: working local dependencies and PostgreSQL tools exist. Existing shared cluster 55432 contains current app data; do not treat it as disposable. Earlier isolated implementation test cluster 55439 was stopped. Root main API was left running at8000; planning makes no process changes. These are checkpoint observations, not guarantees of later availability. Worker provisioning must verify actual state without inspecting secrets.

Current module paths and exact exports are pinned in owning task packets. New shared DTOs/signatures live in schemas.md. Source line numbers from the old9e6cc63 inventory are intentionally not reused.
