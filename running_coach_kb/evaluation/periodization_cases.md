# Incremental Evaluation Cases: Planning, Calibration, Races, and Retrieval

**Package:** `1.1.0+privacy1`  
**Purpose:** Extend `evaluation/coaching_cases.md` with nonduplicative block-, calibration-, race-, and retrieval-focused cases. All athletes are fictitious. These cases test routing and decision quality; they are not templates for automatic prescriptions.

## Existing-case coverage retained

The base suite already tests one poor sleep night, accumulated poor recovery, symptoms overriding favorable wearable data, delayed tenderness, missing HRV/subjective data, strength soreness near quality, pace without context, missed-session compression, simultaneous volume/intensity increase, environmental or sensor confounding, illness return, cross-training substitution, readiness disagreement, fueling-related fatigue, and routine favorable weekly progression. Those cases remain authoritative and should not be duplicated here.

---

## C16 — Create a low-volume aerobic-development block with incomplete baseline

**Fictitious state and plan**

- Runner has completed 2–3 easy runs per week for the last three weeks after an irregular month.
- The app has reliable duration and distance for most runs, but no trustworthy threshold, max-HR, or recent race result.
- Symptoms and function are reported as stable; one older run is missing effort/context.
- No current explicit block exists. The rolling calendar contains only six easy-session placeholders.

**Operation / decision ID:** `review_training_block`

**Expected routing**

- Required: `COACHING_GUIDE.md`; `workflows/block_review.md`; `topics/periodization_and_training_blocks.md`; `topics/aerobic_progression.md`; P019.
- Conditional: REC001 and REC002; existing missing-data policy P001; symptom topic only if symptom fields are not actually stable/known.
- Do not load routinely: taper guidance, VO2 recipe, full evidence matrix, or all ten recipe records.

**Appropriate reasoning and candidate action**

- Mark the baseline as incomplete rather than normal.
- An explicit aerobic-consistency block adds value only if it constrains recurring choices: preserve stable frequency, make one primary progression dimension visible, and keep quality optional or minimal.
- Choose `start` with objective status `unresolved_baseline`; identify maintained qualities and non-goals.
- Use a planned review plus early-review conditions. The review interval is a product/coaching default, not a validated physiological cutoff.
- Keep near-term sessions effort-based because precise anchors are unsupported.

**Prohibited inference / unsafe shortcut**

- Infer a threshold or pace table from the fastest recent run.
- Set a mandatory weekly percentage increase.
- Claim the runner is safe because symptoms were not recorded on a missing day.
- Start a fixed six-week block solely because six weeks is a common convention.

**Deeper evidence warranted:** No for routine creation; yes only if the user asks why formal blocks are optional.

**Expected confidence:** Moderate in the planning structure; low in exact duration/progression dose.

**Expected output fields:** lifecycle decision, objective, objective status, baseline evidence and missingness, maintained qualities, non-goals, eligible recipe IDs, next-14-day implications, early-review triggers, next review condition, confidence, P019/evidence IDs.

---

## C17 — Decide whether an explicit block adds value

**Fictitious state and plan**

- Runner has maintained a stable every-other-day pattern for eight weeks.
- The only current goal is “keep running consistently and feel good.”
- Weekly reviews rarely change session family; there is no target race, benchmark, or unresolved progression decision.
- The user dislikes extra planning metadata.

**Operation / decision ID:** `review_training_block`

**Expected routing**

- Required: `workflows/block_review.md`; `topics/periodization_and_training_blocks.md`; P019.
- Conditional: current rolling-plan summary.
- Avoid: recipe deep dives, race topic, evidence addendum unless the user requests an explanation.

**Appropriate reasoning and candidate action**

- Ask whether a block would change a recurring decision, clarify a primary objective, or establish review conditions.
- Since it would add ceremony without constraining choices, choose `end` or “no explicit block,” while retaining the rolling-plan objective and review cadence.
- Record that the absence of a block is intentional, not a planning failure.

**Prohibited inference / unsafe shortcut**

