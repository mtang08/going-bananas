# Going Bananas — PRD (v0.2, reviewed 2026-11-11)

Status: **planning reconciliation 2026-11-11**. User confirmed review of each changeset and Codex-only entry point. Not frozen (freeze happens with the full spec package). Metric parameters in `metrics.md`.
Decision IDs (D*, E*) refer to `progress.md` → Decision register.
Baseline repo: `going-bananas` `main` @ `5ebf981aa4517f4f73f3c97aa5d43232204466ce`.

## 1. Product in one paragraph

A local, single-user running app on the Mac. It shows what training actually happened (Garmin summaries, FIT laps and traces, recovery, Strong lifts), keeps a versioned rolling 14-day calendar inside an optional training block, and lets a Codex coaching skill propose calendar changes that the user approves change by change. Dashboard and metrics never call an LLM. Running is the optimization priority; two weekly lifts are a preferred commitment the coach plans around.

## 2. Athlete context the product must hold (dated, editable)

Stored in app state, never in the KB. Entered at setup and editable in Settings.

- Device: Garmin Forerunner 265. Timezone: America/New_York (default).
- Run cycle: every other day from a confirmed anchor date; 4 runs then 3 runs per 7 days; does not reset at week boundaries.
- Default weekly pattern: 1 quality, 1 long, rest easy.
- Strength: 2 full-body sessions/week, default Mon and Fri nights (sometimes Tue/Sat); routine template per D13.
- Symptoms: left posterior tibial tendon symptoms can follow longer runs, sometimes 16–40 h later. No diagnosis.
- Goals: 3–6 months — sustainable volume and aerobic development, uninterrupted training. Long term — possible 2028 NYC Marathon (unconfirmed). Secondary — faster mile and 5K; possible sub-2 half if an event is confirmed.

## 3. Screens (P0)

| Screen | Contents | Decision |
| --- | --- | --- |
| **Home** | Today card (planned session, recipe, targets or effort cue); pending prompts (RPE, delayed-response check); latest daily guidance; pending coach proposal with diff; block card; 14-day calendar strip (committed vs provisional, planned/completed/changed/missed markers) | D11, D12, E10 |
| **Calendar** | 14-day detail; edit, move, add, delete a session; proposal review (accept all / untick changes); version history and rollback | D2, E10 |
| **Activity detail** | Summary, laps, planned vs actual per rep for structured workouts, RPE (Garmin or manual), symptoms linked to the run, data-quality flags | D3, D6, D9 |
| **Trends** | Rolling volume/frequency, long-run exposure, sRPE load, intensity time (when anchors exist), hard-session spacing, recovery panel (sleep, HRV, RHR with missing nights shown) | D3, E6 |
| **Block** | Objective, maintained qualities, eligible recipes, review date, triggers, decision history | D12 |
| **Strength** | Existing Strong history (unchanged) | E3 |
| **Settings** | Setup wizard (anchor, strength template, weekly pattern), goals/events, intensity anchors, sync, data management | D10, D13, D14, E16 |

Check-in is a Home modal, opened by a prompt or by the user. No routing library change is implied here; navigation details go in `architecture.md`.

## 4. P0-A journeys — deterministic analytics (no LLM)

1. **Setup.** User confirms anchor date, strength template (pre-filled from Strong), weekly pattern, goals, events, timezone. App fills the next 14 days deterministically (D10). Block = null.
2. **Sync.** Real-mode sync pulls activity summaries, FIT files for runs, sleep, HRV, daily HR. Re-sync is idempotent. Each dataset shows freshness.
3. **See today.** Home shows today's planned session and the calendar strip.
4. **After a run.** The run matches to the planned session or shows as unmatched/extra. If FIT has `workout_rpe`, RPE fills automatically; otherwise Home prompts for RPE (0–10) and, if the session changed, a modification reason.
5. **Delayed-response check.** 16–48 h after a long run, or after any run followed by a symptom report, Home prompts: pain yes/no → site, side, severity 0–10, onset timing; gait change.
6. **Exception check-in.** User opens the check-in to report pain, gait change, illness, fatigue, or context. Deterministic rules return proceed/modify/reschedule/rest immediately and may raise "coach review suggested". No check-in → plan stands (D8).
7. **Edit the plan.** User edits, moves, adds, or deletes sessions. Each edit creates a new calendar version with actor, time, optional reason. Missed sessions stay as facts; nothing is auto-rescheduled.
8. **Inspect execution.** Structured workout: per-rep planned vs actual using lap step indices; mismatched watch structure shows `not_assessable` with planned vs watch steps (D9).
9. **Trends.** User reviews the P0 metrics; missing data appears as missing, never as normal.
10. **Anchors.** User records a 5K result or other protocol; intensity metrics turn on once an anchor exists (D14).

## 5. P0-B journeys — coach (Codex skill)

