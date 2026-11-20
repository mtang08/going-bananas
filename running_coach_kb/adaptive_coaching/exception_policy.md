# Exception Policy: Findings, Minimal Patches, and Return to Plan

**Status:** reviewable candidate guidance for package 1.2.0+privacy1; not an activated rule or medical instruction.

**Retrieve for:** `exception_review` (sections 1–6) and `post_event_review` (Escalation and medical scope).

The application's deterministic detector creates findings with category, severity, evidence, and status. The coach never decides whether a finding exists, only the smallest useful response. Named thresholds belong to the app rule set `exceptions.v1`. (product heuristic)

## Categories and severity

- `symptoms_illness`: symptom reports, gait change, illness, and clinician restriction. (product heuristic)
- `training_response`: RPE above the intended session class or failed quality sessions. (product heuristic)
- `accumulated_fatigue`: repeated high fatigue or converging signals. (product heuristic)
- `calendar_disruption`: missed key sessions, adjacent demanding sessions, travel, and `BLOCK_BENCHMARK_MISSED`. (product heuristic)
- `post_event` marks a due race review (`POST_EVENT_REVIEW_DUE`) or block-benchmark step (`BLOCK_BENCHMARK_COMPLETED`); it is not a problem category. (product heuristic)
- `observe`: log it for the Sunday review; no plan change is needed. (coaching convention)
- `caution`: patch the next affected session or sessions. (coaching convention)
- `hold`: hold demanding work for the patch window, up to the committed window. (coaching convention)
- `escalate`: narrower layers cannot keep the plan coherent; route to a block review, or say outside evaluation may be needed. (coaching convention)
- Severity comes from the app's rule table, never from a composite or readiness score. (product heuristic)

Severity `escalate` is a finding severity. It is not the proposal field `escalation`, which routes to another operation, and it is not the P018 recommendation to seek clinical input; record each separately. See `COACHING_GUIDE.md` §2, Decision authority by layer. (product heuristic)

## Evidence requirements

- No single raw RPE, HRV, resting-HR, sleep, or pace value raises a finding above `observe`; see `topics/recovery_and_daily_adaptation.md` › Takeaways first, item 2, and P002. (product heuristic)
- RPE is a usable report of perceived exercise intensity. (research: E-DATA-01)
- Judge its mismatch against the intended session class (easy, long, quality), not an absolute number: one mismatch is an observation; repetition within the committed window or agreement with fatigue, illness, poor sleep, travel, or adverse recovery nights raises concern. (inference)
- Heat, hills, travel, and sensor or recall problems are confounders, not reasons to dismiss repetition; see P015. (research: E-DATA-02)
- Recovery metrics count only as one converging signal and never create a finding alone; see `topics/recovery_and_daily_adaptation.md` › HRV › Operational use. (research: E-REC-04)
- For symptom/function priority, see `COACHING_GUIDE.md` §3, item 3, and P005.
- When the athlete has a prior posterior-tibial-region issue, a new or persisting medial-ankle report deserves earlier caution. (inference)
- No numeric pain threshold is active: thresholds stay `null`; see `topics/ptt_and_load_tolerance.md` › Pain-monitoring models. (product heuristic)
- For missing data as unknown rather than normal, see `COACHING_GUIDE.md` §7, Missing data and uncertainty.

- For checks against overreaction, see `topics/recovery_and_daily_adaptation.md` › Overreaction failure modes.

## Minimal-change ladder

- Choose the lowest useful level: current session → next session → next days (at most 3) → committed window (days 1–7) → block, reached only through `escalation: review_training_block`. (coaching convention)
- Day labels are ordinal: committed days 1–7 map to internal offsets `today+0…+6`; provisional days (day 8 onward) map to `today+7` and later. Window arithmetic uses these offsets. (product heuristic)
- Typical mapping: `observe` → no change or current session only; `caution` → current session, next session, or next days, at most 3 days; `hold` → next days or committed window, at most 7 days; `escalate` → block via `escalation`, with protective changes only inside the committed window. (coaching convention)
- For how to modify, see `topics/recovery_and_daily_adaptation.md` › Modify and `workflows/daily_recommendation.md` › Step 5: Choose the smallest effective action.
- Never edit provisional days (day 8 onward); the next weekly review owns them. (product heuristic)
- List committed sessions deliberately left unchanged, each with a reason. (product heuristic)
- In an exception review, do not add sessions, change run frequency, or move, add, or delete strength sessions. (coaching convention)
- Every accepted patch records a patch window, a reassess date within 7 days, what to monitor, return-to-plan criteria, and escalation criteria. (product heuristic)
- Repeated related exceptions can change the committed window; they never change the block silently. (coaching convention)
- For planning-layer authority, see `workflows/block_review.md` › Planning-layer authority.