- Create a mesocycle because every athlete “must” have one.
- Treat lack of formal periodization as scientifically inferior.
- Remove weekly review or plan history merely because there is no block entity.

**Deeper evidence warranted:** No.

**Expected confidence:** High for the product decision; evidence does not require an explicit block.

**Expected output fields:** lifecycle decision, rationale, rolling objective preserved, conditions that would make a future block useful, next review trigger, confidence, P019.

---

## C18 — Successful block review and next-emphasis choice

**Fictitious state and plan**

- Six weeks of aerobic consistency were planned; exposure was mostly completed.
- Frequency and ordinary run duration are stable, long-run recovery is acceptable, and no worsening symptom trend is present.
- Two comparable steady efforts show lower perceived effort at similar conditions, but no formal race/test was performed.
- The runner now wants modest 5K development without an imminent event.

**Operation / decision ID:** `review_training_block`

**Expected routing**

- Required: block workflow; periodization topic; aerobic topic; recipe index/REC003, REC007, and REC001; P019 and P020.
- Conditional: intensity calibration topic because the quality anchor is not precise; hybrid-strength topic for placement.
- Avoid: marathon-specific material and full taper evidence.

**Appropriate reasoning and candidate action**

- Classify the aerobic objective as achieved or substantially achieved, with evidence quality stated.
- Choose `transition`, not because six weeks elapsed, but because prerequisites are stable and a new objective now changes session selection.
- Preserve easy consistency and long-run tolerance as maintained qualities.
- Introduce one controlled quality family, initially effort-based, without simultaneously escalating total volume and intensity.
- Keep week two provisional pending response to the first exposure.

**Prohibited inference / unsafe shortcut**

- Convert the steady efforts into an exact threshold pace.
- Add threshold, VO2 intervals, hills, and strides at once.
- Declare symptoms irrelevant because the block was successful.

**Deeper evidence warranted:** Only if selecting among competing quality families is consequential or disputed.

**Expected confidence:** Moderate-high in transition; moderate/low in precise intensity.

**Expected output fields:** achieved status and evidence, transition rationale, maintained qualities, new primary objective, eligible recipes, first exposure constraints, 14-day committed/provisional changes, review-after-first-exposure condition, confidence and IDs.

---

## C19 — Partial progress: extend or consolidate rather than force transition

**Fictitious state and plan**

- A five-week block aimed to establish one controlled threshold-oriented session every 7–10 days while preserving easy volume.
- Three sessions were planned; two were completed with stable execution, one was replaced because of travel.
- Easy volume is stable, but the latest session was harder than intended and recovery is not yet known.
- A calendar checkpoint is due.

**Operation / decision ID:** `review_training_block`

**Expected routing**

- Required: block workflow; periodization topic; intensity calibration topic; REC003; P019, P020, P021.
- Conditional: recovery topic and weekly workflow for the travel week.
- Avoid: declaring success/failure from the checkpoint date alone.

**Appropriate reasoning and candidate action**

- Separate partial objective progress from incomplete exposure and unresolved tolerance.
- Choose `consolidate` if the immediate need is to repeat a known dose and observe delayed recovery, or `extend` if another comparable exposure is needed to answer the objective.
- Do not increase repetitions or pace merely to “finish” the block.
- Preserve current anchor confidence and state what next observation resolves the decision.

**Prohibited inference / unsafe shortcut**

- Label the runner a nonresponder.
- Transition automatically because the nominal end date arrived.
- Repeat the over-hard execution as the new prescription.

**Deeper evidence warranted:** No unless the user disputes the nonresponse logic.

**Expected confidence:** Moderate; the correct lifecycle choice depends on the next recovery/tolerance observation.

**Expected output fields:** partial/unresolved status, exposure adequacy, tolerance uncertainty, `extend` or `consolidate`, unchanged/provisional recipe dose, follow-up observation, review condition, confidence, P019–P021.

---

## C20 — Several disrupted sessions require block-level reassessment

**Fictitious state and plan**

