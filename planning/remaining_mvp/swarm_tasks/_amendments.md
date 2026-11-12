# Planner amendments applied to the spec during packet writing (2026-11-11)

All are already in the spec files. Every packet (new or existing) must conform.

| # | Amendment | Spec file |
| --- | --- | --- |
| A1 | KB manifest routing heading fix: `select_quality_session` → `topics/intensity_and_workout_methods.md` section "Two demanding exposures within the agreed rolling-cycle run count" (TASK-060 edits manifest) | coaching_contract §6 |
| A2 | `conflicts` table, `Conflict` model, `GET /conflicts`, `POST /conflicts/{id}/resolve` are KEPT | schemas §1, architecture §2 |
| A3 | `services/summary.py`, `export-context` CLI, `GET /context` kept until TASK-064 deletes them | dependency_graph, architecture §2 |
| A4 | `local_rules.v2`: remove all absent-input downgrades (`coaching.py:266` no-check-in clause, `:291`, `:306`, `:319`); `unknown` never downgrades; delete `EVIDENCE` dict; evidence IDs from KB policy records; decision enum keeps `seek_clinical_input` (do NOT rename to `seek_input`) | coaching_contract §7, schemas §2.6 |
| A5 | Running sport values `running|trail_running|treadmill_running` | metrics §4 |
| A6 | Long-run prior max window 30 days (current excluded); 28 days only for classification median | metrics §4 |
| A7 | `fit-inventory` also emits redacted key paths + types of Personal API responses (activity detail, workouts, sleep, HRV, daily HR); TASK-004 is NOT `G2: pending` (it produces G2) | schemas §5 |
| A8 | TASK-003 owns `scripts/verify-restore.py`, `verify-export.py`, `verify-real.py` (model imports only) | dependency_graph |
| A9 | `GET /calendar` returns `today`, `timezone`, `start`, `end`, `version`, `head`, `last_planned_date`; D19 no roll-forward; Home banner `Plan ends on <date> — run the weekly review` when `last_planned_date` ≤ today+6 | schemas §3.1, prd §6 |
| A10 | Delayed-symptom prompt window 16–48 h | prd §4, coaching_contract §9 |
| A11 | Skill CLI calls use `scripts/with-mode ${GB_MODE:-real}`; `deep_evidence_audit` is not a P0 operation | coaching_contract §3.2 |
| A12 | Empty `changes` = valid "proceed unchanged" (accept writes no version); reject-all writes no version | coaching_contract §5 |
| A13 | C16 `unresolved_baseline` maps to objective_status `unresolved` + rationale | decisions |
| A14 | `daily_guidance.created_at timestamptz default now()` | schemas §2.6 |
| A15 | `coach query ... --result-id` for `explain_metric` | schemas §5 |
| A16 | `select_quality_session` uses the Rolling snapshot projection; daily never receives candidate recipe lists | schemas §4.1, coaching_contract §6 |
| A17 | `metric_configs` not seeded by migration; TASK-011 adds `ensure_metric_config(session, metric_id, method_version, config) -> str` | schemas §2.5 |
| A18 | Anchor units: `performance_5k`/`performance_1mile` → `s`; `performance_3min` → `m`; `performance_20_30min` → `mps`; unit enum `bpm|mps|s|m` | schemas §2.5 |
| A19 | `fit-backfill`, `metrics-recompute`, `strong-import` CLI wiring → TASK-030; TASK-010 provides `backfill_fit()` service only | dependency_graph |
| A20 | TASK-064 no longer owns `services/calendar.py`; TASK-012 marks other pending proposals stale on every new version | dependency_graph |
| A21 | Hash navigation is added by TASK-050 (baseline has none) | architecture §4 |
| A22 | `checkin_revisions` (v2) table exists: `checkin_id, version, payload jsonb, recorded_at`; written on every PATCH | schemas §2.2 |
| A23 | Metric recompute (incl. anchor-wide) runs synchronously in a `before_commit` hook (TASK-030); FIT decode in sync worker | architecture §3 |
| A24 | TASK-024 depends on GATE-G2 (recovery field mapping); TASK-026 reads stored `planned_actual_session` rows; TASK-030 does not own `api/core.py`; wave 1–2 API tests mount routers on a bare `FastAPI()` | dependency_graph |
| A25 | `calendar_session_revisions.placeholder bool default false`; recipe required for runs unless `custom` or `placeholder`; V15 uses `placeholder`; setting `recipe_id` clears it | schemas §2.3, coaching_contract §4, §8 |
| A26 | `structure` = list of steps or one-level repeat blocks `{type:'repeat', count, steps:[...]}` | schemas §2.3 |
| A27 | `PUT /calendar/completions/{uid}`: linking a subject → status computed by `planned_actual_session`; without subject, `status` ∈ {skipped, unknown} required | schemas §3.1 |
| A28 | `GET /coach/daily` implemented by TASK-013 in `api/checkins.py` (P0-A); TASK-063 must not implement it | schemas §3.5, dependency_graph |
| A29 | Prompt answering rules; `missing_activity` ignores certainty (run sessions in [today−7, today−1]) | coaching_contract §9 |
| A30 | `make backup` for real data via `scripts/with-mode real` (acceptance/integration docs) | integration_and_release |
| A31 | `GET /prompts` hides prompts whose `opens_at` is in the future (TASK-013) | schemas §3.2 |