## Return to plan

- Do not restore a removed hard session because one metric returned to normal. Return when the patch's own return criteria are met. Examples include symptoms and function stable through the delayed window after an easy exposure (see `topics/ptt_and_load_tolerance.md` › Return-to-running and progression), staged illness return per P004, fatigue at the athlete's usual level on more than one day, and easy-run RPE back inside its expected range. (coaching convention)
- Findings close only through a decision: coach resolution, review acceptance, or athlete dismissal or resolution. Stale `observe` findings may also expire; a changed observation alone is not a resolution decision. (product heuristic)
- Restore one demanding exposure first; never compress removed work. See P013 and `COACHING_GUIDE.md` §3, item 5. (coaching convention)
- At reassessment, resolve the patch if its return criteria are met, open a new narrow patch if partly met, or escalate if escalation criteria are met. A weekly review may resolve patches whose window has passed. Record which criteria support the decision so the next review can follow it. (coaching convention)

- For return after disruption, see `topics/races_tapers_and_transitions.md` › Interruption and return to a block.

## Escalation and medical scope

- Escalate to `review_training_block` via `escalation` when the same category recurs in both halves of the last 14 days, a patch meets its escalation criteria, or another patch would change the committed window again. See `COACHING_GUIDE.md` §2, Decision authority by layer. This is a review-routing decision, not permission to rewrite the block inside an exception proposal. (coaching convention)
- Clinical input follows P018 and `topics/ptt_and_load_tolerance.md` › When self-directed adjustment is insufficient. The app cannot diagnose; recommend an appropriate clinician and preserve only clearly tolerated activity. For prolonged or systemic illness, follow P004. (clinical guidance)
- A clinician restriction is an `escalate` finding. Honour it; do not plan around it. Current clinician instructions outrank this package. (clinical guidance)
- For an `escalate` finding in `symptoms_illness`, say that outside evaluation may be needed. Keep that clinical recommendation distinct from the proposal's route to a block review. (clinical guidance)
- For the boundary between daily and block authority, see `workflows/block_review.md` › Planning-layer authority.

## Missed sessions and spacing

- For missed work as non-debt, see P013 and `COACHING_GUIDE.md` §3, item 5. Never stack sessions to make up a missed key session. (coaching convention)
- After one missed key session, usually let it go. An exception review may move it inside the committed window only if spacing and the strength schedule stay intact and no demanding sessions become adjacent. Otherwise the weekly review decides. (coaching convention)
- When two demanding sessions (quality, long, benchmark) fall on adjacent days, separate them or downgrade one. Prefer to protect the long run or the block's key session. (coaching convention)
- During travel, keep frequency where practical, shorten or move easy runs, and avoid novel hard work in unfamiliar conditions. Keep the exception response within its existing session and strength constraints. (coaching convention)
- Repeated missed runs suggest the plan is unrealistic; leave that to the weekly review, using the P013 review trigger. (inference)

## Worked examples

**One hard-feeling easy run.** The app reports `RPE_ABOVE_INTENT`, `training_response`, `observe`: one easy run at RPE 6 in reported heat, without another signal. (product heuristic)
Use the current-session ladder level with no change; keep the planned next session and ask for RPE on the next easy run. Reassess at that run, within 7 days. (coaching convention)
Return criteria mean continued ordinary easy response, not a requirement to earn back a removed session; none was removed. Repetition or converging fatigue warrants a fresh review of app findings rather than raising severity by hand. (inference)

**Repeated mismatch with fatigue.** Two easy runs above intent plus fatigue at or above 7 on two days support the app's `caution` findings. (product heuristic)
Use `next_session`: replace the next quality session with an easy run, leave other committed sessions explicitly unchanged, and reassess in 3 days. (coaching convention)
Return when easy RPE is back in range on two runs and the patch's fatigue criteria are met. Escalate if its escalation criteria are met or another patch would again change the committed window. (inference)

**Delayed medial-ankle report.** For an athlete with a prior posterior-tibial-region issue, next-morning tenderness after a quality run prompts a `caution` response, or `hold` if walking is affected, using the app's findings. (inference)
Use `next_days`: easy or low-impact sessions, monitor walking and delayed response, and reassess in 3 days. Return only after the patch's symptom/function criteria are met through the delayed observation window. (coaching convention)
If worsening or gait changes occur, seek clinical input per P018; record that separately from any `escalation` to block review. (clinical guidance)