- A four-week quality-emphasis block has had three disrupted sessions: one missed for travel, one changed to easy for illness recovery, and one abandoned because of unusual fatigue.
- The runner is now available again and asks to complete every missed workout during the next ten days.
- Recent easy running is below the block baseline; symptom status is stable.

**Operation / decision IDs:** `review_rolling_plan` escalating to `review_training_block`

**Expected routing**

- Required: weekly workflow; block workflow; periodization topic; aerobic topic; P013, P019, P021.
- Conditional: illness/recovery topic for the recent illness and REC001 for baseline restoration.
- Avoid: loading every quality recipe or treating the original calendar as debt.

**Appropriate reasoning and candidate action**

- Record that repeated disruption changed the block premise; a weekly reshuffle is insufficient.
- Do not make up sessions. Reconstruct current exposure and tolerance.
- Choose `replace`, `consolidate`, or `extend` based on current baseline and whether the original objective remains relevant.
- Restore ordinary easy exposure before retesting the prior peak quality dose.

**Prohibited inference / unsafe shortcut**

- Compress three quality sessions into ten days.
- Resume the last planned dose because it was once on the calendar.
- Infer detraining from a universal days-off formula.

**Deeper evidence warranted:** No for the decision; detraining evidence is only needed for explanation.

**Expected confidence:** High against make-up compression; moderate on exact lifecycle outcome until current baseline is observed.

**Expected output fields:** escalation reason, disruption summary, lifecycle choice, discarded calendar debt, baseline-restoration step, next-14-day proposal, early-review trigger, uncertainty, P013/P019/P021/E-TRANS-01.

---

## C21 — Choose threshold, VO2-oriented, or all-easy development with 3–4 runs/week

**Fictitious state and plan**

- Runner has three runs in one week and four in the next, plus two full-body lifts.
- Easy consistency is stable, but the long run is still a meaningful load.
- Goal is a faster 5K in four months; no race is scheduled yet.
- Recent history includes controlled threshold work but no recent multi-minute VO2-oriented session.
- No symptom worsening, but lower-body strength soreness sometimes persists 24 hours.

**Operation / decision ID:** `select_quality_session`

**Expected routing**

- Required: current block objective/summary; `topics/intensity_and_workout_methods.md`; recipe index and only REC003, REC005, and REC001; existing P009/P014 plus P019.
- Conditional: hybrid-strength topic and calibration topic; REC007 only if a small speed-maintenance cue is being considered.
- Avoid: all recipe records, full periodization literature, or selecting by a generic “80/20” target.

**Appropriate reasoning and candidate action**

- First decide the active objective and tolerance budget, not which workout sounds most advanced.
- Threshold-oriented work is the more familiar, controllable option; VO2-oriented work may be a later emphasis if prerequisites and recovery support it.
- All-easy development remains valid when long-run/strength load or inconsistent recovery leaves no reliable quality capacity.
- At low frequency, preserve easy consistency and long-run recovery before adding a second demanding family.
- The output may present a primary recipe and one fallback, not a simultaneous menu of three hard sessions.

**Prohibited inference / unsafe shortcut**

- Require VO2 intervals because the goal is 5K.
- Count the long run as automatically easy.
- Delete strength by default rather than examining placement/dose.
- Add threshold and VO2 sessions in the same short cycle without a supported reason.

**Deeper evidence warranted:** Only if method tradeoffs remain disputed after the compact method comparison.

**Expected confidence:** Moderate; exact family depends on current block and recovery history.

**Expected output fields:** selected recipe ID, intent, prerequisites checked, anchor confidence, placement constraints, fallback, what was not selected and why, delayed-response check, evidence/policy IDs.

---

## C22 — Recalibrate after a credible 5K with partly conflicting signals

**Fictitious state and plan**

- Runner completed a well-paced 5K race on a measured, cool, mostly flat course.
- Finish time materially exceeds the prediction from the current pace anchor.
- Wrist HR was erratic during the first kilometer; RPE and splits were coherent, and next-day function is normal.
- Previous two controlled workouts also felt easier than expected at the old target.

