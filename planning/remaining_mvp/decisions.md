# Going Bananas — decision register (MVP-1.0, 2026-11-11)

Clean, final form of the register in `progress.md`. Where they differ, **this file wins**. Source: U = user, P = planner (engineering call within the brief's mandate), R = research.

## Product decisions

| ID | Decision | Src | Spec home |
| --- | --- | --- | --- |
| D1 | Coach = Codex skill (current entry point), with versioned repo-local source using `app.cli coach snapshot / query / submit`; app holds no model credentials and makes no LLM calls; `local_rules.v2` is the no-model daily fallback | U | coaching_contract §1–3 |
| D2 | Coach output is a changeset; nothing applies until accepted; accept all or untick changes; manual edits always allowed; any head change makes pending proposals `stale` (no merge) | U | coaching_contract §5 |
| D3 | Full FIT ingestion and FIT metrics in P0 (`intensity_time_distribution`, `work_interval_execution`), using `garmin-fit-sdk==21.221.0`; canonical SDK decoding fixed; real-device capability claims gated on G2 | U | metrics §1; schemas §2.1 |
| D4 | P0 UI is Mac browser only; loopback-only stays | U | prd §7 |
| D6 | Check-in v2: fatigue 0–10; symptoms per site (site, side, severity 0–10, timing `during|immediately_after|next_morning|hours_24_48|later|unknown`); gait change `yes|no|unsure`; illness `none|possible|present`; context tags; post-run session RPE 0–10 and modification reason | U | schemas §2.2 |
| D6a | Garmin `workout_rpe` (FIT session field 193 ÷ 10) imports as session RPE `source=garmin_fit`; manual entry overrides; both kept | U+P | metrics §4 |
| D7 | Quality sessions are run as structured watch workouts (laps carry `wkt_step_index`); app cannot publish workouts (API is pull-only) | U | metrics §4 |
| D8 | Exception-only check-ins; no check-in → plan stands without downgrade; prompts only for RPE (no Garmin RPE) and delayed symptoms; daily skill scope today…today+3 | U | coaching_contract §2, §7, §9 |
| D9 | Execution reference = app plan; watch steps only map laps to reps; structure mismatch → `not_assessable` `WATCH_WORKOUT_MISMATCH` | P | metrics §4 |
| D10 | Setup confirms anchor date, strength routine, pattern (1 quality, 1 long); deterministic 14-day fill; quality day is a placeholder until first review | U | coaching_contract §8 |
| D11 | Home = Today + prompts + guidance + pending proposal + block card + 14-day strip; Trends tab replaces Overview/History charts | U | prd §3 |
| D12 | Blocks are lightweight, optional, visible as a Home card + Block page; created/changed only via accepted proposals | U+R | schemas §2.4 |
| D13 | Strength = preferred commitment: ≥ 2/week kept; coach may propose moves (flagged, approved); never reduces count or changes lifting content; coach sees a confirmed routine template + latest Strong session per slot | U | schemas §2.4; coaching_contract V9 |
| D14 | Primary performance anchor = 5K (race/parkrun/TT, REC 009), scheduled only via block review when symptoms are stable and an objective needs it; effort-first until then; registry accepts 5K, 1 mile, 3 min, 20–30 min, workout-derived, lab, manual; no critical-speed testing in P0 | U delegated, P | metrics §3 |
| D15 | SUPERSEDED: preserve the populated current database, plans, check-ins, completion links and immutable coach history; additive migrations followed by transactional import/cutover (E24) | U | schemas §1 |
| D17 | 3 zones per modality; relative long-run rule (≥ 1.33 × 28-day median, ≥ 4 prior runs) for unplanned runs; one delayed-symptom window 16–48 h; P0 scope unchanged; remaining heuristic parameters accepted as versioned config | U | metrics §3–4 |
| D19 | No calendar roll-forward: days beyond the last planned date stay empty; Home banner `Plan ends on <date> — run the weekly review` when the last planned date ≤ today+6 | U | prd §6 |
| D18 | Codex-only skill has versioned repo source and preserves the existing installed entry point; safety guard V12 is a hard block on coach proposals; bootstrap quality slot is a placeholder; weekly review banner on a fixed weekday (default Sunday, editable) | U | coaching_contract §2–4 |

## Engineering decisions

| ID | Decision | Spec home |
| --- | --- | --- |
| E1 | Extend existing FastAPI/SQLAlchemy/Alembic/PostgreSQL 17 + React/Vite/TanStack stack; no rewrite | architecture |
| E2 | Keep official Garmin Personal API client (`garmin-connect-personal-api-python` 1.0.0, Garmin Ltd.) and the provenance chain | architecture §2 |
| E3 | Keep Strong CSV import (CLI) | prd §7 |
| E4 | Frontend extraction TASK-001 already delivered (ab5d699); do not replay | dependency_graph |
| E5 | Profile IANA timezone everywhere (default America/New_York); API supplies "today" | architecture §4, §6 |
| E6 | Excluded: readiness and goal-alignment composites, ACWR, monotony/strain, 10% rule, vendor proprietary scores as inputs, running dynamics injury load | metrics §1 |
| E7 | Distinct missing states in every result: `available|partial|missing|invalid|not_applicable|not_assessable` | metrics §2 |
| E8 | Coach operations = Workstream A route keys; Workstream B decision IDs are evidence questions inside them | coaching_contract §2 |
| E9 | New planned runs reference REC 001–REC 010 or `custom` with structure; imported prose is explicitly `legacy_unstructured`, never invented structure; strength is a separate kind | schemas §2.3 |
| E10 | Certainty derived by app: today…+6 committed, +7…+13 provisional; directional = block only | coaching_contract §4 |
| E11 | Race priority vocabulary `target|supported_exposure|benchmark|optional` | schemas §2.4 |
| E12 | Default explanation: one paragraph + expandable IDs/observations | prd §5 |
| E13 | Persist daily guidance only for a check-in or explicit request | schemas §2.6 |
| E14 | KB 1.1.0+privacy1 and selective loader already delivered (c0acf69); TASK-060 adds residual routing with compatibility | dependency_graph TASK-060 |
| E15 | First block via first `review_training_block` (`start`); null block until then | coaching_contract §2 |
| E16 | Minimal `goals` and `events` entities | schemas §2.4 |
| E17 | Keep legacy behavior until TASK-068 authority cutover; archive history and adapt existing consumers before retiring mutations | architecture §2 |
| E18 | Calendar lineage = logical sessions with per-session revisions; a version = revisions from one change; rollback = new version | schemas §2.3 |
| E19 | Streams stored as one JSONB/array row per activity; no GPS coordinates outside raw FIT | schemas §2.1 |
| E20 | App does no physiological conversion (e.g., 5K → threshold); zone anchors come from user or accepted calibration proposals | metrics §3 |
| E21 | Fixed operation → policy map; P 011 excluded (conflicts with running-first wording) | coaching_contract §6 |
| E22 | KB section extraction by exact heading; conditional topics via deterministic trigger table; no truncation | coaching_contract §6 |
| E23 | One integration owner for migrations, lockfiles, `main.py`, `cli.py`, `App.tsx`, `api.ts` | dependency_graph §3 |

## Superseded entries

- D5 (strength placeholder) → superseded by D13.
- "Deferred (periodization-dependent)" list in `progress.md` → resolved by D8, D10, D12, D14, E8–E10, E21–E22.
- D6 timing value `24_48h_later` in `progress.md` → final enum value `hours_24_48`.

## Current-baseline reconciliation (2026-11-11)

| ID | Binding decision | Source / owner |
| --- | --- | --- |
| E24 | Baseline main 5ebf981aa4517f4f73f3c97aa5d43232204466ce, migrations through 0009. Add0010–0015; no destructive legacy drops. TASK-068 imports cross-plan active_session_ids, preserves raw snapshots/UUIDs/completions/recurrence/history, replays idempotently, then switches one authority atomically. Preserve latest eligible old undo; no hidden legacy automatic-write bypass after cutover. | Current source + user preserve-working-app instruction; schemas,068 |
| E25 | Review each changeset and Codex-only are explicit user answers. Submit only stages; acceptance alone applies selected changes. No-change/reject-all create no calendar version. | User answers in this conversation |
| E26 | Snapshot decision-input fingerprint includes observation/profile/plan/anchor/KB revisions; check at submit and acceptance, re-evaluate safety and selected resulting state, lock once, commit atomically. Identical decision retries replay; changed terminal selection conflicts. | Preserve existing guards;061–063 |
| E27 | One-level repeat blocks expand in interleaved order with stable original paths and ordinal. No nested blocks or implicit grouping. | Shared schemas contract |
| E28 | G2 is real-device acceptance evidence, not a prerequisite to writing synthetic-safe implementations. Missing representative evidence stays unverified; calculators return defined missing/not_assessable outputs. Full P0-A real-device acceptance remains gated, or user explicitly approves a scope reduction. | Manager;004/release |
| E29 | Trace coverage denominator includes uncovered timer-on edges; common session origin; unknown aggregates are null, observed empty periods zero; immutable effective-dated anchors and complete source provenance. Recompute old/new dependency scopes and all completion links transactionally. | Metrics audit;metrics/030 |
| E30 | Confirmed weekly/alternating strength recurrence survives; defaults and inferred suggestions only for unconfirmed setup. | Existing functionality;014/068 |
| E31 | New functionality is staged behind persisted workflow authority; existing pages/routes stay operational until replacement is complete. P0-A can be demonstrated in isolated demo before production cutover. |050/068/070 |
| E32 | Planning only until finished spec/swarm plan approval, as handover §H. Then root manager → Astra low/medium leads → Sol low workers; Luna only bounded mechanical work. User standing authorization allows completed, reviewed, green tasks to main; no push authorization. | User + handover |

E33 (planner reconciliation, not an original research threshold): reconstructed timer-on sum differs from canonical session timer by more than max(1 second,1% of timer) → TIMER_MISMATCH and reconstructed trace metrics not_assessable. Valid canonical summary timer still contributes to volume/completion. This is an engineering consistency tolerance, not a physiological or injury threshold.

E34 (transaction integration): every calendar-authority mutation acquires advisory lock71382413 before app_state row lock. TASK-030 owns a bounded db.bump_data_revision adaptation that coalesces source bumps per outer transaction only in calendar authority; legacy behavior stays intact. before_flush captures dependencies without recursive flush/bump. Derived-only refresh never increments source revision; rollback/new transactions cannot inherit a prior bump marker.

E35 (legacy safety preservation): recent schema1 check-ins remain qualitative source facts in the72-hour coaching safety window after cutover. legacy_safety_active is true for gait affected, severe symptoms, or moderate symptoms with change worse, and activates V12. Do not invent numeric severity/fatigue. Snapshot provenance retains original categories and IDs; older facts remain history without becoming current safety measurements.
