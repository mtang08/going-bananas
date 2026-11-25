# Implementation plan for the running feedback loop

This plan follows the November 24 discovery. The first delivery connects Today, workout response and Sunday review. The acceptance test is whether the athlete can answer the questions below from a normal entry point.

| Athlete's question | Work in this delivery | Verification |
| --- | --- | --- |
| What am I doing today and what do I need to report? | Prioritize the accepted session on Home, provide a feedback action from its recording, and persist explicitly reported pain or its absence. Keep legacy uncertainty. | Synthetic known, unknown, missing and corrected responses. Inspect the Today and recorded-run paths. |
| What limits are in force? | Allow the athlete to maintain a dated restriction in Settings. Carry the wording and applicable dose limits through coach context, proposal validation, accepted subsets and direct calendar edits. | Paired compliant/conflicting plans across units and dates, protected history, revised restrictions and unchanged legacy facts. |
| Did the change we agreed to work? | Show a representative accepted run change alongside its actual execution, effort, delayed response and the next review question. Use the same data for the weekly digest and coach. Bound research/context size and preserve decision freshness. | Partial acceptance, later plan edit, missing report, independent actuals, current configuration, and synthetic packet-size comparison. |
| How can rehab fit alongside the rest? | Extend dated slots, review and manual completion with independently tracked rehab and a 15-minute total daily budget. | Same-day run, lift and rehab combinations. Independent completion and separate weekly counts. |

## Two higher-level UX changes in this delivery

**“What happens if I move Thursday’s run?”** The pending proposal now previews two Monday–Sunday weeks from the first dated proposed change. The selected subset drives the per-week changes in running time and distance, using explicit totals or a structure entirely in one unit. Mixed or missing doses are identified. A move shows its old and new dates and the nearest identifiable demanding session within three days when available. Changes outside the preview are labeled. The athlete can decide whether to accept the tradeoff before writing to the calendar. [Proposal preview](../../../frontend/src/pages/proposal/ScheduleImpact.tsx)

**“Am I progressing toward my goal?”** The existing Block page brings the accepted objective and its dated assessment together with the latest dated benchmark, what was measured, the comparison entered by the athlete, the indicators the athlete agreed to review, and the next check. A finish-time prediction or inferred threshold would require additional evidence. This release surfaces the coach’s recorded judgment and the facts a future review can compare. [Block page](../../../frontend/src/pages/Block.tsx)

## Operating scope and acceptance

A delayed answer describes the athlete at the recorded observation time. The Sunday comparison selects one due run per week from a change that was actually applied. Within the newest decision it prioritizes an adjustment, then a key workout, then the most recent eligible date. The accepted revision supplies the original dose even after a later edit. A missing recording or a missing answer stays visible. The next-check text belongs to the overall proposal. The same evidence is present in the weekly and block coach packets. The live digest can reflect a later correction. Use the saved packet to reconstruct what the coach actually saw. No additional model call is needed.

The coach now routes relevant adverse nightly readings to recovery guidance and fingerprints the active metric method and configuration. The routine packet sends an exactly duplicated verified JSON recipe once. In a synthetic one-recipe example the rolling payload plus excerpts fell from 72,590 to 68,341 bytes and the daily example from 45,600 to 41,351 bytes. The corresponding rolling character-based estimate fell from 18,124 to 17,062 proxy tokens. Some seeded weekly and block reviews still exceed their advisory KB budgets. Actual model billing and the effect on coaching choices are still unmeasured.

**Next candidate — “I lost a week. Where do I restart?”** Give the athlete one place to confirm unavailable dates, the first feasible run and whether a restriction needs review. A return proposal should protect commitments, show what to drop and avoid creating missed-workout debt. Validate a time-limited busy week and a restriction with an uncertain end against the existing exception, trip and rolling-plan paths before building a new workflow. Keep model policy, exercise libraries, an independent lifestyle scheduler and automated race forecasts outside this delivery.

**A smaller alternative for a recurring time crunch.** If the athlete repeatedly asks “what can I do in 25 minutes today?”, let the coach attach one approved short version to the important workout. Today would show its minimum useful dose and purpose, and the weekly record would preserve which version was executed. First count how often this happens during the acceptance trial. Existing session briefs and conversational changes may already solve it with less upkeep.

Use four ordinary Sunday reviews and a block transition to decide whether another feature is justified. Record whether the athlete finds the workout, can explain an accepted change from its evidence, and can return after a disruption. The [maturity roadmap](roadmap.md) and [evaluation plan](evaluation.md) set out that trial.

## Verification and operations

The disposable PostgreSQL integration suite passed 312 cases. Two additional downgrade tests verified that explicit pain answers and rehab history survive a refused downgrade. All 28 stock browser scenarios passed on a fresh native demo, including selected proposal acceptance and subsequent snapshot retrieval. Separate browser journeys recorded a delayed no-pain response from Home and completed a 15-minute rehab session independently. These checks establish software behavior. They cannot establish that a particular change improved training.

During browser setup a runner loaded the configured real connection over an explicit test target and an upgrade command reached the live database before the intended backup. The subsequent read-only check found revision `0027_rehab_sessions`. The previous live revision was not captured. The two new upgrades add a nullable field and widen a calendar constraint. The launchers now preserve a complete explicit destination, reject conflicting partial overrides and keep nested same-mode test commands on the selected database and private directory. A sandboxed shell regression covers both routes.