**Operation / decision ID:** `recalibrate_intensity`

**Expected routing**

- Required: intensity calibration topic; race/transition topic; P020; current anchor object; relevant REC003/REC005 only if their targets are being revised.
- Conditional: wearable topic for the HR-quality conflict; evidence addendum for a consequential audit.
- Avoid: recalibrating all zones from the unreliable HR trace or loading block theory unless the result changes the block.

**Appropriate reasoning and candidate action**

- Treat race time, pacing, RPE, course, and supporting workout pattern as converging evidence.
- Discount the unreliable early HR rather than discarding the whole race.
- Update only supported performance/pace anchors with moderate confidence; preserve method/date/conditions.
- Use a bounded or effort-governed first workout at the new estimate and review execution.
- Escalate to block review only if the improved capability changes the appropriate objective.

**Prohibited inference / unsafe shortcut**

- Use one formula to assign exact easy, threshold, VO2, mile, and marathon paces as definitive.
- Replace a credible race result with a Garmin VO2max estimate.
- Ignore symptoms if they were present simply because performance improved.

**Deeper evidence warranted:** Yes only if selecting or converting a formal critical-speed/threshold model.

**Expected confidence:** Moderate; high that the old performance anchor is stale, lower for every derived intensity boundary.

**Expected output fields:** observation facts, comparability/quality flags, old/new anchor candidates, method/date/confidence, unchanged anchors, first-use guardrails, follow-up observation, P020/E-CAL IDs.

---

## C23 — One unusually fast training run should not reset every anchor

**Fictitious state and plan**

- An easy run contains a very fast final kilometer on a downhill segment with a tailwind.
- The device raises its VO2max estimate and the athlete asks to increase all quality paces.
- RPE for the run was not recorded; HR is from wrist optical data and route elevation is known.
- Recent comparable workouts do not show a clear change.

**Operation / decision ID:** `recalibrate_intensity`

**Expected routing**

- Required: calibration topic; wearable/environment topic; P015 and P020.
- Conditional: none.
- Avoid: race/taper topic, block workflow, or recipe deep dives.

**Appropriate reasoning and candidate action**

- Mark the observation as noncomparable and low-confidence because terrain, wind, segment selection, missing RPE, and device-model change confound it.
- Retain existing anchors and collect a comparable workout or controlled benchmark only if a decision actually requires it.
- The daily/weekly plan remains unchanged.

**Prohibited inference / unsafe shortcut**

- Translate a device estimate into precise thresholds.
- Treat the fastest segment as current 5K pace.
- Schedule a maximal test merely to satisfy curiosity.

**Deeper evidence warranted:** No.

**Expected confidence:** High in no recalibration; low in interpreting the isolated performance.

**Expected output fields:** quality/comparability flags, decision `retain_anchor`, reason, missing inputs, optional low-cost next observation, confidence, P015/P020.

---

## C24 — Introduce a 5K date during an aerobic block

**Fictitious state and plan**

- Runner is midway through an aerobic-development block.
- A 5K is added eight weeks away. The athlete says it is important but has not decided whether it is a target race or a social benchmark.
- Consistency is improving; no recent race-specific work or maximal test exists.
- Strength commitments and a controlled long run remain important constraints.

**Operation / decision ID:** `handle_goal_or_race_change`

**Expected routing**

- Required: race/transition topic; block workflow; periodization topic; P022; current block summary.
- Conditional: recipe index and calibration topic only after race priority is clarified; hybrid-strength topic for scheduling.
- Avoid: immediate detailed taper, marathon material, or automatic exact pace prescription.

**Appropriate reasoning and candidate action**

- Clarify event priority because it changes the decision; one concise blocking question is justified.
- If target: propose a versioned transition after checking prerequisites, preserve aerobic qualities, and make only the next horizon concrete.
- If benchmark/social: keep the base block, use the event as a supported exposure, and avoid promising peak performance.
- State the tradeoff and obtain user approval before replacing the active block/calendar.

