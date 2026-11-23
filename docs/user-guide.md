Your daily plan, Sunday review, and training blocks in one local app. Use this guide to record feedback, work with the coach, and review changes before they apply.

## Start here

Going Bananas brings your recorded running, recovery, lifting history, and accepted running plan together. Use the app for check-ins and review; ask the Codex coach to interpret the evidence and prepare changes.

If the app is already running, just open http://127.0.0.1:8000; do not start a second copy. Otherwise, on this Mac, start from the repository with `make db-start`, `make migrate`, `make build`, and `make start`, then open http://127.0.0.1:8000. The README covers first-time setup and imports. `Ctrl+C` stops the app; your saved data remains. The app currently runs locally on this Mac.

## Daily check-in

Open [Home](#home) to see what needs attention, weekly mileage, **Planned vs done**, today's accepted session, and this week's sessions with their recorded distance, time, pace, heart rate, RPE, and comparison with the plan. Open a session for its full prescription, including warm-up, intervals, recovery, targets, and notes. In a rolling proposal, days 1–7 are committed planning and day 8 onward is provisional. Calendar shows one Monday–Sunday week at a time. Use each session’s saved badge to see whether it is provisional. The **Planned vs done** card covers this week or last week (Monday–Sunday): sessions done against planned (so far, while the week is still running), time, running distance, how each key session went (quality, long, and benchmark runs, with steps completed and time in target), what was missed or not recorded, unplanned sessions, and sessions an accepted change removed. A value the app cannot know shows as unknown, never as zero. The coach reads the same numbers in your Sunday review.

Record actual effort and post-run response when prompted. Report fatigue, illness, symptoms, or gait changes when relevant. Missing observations stay unknown, so a blank check-in does not mean everything was normal.

Each check-in, post-run RPE, and recorded outcome runs the exception check. An isolated HRV, resting-HR, sleep, or pace reading on its own is logged for your Sunday review. Repeated or converging signals may raise a finding on Home; a new symptom, illness, or gait change can raise one immediately. See **Exception review**.

## Sunday review

Start one manual coaching review on Sunday evening. You do not need to decide whether it should be a weekly or block review:

> Use $going-bananas-coach for my Sunday review in real mode. Review my current block and talk through the plan with me. My schedule changes and feedback are: …

The coach checks the active block and its review date. With no block, it helps establish one. When the block is due or an early-review trigger applies, it reviews the objective and response. Otherwise, it reviews the rest of the current block, from today through the block's review date and always at least 14 days ahead, keeping day 8 onward provisional.

This cadence is manual. No coaching review or proposal runs automatically on Sunday. Extra reviews are useful after a material change, symptoms, or a new goal.

## Exception review

The Sunday review is the normal control loop. Between Sundays, the app checks check-ins, post-run RPE against each session's intent, completions, and races. One HRV, resting-HR, sleep, or pace value never raises a concern on its own.

- **Logged**: kept for your Sunday review. Home lists these under **Logged for Sunday review**.
- **Caution** or **Hold**: Home shows the finding under **Needs attention** and recommends an exception review.
- **Needs bigger review**: Home recommends a block review instead of another patch. For symptoms or illness, outside evaluation may be needed.

When Home recommends an exception review, copy its prompt:

> Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require.

The coach makes the smallest change that works: today's session, the next session, the next few days, and at most this committed week (days 1–7). It never edits provisional days (day 8 onward). The proposal lists the sessions it leaves unchanged, a reassess date, what to watch for, when to return to plan, and when to escalate. Accepted changes show **Patched · reassess** with the day on Home and in Calendar.

On the reassess day, Home shows **Reassess due**. Choose **Mark resolved** when you are back to normal, or **Still not right** to keep it for the coach. To ask the coach to reassess:

> Use $going-bananas-coach to reassess the open exception patch.

When a finding needs a bigger review:

> Use $going-bananas-coach for a block review. An exception needs a bigger review.

Use **Dismiss** on a finding that is wrong or already handled. A finding never closes just because a metric returns to normal; a review, a resolved patch, or your dismissal closes it.

## After a race

A completed PR or benchmark race puts a race review on Home for 7 days. A training run at an event gets no race review. Treat the 1–3 days after it as an observation window, not a fixed rest prescription. Copy the prompt from Home, which names the race, or use:

> Use $going-bananas-coach for a post-race review of … on ….

The review records pacing, effort and the limiting factor, conditions, symptoms, and recovery. It may propose new intensity anchors and changes inside the committed week. A race that is the block's ending benchmark is reviewed in the block review instead.

## Block-ending benchmark

A training block ends with a benchmark, a time trial or a race, when one is due: there is no benchmark result yet, your last credible result is about 6 weeks old (42 days or more before the week the benchmark would fall in), or a race you run as a goal or benchmark effort falls in the block, in which case that race is the benchmark. The benchmark falls in the week before the block's last week. The block review that sets the block also sets the benchmark protocol, its date, and what counts as progress or consolidation. The block review places the time trial; it shows a **Benchmark** badge. The Sunday review 7 days before the block's review date is the block review, so it has the result in hand, and the next block starts the day after the review date.

A block without a benchmark is judged on the completion indicators shown on [Training block](#block), such as workout progression, aerobic efficiency on easy runs, completed key sessions, and effort against intent. Its review keeps your intensity anchors; only a benchmark or race result changes them.

The app matches the benchmark run automatically. If it chose the wrong run, open [Training block](#block) and use **Choose activity** in the Block benchmark card. **Use automatic match** undoes your choice.

When the benchmark is complete, Home recommends a block review:

> Use $going-bananas-coach for a block review. Review the block benchmark.

That review compares the result with earlier benchmarks of the same protocol, decides whether to progress, consolidate, or only recalibrate, and recalibrates intensity anchors. Results stay in [Trends](#trends) under **Benchmark history**. A missed benchmark also leads to a block review; never force a test through illness or symptoms.

## Training blocks and weekly plans

A block gives the weekly plan direction: an objective, start date, review date, progression dimension, and observable completion indicators. It also records qualities to maintain, constraints, and reasons to review early. A weekly plan chooses the sessions that serve that accepted objective from today through the block's review date, and always at least 14 days ahead.

To establish your first block now:

> Use $going-bananas-coach to establish my first training block in real mode. Propose its objective, start and review dates, progression dimension, completion indicators, and sessions through its review date using my current evidence and priorities.

The proposed block becomes active only after you select and accept its block change in the app. Creating or revising the draft does not activate it.

Open [Training block](#block) to inspect the current direction, review timing, and block benchmark. The timeline shows elapsed calendar time; it does not prove that you have achieved the objective. A block review considers actual response and indicators before continuing, consolidating, or changing direction. A regular weekly review cannot silently change the block.

## Events and your goal race

Add every upcoming race or event under [Settings](#settings), **Events**, with its date, distance, a purpose, and, if you want one, a goal time. The purpose says how the event is run and prepared for:

- **Race it (PR attempt):** you are racing for a result. The coach plans a taper sized to the event.
- **Benchmark effort:** a quality effort. The coach reduces the load around it only enough for an interpretable result, with no full taper.
- **Training run:** a session that happens to fall at an event. No taper, you do not run it maximally, and it gets no race review.

Your upcoming events are listed in priority order. Rank 1 is your **goal race**, marked with a badge. Use **Move up** and **Move down** on each row to reorder them; both work from the keyboard. Every training block builds toward the goal race, so the [Training block](#block) page shows the earlier blocks, the current block, the emphases the coach expects between now and race day, your other events by date, and race day. The emphases are direction only: the coach sets them again at each block review. Home's block line names the goal race.

Rank decides what the blocks build toward. Purpose decides how each event is prepared for and run. A Race it 10K ranked third still gets its own taper inside the current block, and the coach says what that costs the goal-race build in its proposal. Accept the proposal, or change the event's purpose, to decide.

Your goal time is a target, not a prediction. The coach judges whether it is plausible from your recent evidence and says how confident it is.

When the goal race changes (you move it up or down, cancel it, or its date passes), the Training block page and Home say the block was planned for another race, and the next Sunday review is a block review. Nothing on the calendar changes until you accept a proposal. Events entered after a block was planned have the same effect once.

## Review and revise a proposal

Discuss the plan in one chat. Ask for a shorter workout or a different day and the coach will work from the same review context. When the plan looks right, say “looks good” or “publish it.” The coach saves the agreed plan and provides its review link. **Pending your review; nothing applied.** On Home, open **Needs attention → Review** to inspect the rationale and each proposed change, including workout details, block changes, and calibration anchors when present.

- Valid session changes start checked. Uncheck any you want to reject, select any block or anchor changes separately, then choose **Accept selected**.
- A **Skip lift** row shows the date, the affected lift, and why the coach proposes skipping it. The decision applies only to that lift. Review other sessions on the same date separately.
- Review related calibration anchors with any targets that depend on them.
- For a no-change review, the app records your acknowledgment.
- Opening a proposal or receiving it in chat does not apply it.
- Exception reviews add an **Exception** card: why now, plan impact, sessions left unchanged, the reassess date, and what to watch for. Race reviews add a **Race review** card; block benchmark reviews add a **Benchmark review** card. Settled patches appear under **Patch updates**.

To refine an open draft, continue the same conversation. For example:

> Could we move the long run to Saturday?

Once you agree, the coach updates the same proposal ID and review link, with revision history. Refresh before deciding; review selections reset when a new revision arrives. New check-ins or imports can make a draft stale, so the coach may refresh its evidence before revising. Stale and invalid drafts still count as the one open draft.

Use **Discard proposal** on the review page if you want to abandon that draft and start fresh. Its history remains and the calendar does not change. Accepted, partially accepted, rejected, and discarded proposals are final; a later change needs a new proposal.

## Weekly mileage and the week view

Home's weekly mileage uses Monday–Sunday in your profile timezone. It adds recorded running distance so far to the remaining accepted runs. Time-based sessions use workout speed targets or median observed speed from the previous 28 days and show an estimate. Past unrecorded sessions are not added to the forecast, and pending drafts never affect it.

Missing data and incomplete plan coverage are labeled. Treat the projection as a planning aid, especially where distance is estimated. Use the Calendar arrows to move between weeks. Choose **This week** to return to the current week or **Session details** to read the full prescription and the coach’s notes. Sessions marked provisional are an outlook that may change. Those badges follow the saved proposal, rather than making every next calendar week provisional.

On the Calendar, use **Mark complete** for a workout you did today or earlier without a recording, including a strength session without a Strong import. The **Completed · self-reported** badge counts toward the weekly session total. Actual time, distance, and reps stay unknown. Use **Undo manual completion** to correct the entry. A later matching activity or Strong workout can supply measured details.

Reps are matched to your watch workout in order. Split laps within a step are combined. An unrecorded warm-up, recovery, or cool-down can be skipped. A skipped work rep counts as unrecorded. The comparison is unavailable when equally plausible matches give different counts of completed reps.

On treadmill runs the watch estimates pace and distance from your wrist. Rep paces are shown for reference. The comparison skips pace targets and scores distance only when the session has no planned duration.

## Find your way around

- [Home](#home): sync status, **Needs attention** (open proposals, coach recommendations, findings, patch reassessments, and check-in prompts), weekly mileage and **Planned vs done**, today's plan, this week's sessions, the block line, and **Logged for Sunday review**.
- [Calendar](#calendar): one week at a time, with arrows to browse accepted sessions, workout details and notes, patch and benchmark badges, and **Plan versions** with a link to the proposal behind each coach change. Completed, historical, and locked sessions are protected during undo.
- [Trends](#trends): volume, effort load, long runs, intensity, aerobic efficiency on steady runs, workout progression, recovery, and benchmark history. Panels without enough data wait under **Not yet assessable**.
- [Training block](#block): the current objective, timeline, review indicators, and block benchmark.
- [Settings](#settings): sync, setup or strength routine, display timezone and units, weekly review day, goals, events, and intensity anchors.

Heart-rate drift needs at least 40 minutes of timer-on analysis after the 10-minute warm-up.
That is about 50 minutes of running before allowing for extra time after pauses.

The **Guide** link in the header opens this guide. Lifting stays in Strong; the app reads its export for running context.

If you need to undo an accepted calendar change, inspect Calendar’s **Plan versions** or explicitly ask the coach for an undo. Protected sessions remain protected.

## Occasional calibration and goal changes

A new race result, test, or sustained change in workout execution may justify revisiting intensity anchors. Missing saved anchors alone do not require a test or an easy-only reset. Tell the coach what evidence is new:

> Use $going-bananas-coach to review intensity calibration in real mode using my new test or race evidence: …

For a new goal, race, or substantial scheduling constraint, request the broader review explicitly:

> Use $going-bananas-coach to review this goal or race change in real mode: … Explain its block implications and the plan through the block's review date.

These are occasional reviews rather than extra weekly chores. The coach distinguishes observations, research, and athlete-specific inference; uncertain data stays uncertain.

## Coaching model and research

Use **Astra Medium** as the head coach for personalized decisions and final proposals. Select it in Codex when available; a skill cannot change the model of an existing session. If another model invokes the skill and delegation is supported, it can hand coaching to a fresh Astra Medium agent.

The coach first reuses the verified running research already returned with your training snapshot. For a genuine unanswered research question, it may ask a cheaper helper to retrieve a short source-linked brief. Astra checks decisive claims and retains the coaching decision. Helpers never prescribe or apply a plan. This can reduce head-coach context and cost, but extra agents do not guarantee fewer total tokens.
