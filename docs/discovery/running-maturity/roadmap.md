# Incremental roadmap to a maintainable running coach

Recommendation dated 2026-11-24. Start with the checkout and observed baseline described in [current state](current-state.md) and [saved review evidence](data.md#what-the-saved-reviews-demonstrate). The owner has already built a usable calendar authority, training metrics and review workflow. The next investment should make one accepted prescription, its outcome and the following decision dependable.

The levels describe capabilities. Ship the small rehab scheduling iteration as soon as its core dependencies are available, ahead of optional analytics. Begin regression checks and cost measurement in the first iteration and only expand the evaluation machinery when the evidence warrants it. Each slice can be accepted on its own. Candidate numbers refer to the [feature inventory](opportunities.md).

## Level 1 — Reliable core experience

### A. Close one workout's feedback loop (candidate 1, first checks from 10)

**Objective and benefit.** An athlete can see today's accepted run and its purpose, execute it, reconcile the recording, and answer a relevant follow-up once. The following Sunday can distinguish known tolerance from silence. This is the first build.

**Scope and dependencies.** Start from Home, Activity/Calendar, existing session IDs, wearable RPE, prompt generation, check-in persistence and coach snapshots. Move the accepted prescription and unresolved action into focus. Correct the past “moved” wording and expose the matching action. Preserve pain answered/no/unknown across the API, UI, digest and snapshot. Keep existing ambiguous history unknown. Use the existing reminder windows and low-touch exception preference. Baseline manual interventions and review size from current evidence before making changes.

**Done and validation.** A synthetic accepted long run imports from Garmin, gets exactly one completion, uses its watch effort, and a delayed response appears with the correct timing in the next review. Exercise the same flow with explicit absence, an unanswered prompt, late arrival, a moved activity and a partial save/retry. A self-reported completion never acquires invented distance. On the next naturally occurring eligible run, the athlete can complete or intentionally skip the feedback step and explain what the next review sees. An unsolicited symptom survey is unnecessary.

**Deferred.** Phone hosting, notifications, new workout scores, general chat and automated scheduling.

### B. Make material constraints and evidence consistent (candidates 2 and 5)

**Objective and benefit.** The runner can trust a reviewed change to respect explicit restrictions and the evidence available at acceptance.

**Scope and dependencies.** Build on versioned athlete facts, scoped proposal validation and selected-subset acceptance. Cover the units and dates of confirmed restrictions the athlete needs. Include structure changes that materially alter dose and visibility on direct edits. Reconcile recovery-topic selection with the actual nightly result shape, and extend proposal freshness to decision-relevant metric configuration. These seams were identified in code. The right handling for an ambiguous clinical instruction remains an owner/clinician decision. [Observed restriction and routing cases](coaching.md#what-the-coach-actually-sees-during-adaptation)

**Done and validation.** A compatible proposal passes both submission and acceptance. An explicit dated limit remains effective through its intended interval across equivalent changes in distance, duration or workout structure. Changed evidence requires a fresh review of the same draft. An expired review date calls for confirmation when the restriction's end is unknown. Paired fixtures differentiate isolated wearable change, poor-quality measurement and a converging trend. Inspect the excerpts and the recommendation separately. Preserve explicit manual acceptance.

**Deferred.** Diagnosis, rehabilitation protocols generated from symptom scores, interpretation of arbitrary clinical prose and universal readiness gates.

## Level 2 — Effective personalized coaching

### C. Start Sunday with the outcome of the last meaningful decision (candidate 3)

**Objective and benefit.** The review can answer whether to repeat, progress or change direction without asking the athlete to reconstruct last week.

**Scope and dependencies.** Use A's response semantics, existing proposal revisions/next checks, exception patches, calendar differences and the weekly digest. Project one due decision with the accepted reason, intended response, actual dose, response evidence, alternatives or confounds, and what remains unknown. Save only the confirmed facts required for the next review. Use a previous commitment for comparison where midweek edits changed the interpretation. Add one optional correction for a durable preference if the same question keeps recurring.

**Done and validation.** In a fresh chat, reconstruct a partially accepted change and a subsequent modification. Correctly identify what happened after the accepted dose and what the data cannot establish. A no-change week can be acknowledged briefly. Two successive ordinary reviews should each explain a next action or an evidence-based decision to continue without the athlete retelling the prior plan. Blind-review synthetic examples before changing the coach's instructions.

**Deferred.** Full chat storage, medical free-text mining, a permanent archive of weekly prose, a generic memory system and a mandatory “why did you deviate?” prompt.

### D. Reduce review context and make access costs visible (candidate 5)

**Objective and benefit.** The athlete can keep using the plan when inference is unavailable and buy personalized reasoning only when it helps.

**Scope and dependencies.** Use C's review summary plus existing bounded drill-downs and verified KB route. Measure ordinary, block and exception reviews independently. Replace the full rolling package for a routing-only decision with the required summary if measurement confirms the duplication. Return provenance, enough exceptions to make a safe decision, and explicit overflow/lookup paths. Measure section sizes, real usage where available, whole-review latency and retry counts. Maintain the existing model policy until a candidate passes evaluation.

**Done and validation.** Same-input comparison preserves safety, restrictions, accepted revisions, relevant exceptions and recommendation quality with a smaller measured packet. An ordinary unchanged day invokes no model. With model access unavailable, Today, accepted sessions, manual edits, the local digest and stored decisions remain usable. Compare at least one ordinary and one difficult synthetic decision on any cheaper route before offering it, then check actual monthly access cost against the owner's ceiling.

**Deferred.** A model marketplace, always-on agent, vector database, multi-agent daily reviews and an inference provider migration without a cost or availability problem.

## Level 3 — Comprehensive athletic development, bounded to running

### E. Put the existing rehab routine on the calendar (candidate 4)

**Objective and benefit.** Rehab can coexist with a run or lift, has its own completion record, and is considered in the next running decision. Pull this forward immediately after A and the relevant restriction handling in B. C and D can ship independently of it.

**Scope and dependencies.** Extend the existing dated session/slot, proposal, digest and outcome types with a distinct, independently tracked rehab routine. Use the owner's 15-minute daily total, proposed weekly frequency and known restrictions. Start with an athlete/clinician-owned routine reference. Capture a relevant function measure only after its owner defines its meaning. The weekly decision sets scheduling, with a stated reason for changes.

**Done and validation.** One day can contain a run or lift plus rehab. Completing either leaves the other open, run volume remains exact, and the next review sees prescribed days, completed days and missing response. A daily schedule can validate within the limit, and two entries that jointly exceed the daily budget are caught. Check partial acceptance and older weeks. Demonstrate one weekly revision with no new clinical prescription.

**Deferred.** Exercise library, diagnosis, automatic progression or clearance, a strength KB, and designing a HYROX station program.

### F. Make interruptions and hybrid weeks practical (candidates 6 and 8)

**Objective and benefit.** A temporary loss of availability changes the next feasible week while preserving the normal rhythm and the priority run.

**Scope and dependencies.** Reuse trips, confirmed lifting cost/slots, actuals, exception patches and the last reviewed response from C. Begin with temporary available/reduced/unavailable days and an explicit return/review condition. Put a dated choice to shorten, move, substitute or omit in the existing review. Add another time-window field only if a real placement decision requires it. Show Strong coverage and a significant nearby lower-body exposure.

**Done and validation.** Replay a missed quality run with incomplete import, a confirmed travel week with limited gym access, and an illness interruption with an uncertain return. The coach verifies unknowns, preserves accepted commitments, avoids catch-up compression and identifies the first review of the return. An unconfirmed Strong session stays unknown. If current travel and exception features already solve the owner's cases, close the iteration on that evidence.

**Deferred.** A general availability solver, trip-aware date migration, Google workout write-back, exercise-level strength prescriptions and two-way sync.

### G. Show credible progress across a block (candidates 7 and 9, conditional)

**Objective and benefit.** The runner can decide whether a block worked and whether to consolidate, change emphasis or revise an anchor.

**Scope and dependencies.** Select one indicator from the existing block objective. Show a bounded comparison of like-for-like runs and competing goals. Use suitable steady-run trends, key reps or a credible protocol-matched benchmark as appropriate. Use quality flags and return a reason when the comparison is indeterminate. Where a race warrants a taper, show the race priority, pre-race load/availability, reduced workload and what to retain for athlete review. Store the expected indicator and review date.

**Done and validation.** A base block can be evaluated without a race. Matched repeats can justify consolidation despite a faster best rep. A secondary race need not displace a primary build. A missed benchmark or mismatched course/effort cannot reset anchors automatically. Use a prior comparison withheld from calibration when assessing prediction error. If volume, coverage and existing block history already answer the question, stop before adding estimation.

**Deferred.** Continuous race-time forecasts, lactate/VO₂ estimates from easy runs, course simulation, rigid weekly progression rules and automatic tapers by distance alone.

## Level 4 — Coaching refinement and operational maturity

### H. Prove the app is inexpensive to keep and safe to recover (candidate 10)

**Objective and benefit.** The owner can assess a change in coaching behavior and recover the running history without an engineering project.

**Scope and dependencies.** Use the early scenario checks, immutable review records, local backups, existing restore verification and sync status. Run a small synthetic comparison only on material changes to the skill, model, KB or rules. Watch dataset freshness, prompts that require attention, failed imports, snapshot growth and total review cost over ordinary use. Reuse the existing launchd/worker and backup process.

**Done and validation.** Run the six core cases in the [evaluation plan](evaluation.md#scenario-set-for-comparing-changes), resolve decision-changing regressions, and document a dry restore into a separate target including raw checksums, accepted sessions and feedback. Demonstrate degraded use through provider unavailability or credential renewal, then duplicate-free replay. A backup on the same disk does not establish recovery after disk loss. Choose and test a private independent copy if that recovery goal matters. Check usability and budget on the stop criteria below.

**Deferred.** Hosted infrastructure, continuous LLM evaluation, an observability platform, a second deployment or broader operating system.

## A reasonable point to stop

Proposed owner acceptance trial, **four consecutive ordinary Sunday reviews and one block transition**, with synthetic interruption/restriction cases when life does not supply them. Start counting after the relevant fixes ship. Extend the observation period only if a material decision remains unevaluated.

- Every scheduled run in the sample has a findable accepted purpose/dose or an explicit rest/unplanned/unknown status. The athlete can follow it if a provider or model is briefly unavailable.
- On each review the athlete can answer what changed, why, what actually happened and what evidence is missing. Sample one meaningful change from decision to follow-up in a fresh chat. No unreviewed plan edits, loss of protected history or contradictions of an explicit restriction in the exercised cases.
- Relevant rehab can be scheduled within the agreed budget and tracked separately. Required strength remains coordinated with running. The athlete finds the manual steps acceptable on the device they actually use, and unknown outcomes are visible.
- Evidence of aerobic, performance or consistency progress is intelligible at block review, including a defensible “insufficient evidence.” Actual training improvement is desirable but cannot serve as a software acceptance test.
- Routine daily readings cost zero model calls. Normal coaching fits the owner's agreed time and incremental monetary ceiling without a subscription purchased solely to keep the app useful. One successful private restore and an on-demand behavioral comparison are repeatable.

If these hold and the owner can name no repeated decision the app fails to support, enter maintenance. Maintain imports, backups, dependencies and research that changes an actual decision. Resume feature development for a recurring failure, a new running goal the current process cannot serve, or loss of a required integration. Numerical race estimates, mobile access, general scheduling and new sports can remain unbuilt.