All coach output is a **proposal**: a changeset against a named calendar/block version. Nothing applies until the user accepts (D2).

1. **Weekly review** (`review_rolling_plan`). User runs the skill. It reads a compact snapshot and routed KB sections, then submits a proposal: changes to committed and provisional days, preserved items, rationale, confidence, evidence/policy/recipe IDs, follow-up. App validates structure, shows the diff, user accepts all or unticks changes, app writes a new calendar version.
2. **Daily exception** (`proceed_or_modify_today`). Triggered by "coach review suggested". Proposal may touch only sessions dated today through today+3.
3. **Block review** (`review_training_block`). First run may propose `start`; later runs propose continue/extend/consolidate/transition/replace/end. Accepted decisions append to block history.
4. **Recalibration** (`recalibrate_intensity`). After a benchmark, the skill proposes an anchor update with method and confidence; user accepts.
5. **Goal/race change** (`handle_goal_or_race_change`). New or changed event triggers a block-review style proposal; no cramming.
6. **Next review uses outcomes.** Snapshots include prior proposals, what was accepted, what actually happened, and later symptom responses.
7. **Rollback.** User undoes the latest eligible changed revision; the app writes a compensating version with lineage and preserves completed, locked and historical sessions. No-change reviews do not hide the latest eligible undo.

## 6. Fallback behavior

| Condition | Behavior |
| --- | --- |
| Skill never run | Calendar stands; rules give daily guidance. Days after the last planned date stay empty (no automatic roll-forward, D19); Home shows `Plan ends on <date> — run the weekly review` once the last planned date is ≤ today+6 |
| Proposal base version no longer current (manual edit or newer version) | Proposal marked `stale`; cannot be accepted; rerun skill |
| Proposal fails validation | Rejected with field-level errors; nothing written |
| KB missing or hash mismatch | `coach snapshot` returns an error; app dashboards unaffected |
| No FIT for a run | Summary-level metrics only; FIT-dependent metrics `not_assessable` |
| No recovery data for a night | Shown as missing; no imputed value |
| No intensity anchor | Intensity metrics `not_assessable`; quality sessions use effort targets |
| No check-in | Planned session stands; confidence reflects missing subjective input |

## 7. Scope boundaries

**In P0:** everything in §3–§6.

**Out of P0:** in-app LLM calls or chat; phone access; publishing workouts to the watch (API is pull-only); lifting prescription or analytics beyond existing Strong history; readiness/goal-alignment composites; ACWR, monotony/strain, 10% rule; vendor training status/load/VO2max as inputs; running power/dynamics; body composition; multi-user; vector retrieval; automatic policy activation.

**P1 candidates:** comparable-effort speed, aerobic decoupling, transparent HR load, terrain exposure; phone access with auth; Strong CSV upload in UI; retrieval-miss regression across all evaluation cases; block outcome dashboard; critical-speed testing.

## 8. Definition of done (P0)

P0-A done when, on this Mac with real data:
- A full re-sync is idempotent (no double counting).
- Home shows today and 14 days; manual edits version correctly.
- A structured workout shows per-rep planned vs actual.
- RPE and delayed-response prompts appear on schedule.
- Trends show all P0 metrics with explicit missing states.
- No LLM call occurs anywhere in the app.

P0-B done when:
- A weekly skill run produces a proposal, the user unticks one change, accepts the rest, and the calendar shows the new version with lineage.
- A daily exception produces a proposal limited to today..today+3.
- A stale proposal cannot be accepted.
- The next weekly snapshot includes the previous proposal, its acceptance, the actual sessions, and later symptom reports.
- KB-unavailable and invalid-proposal paths return defined errors.

## 9. Compatibility and release transition

Current persisted weekly/daily coaching, revision history, guarded undo, Strong history, check-ins, recurrence and exports remain available while replacement components are built. TASK-050 exposes the new experience only in demo/test fixtures with calendar authority; real-mode legacy authority keeps Overview/Coach/Cycle/Settings/check-in behavior. TASK-068 performs the populated-state migration and single authority switch after new API, UI and Codex helper are ready. Imported prescriptions keep their original prose and identity without invented recipes or structure.

After cutover, every new coaching changeset requires explicit app review before application, including daily changes. Old automatic-submit routes cannot bypass review: they return the documented upgrade response. Old read/history routes remain available. The latest eligible pre-cutover undo remains available through TASK-068's guarded adapter. User approval is the only activation path; submitting a proposal never activates it. The installed external Codex skill remains untouched during planning; implementation packages a repo-local skill/helper and explicitly updates the installation under implementation authorization. No Claude Code delivery is in scope.

Synthetic FIT tests establish parser and metric mechanics. G2 is a real-device acceptance gate: do not claim structured-workout/RPE device support verified until observed-device evidence passes. Planning and approved synthetic implementation can proceed without that evidence.
