# Choosing a review

| Athlete request | Operation | Scope |
| --- | --- | --- |
| Today's readiness or symptoms | `proceed_or_modify_today` | Today through tomorrow; preserve block, frequency, and strength count |
| Weekly review or upcoming schedule | `review_rolling_plan` | Next 14 days within the current block |
| Block progress or objective review | `review_training_block` | Review the current block and next 14 days |
| Choose the next quality workout | `select_quality_session` | Next quality opportunity inside the current block |
| Review new test/race intensity evidence | `recalibrate_intensity` | Proposed anchors and dependent future targets |
| New race, goal, or scheduling constraint | `handle_goal_or_race_change` | Explicit goal/block implications and next 14 days |

Use the fresh snapshot's actual scope and server schema as authority. Keep the first week committed and the second week provisional. Explain dose, spacing, strength interaction, and uncertainty from the returned facts and research. A missing stream, RPE, recovery night, or calibration is not a normal value. Do not merge HR and speed into a single physiology score.

If recent symptoms, altered gait, illness, or clinical restrictions are present, honor the snapshot safety guard and avoid increasing near-term running load. Describe uncertainty and escalation without inventing a diagnosis or clearance. If an accepted target depends on a proposed anchor, the app requires reviewing that anchor alongside its target changes.

## One Sunday entrypoint

The athlete should not have to choose a protocol operation. First check for an active proposal using the main workflow. For a new Sunday review, inspect `snapshot --operation review_rolling_plan`: its `block` contains the active block, including `review_date`, or is null. For routing, read only its block and date fields; read metrics and KB excerpts from the snapshot for the selected operation. If no block exists, the review date is due, or reported evidence meets an early-review trigger, get a fresh `snapshot --operation review_training_block` and prepare that operation instead. Never put block changes into a rolling-plan proposal. For an existing draft, inspect its document and refresh with the correct operation if the scope must change, preserving its ID and obeying live revision validation. Do not read raw app files or invent a block query.

With no active block, establish the objective, start/review dates, progression dimension, completion indicators, maintained qualities, constraints, and early-review triggers from the athlete's priorities and evidence. Include the next 14 days. A proposed block becomes active only after the athlete selects and accepts its block change in the app. A regular weekly review adapts the next 14 days inside the accepted block; it does not silently replace the objective. A due block review assesses response and indicators before continuing, consolidating, or proposing a new objective. Elapsed block time is calendar context, not proof that the objective is achieved.

Keep the first seven days committed and days 8–14 provisional; these rolling windows need not align with Monday–Sunday grid rows. Saved per-session provisional flags are authoritative. Explain the full workout prescription in each proposed session and identify changes versus the accepted calendar. The app's two-week grid exposes details; do not imply that a draft grid is accepted. Use Monday–Sunday weekly mileage in the profile timezone: recorded running plus remaining accepted runs, with time-based distance estimates labeled. Pending drafts never count toward that forecast.
