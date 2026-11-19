# Choosing a review

| Review | When | Operation | Scope |
| --- | --- | --- | --- |
| Weekly (Sunday) review | The Sunday entrypoint below | `review_rolling_plan`, or `review_training_block` when due | Next 14 days; days 1–7 committed, days 8–14 provisional |
| Exception review | The app recommends it (a caution or hold finding, or a patch reassessment), or the athlete reports a material change | `exception_review` | Committed window (days 1–7) only; never edit days 8–14 |
| Block review | No active block, the review date or benchmark is due, an early-review trigger, or a "Needs bigger review" finding | `review_training_block` | The block and the next 14 days |
| Post-event review | The app shows a race review due | `post_event_review` | Days 1–7 |

Other requests, only when asked for exactly: `select_quality_session`, `recalibrate_intensity`, `handle_goal_or_race_change`.

Use the fresh snapshot's actual scope and server schema as authority. Keep the first week committed and the second week provisional. Explain dose, spacing, strength interaction, and uncertainty from the returned facts and research. A missing stream, RPE, recovery night, or calibration is not a normal value. Do not merge HR and speed into a single physiology score.

Two snapshot sections describe trends. `quality_progression` lists recent sessions with the same work steps (`signature`, for example `ws1:4xt300` = 4 × 5 min). Use it to repeat, progress, or consolidate a workout: compare work pace, work HR, rep variation, and last-versus-first change only across `available` or `partial` points, and say how many sessions the comparison rests on. HR is absent for reps under 3 minutes; that is unknown, not normal. `aerobic_efficiency` reports metres per heartbeat and heart-rate drift on steady easy and long runs, always next to mean pace and HR. It is a descriptive trend under comparable conditions, not a fitness score, readiness gate, or threshold (KB E-DATA-02, policy P015); heat, hills, fatigue, and sensor error change it. Do not change training because of one run's value.

If recent symptoms, altered gait, illness, or clinical restrictions are present, honor the snapshot safety guard and avoid increasing near-term running load. Describe uncertainty and escalation without inventing a diagnosis or clearance. If an accepted target depends on a proposed anchor, the app requires reviewing that anchor alongside its target changes.

## One Sunday entrypoint

The athlete should not have to choose a protocol operation. First check for an active proposal using the main workflow. For a new Sunday review, inspect `snapshot --operation review_rolling_plan`: its `block` contains the active block, including `review_date`, or is null. For routing, read only its block and date fields; read metrics and KB excerpts from the snapshot for the selected operation. If no block exists, the review date is due, or reported evidence meets an early-review trigger, get a fresh `snapshot --operation review_training_block` and prepare that operation instead. Also route to `review_training_block` when `exception_summary.open_escalations` is above zero, or when `block.benchmark_status.status` is `completed` or `missed`, or the block has no benchmark. Never put block changes into a rolling-plan proposal. For an existing draft, inspect its document and refresh with the correct operation if the scope must change, preserving its ID and obeying live revision validation. Do not read raw app files or invent a block query.

With no active block, establish the objective, start/review dates, progression dimension, completion indicators, maintained qualities, constraints, and early-review triggers from the athlete's priorities and evidence. Include the next 14 days. A proposed block becomes active only after the athlete selects and accepts its block change in the app. A regular weekly review adapts the next 14 days inside the accepted block; it does not silently replace the objective. A due block review assesses response and indicators before continuing, consolidating, or proposing a new objective. Elapsed block time is calendar context, not proof that the objective is achieved.

Keep days 1–7 committed and days 8–14 provisional; these rolling windows need not align with Monday–Sunday grid rows. Saved per-session provisional flags are authoritative. Explain the full workout prescription in each proposed session and identify changes versus the accepted calendar. The app's two-week grid exposes details; do not imply that a draft grid is accepted. Use Monday–Sunday weekly mileage in the profile timezone: recorded running plus remaining accepted runs, with time-based distance estimates labeled. Pending drafts never count toward that forecast.

## Exception ladder

Choose the lowest level that addresses the finding, in this order: current session, next session, next days (at most 3), committed window (days 1–7), then block. Reach the block level only through `escalation: review_training_block`, and keep only protective changes inside the committed window when you do.

- Patch window: at most 3 days for Logged or Caution findings, and at most 7 days for Hold or Needs bigger review findings.
- Set `reassess_on` within 7 days.
- List every committed session deliberately left unchanged in `exception.unchanged`, with a reason.
- Never edit days 8–14; the next weekly review owns them.
- Do not add sessions, change run frequency, or move, add, or delete strength sessions.
- Missed work is not debt; do not stack sessions to make it up.
- A no-change exception review is valid when monitoring is enough.
- Do not restore a removed hard session because one metric looks normal again; use the patch's return criteria.

## Using the exception summary on Sunday

- Read `exception_summary` first: the findings since the last review, patches and their status, RPE mismatches by session class, quality sessions planned, completed, modified, removed, and failed, recurring symptom sites, and open escalations.
- For each patched pattern, decide whether it is resolved, repeating, or needs a block review. Resolve patches whose window has passed with `patch_resolutions`.
- Accepting a weekly review marks the open findings it saw as reviewed, except Needs bigger review findings. Mention each finding you relied on.
- Repeated related exceptions can change the committed window; they never silently change the block.

## Block-ending benchmark

- Setting it (block review): choose a time trial (an REC009 session) or an existing event dated in `[review_date−6, review_date]`. Put it in `block_change.version_fields.benchmark` with a repeatable `protocol` (same distance, similar route, two easy days before), `progress_if`, and `consolidate_if`. For a time trial, include `REC009` in `eligible_recipe_ids`; the app rejects the block change otherwise. For an event, set `event_id`; the event date must equal `planned_date`.
- Placing it (weekly review, guidance only): for a `time_trial` benchmark whose `planned_date` is inside the next 14 days and no REC009 session is scheduled (`block.benchmark_status.scheduled_date` is null), change that day's run, or the nearest on-cycle run, into REC009. It replaces that week's quality session; keep easy days before it and no demanding session the day after. Do not add a second run that day. For an `event` benchmark, use the scheduled event and do not add a REC009; keep the two days before it easy.
- Using it (block review): read `block.benchmark_status`, the `event` section, and `benchmark_history`. Set `event_review` with the benchmark's `activity_id` or `event_id`, `outcome` (`progress`, `consolidate`, `recalibrate_only`, or `inconclusive`), and `compared_with` (the prior result with the same protocol). Judge the result against the `progress_if` and `consolidate_if` set in advance, together with the training response. If the result is credible, put `anchor_changes` in the same proposal. Then set the next block's benchmark.
- If it is missed or compromised: reschedule it within 14 days or extend the block. Never test through illness or symptoms. A compromised result is `inconclusive`.
- If the athlete says the app matched the wrong activity, point them to the `Choose activity` control on the Training block page. The coach never sets the match.
