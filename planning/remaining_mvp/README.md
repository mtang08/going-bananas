# Going Bananas — remaining MVP plan

Status: **MVP-1.0, SIGNED OFF; implementation authorized**.
Readiness: [all three independent reviews passed](reviews/readiness_summary.md). Artifact hashes: [spec_manifest.sha256](spec_manifest.sha256).
Baseline: `main@5ebf981aa4517f4f73f3c97aa5d43232204466ce` (2026-11-11).
Working and eventual pinned location: `planning/remaining_mvp/`; no second copy required.
Original handover remains unchanged at `/Users/mtang/dev/going_bananas_planning_handover`.

The MVP adds deterministic FIT-backed metrics, a versioned calendar, exception check-ins, and a Codex coach that submits changes for review. Existing saved plans, completions and history survive. The current coach remains operational until the review workflow is ready for an atomic cutover.

| Read | Purpose |
| --- | --- |
| [Decisions](decisions.md), [PRD](prd.md) | Accepted behavior and scope |
| [Schemas](schemas.md), [metrics](metrics.md), [coaching contract](coaching_contract.md), [architecture](architecture.md) | Exact implementation contracts |
| [Task DAG](dependency_graph.md), [worker brief](worker_instructions.md), [packets](swarm_tasks/) | Ordered execution and ownership |
| [Acceptance](acceptance.md), [integration/release](integration_and_release.md) | Verification, preservation and release gates |
| [Inventory](codebase_inventory.md), [research intake](research_intake.md) | Current source and research provenance |
| [Wire/hash fixtures](contracts/) | Static examples for compatible worker output |
| [Deferred evidence](unresolved_nonblocking.md), [progress](progress.md), [reviews](reviews/) | Evidence limits and readiness findings |

Normative precedence: decisions > coaching contract = schemas = metrics > architecture > PRD > packets > research. A conflict is a planning defect to fix, not worker discretion. Historical `_handoff*` and `_amendments.md` files are intake notes only; current contracts incorporate their applicable decisions.

Completed TASK-001/002 and the KB overlay are recorded, not assigned again. G2 real-device evidence is still pending; synthetic implementation can proceed after approval, but full real-device release cannot claim that evidence passed.

Execution tradeoffs: 32 remaining packets plus two completed records; keep root/Astra review and use Sol low-effort workers only after shared contracts land. File-disjoint tasks can run in parallel within the four-slot limit. Additive migration and staged cutover cost more code than replacing tables, but preserve current functionality and data. Imported prose stays readable with explicitly unassessable structured metrics. G2 can limit real-device signoff even when synthetic tests pass; no schedule or cost guarantee is implied.

User signoff (2026-11-12): “just ask me using your tool for the highest impact / priority decisions, otherwise consider it signed off.” Routine engineering choices and approved task execution proceed autonomously.