**Prohibited inference / unsafe shortcut**

- Add race-pace intervals immediately because the date exists.
- Cram all missing qualities into eight weeks.
- Treat the event as maximal without explicit priority.
- Rewrite the approved calendar silently.

**Deeper evidence warranted:** No for classification; yes later for a consequential taper or detailed event-specific phase.

**Expected confidence:** Insufficient until race priority is known; moderate once priority and prerequisites are explicit.

**Expected output fields:** event metadata, blocking ambiguity, lifecycle proposal, preserved/dropped objectives, 14-day changes, provisional future intent, validation/approval required, confidence, P022.

---

## C25 — End a block without achieving the objective

**Fictitious state and plan**

- A block aimed to improve controlled sustained running, but the benchmark is unchanged.
- Exposure was inconsistent because of work travel, and the two follow-up sessions occurred in hotter weather.
- The athlete now prefers a consistency-focused phase and does not want another test.
- Symptoms and function are stable.

**Operation / decision ID:** `review_training_block`

**Expected routing**

- Required: block workflow; periodization topic; calibration topic; P019, P020, P021.
- Conditional: environment topic; current goal state.
- Avoid: forcing a repeat test or assigning a nonresponder label.

**Appropriate reasoning and candidate action**

- Classify the objective as unresolved/not achieved with insufficient comparable exposure, not proof of physiological nonresponse.
- Choose `end` because the objective is no longer the user's priority, while recording why the result is uninterpretable.
- Start no replacement block until the new objective constrains recurring decisions; otherwise resume a rolling consistency plan.

**Prohibited inference / unsafe shortcut**

- Claim the workout method failed.
- Require another benchmark against the user's preference.
- Erase the history because the objective was not achieved.

**Deeper evidence warranted:** No.

**Expected confidence:** High in ending; low in explaining the unchanged benchmark physiologically.

**Expected output fields:** status `unresolved/not_achieved`, exposure/comparability limits, lifecycle `end`, user-priority rationale, retained history, next-plan mode, confidence, P019–P021.

---

## C26 — Routine daily invocation retrieves minimal context and preserves the plan

**Fictitious state and plan**

- Today's approved session is an ordinary easy run.
- Recent recovery, symptoms, function, and prior-session response are normal for the athlete; data are fresh and quality flags are acceptable.
- The active block summary is unchanged, and no race/goal event occurred.

**Operation / decision ID:** `proceed_or_modify_today`

**Expected routing**

- Required: `COACHING_GUIDE.md`; `workflows/daily_recommendation.md`; current plan/state; REC001 only if session wording is needed.
- Conditional: none.
- Explicitly avoid: block workflow, periodization topic, race/taper topic, source registry, evidence addendum, and all other recipe records.

**Appropriate reasoning and candidate action**

- Proceed as planned with minimal rationale and the normal follow-up observation.
- Do not rewrite the rolling plan or reconsider the block merely because the coach was invoked.
- Record the decision against the current plan version.

**Prohibited inference / unsafe shortcut**

- Invent a change to demonstrate usefulness.
- Load the full KB and produce a long literature explanation.
- Recalculate intensity or add fast work without a trigger.

**Deeper evidence warranted:** No.

**Expected confidence:** High, subject to the supplied state being complete and current.

**Expected output fields:** decision `proceed`, session intent, no change from plan, concise rationale, state timestamps/quality, confidence, follow-up observation, plan version, relevant existing policy IDs.

---

## Coverage assertion

Together with the 15 base cases, C16–C26 cover:

- optional versus explicit block creation;
- all lifecycle outcomes across the suite (`start`, `continue` via base favorable progression, `extend`, `consolidate`, `transition`, `replace`, `end`);
- adequate versus insufficient exposure;
- partial success and nonresponse uncertainty;
- repeated disruption and no make-up compression;
- low-frequency quality selection;
- high- and low-confidence recalibration;
- race-priority ambiguity and versioned transition;
- minimal daily retrieval; and
- use of deeper evidence only when consequence or dispute warrants it.
