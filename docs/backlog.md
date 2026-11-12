# Follow-up work

## Active priority — complete the running-coach workflow

November 11, 2026: the user explicitly rejected the current workflow as not yet
usable. Deliver concrete research-backed running proposals that persist into
app review/acceptance, dated calendar sessions, daily confirmation/adjustment,
actual execution/feedback, and the next review. The normal coaching review
cadence is one check-in each Sunday evening, with additional reviews for
material changes, symptoms, or new goals. This describes a manual coaching
cadence, not scheduled automation. This takes priority over further polishing
of the separate local-rule cards. See the living implementation and acceptance
plan in [running-coach-workflow.md](running-coach-workflow.md), and resume state
in [live-progress.md](live-progress.md). Strength prescription remains outside
this phase; preserve the confirmed hybrid schedule as running context.

Proposal presentation: start with a concise focus sentence, followed by one or
two coherent rationale paragraphs, then a concise activity table with the
workout prescription, then the next check-in. Keep the rationale at the top,
not as stream-of-consciousness bullets after the table. Include session-level
reasons only for material tradeoffs instead of repeating rationale in every
row. Remove evidence tags from the athlete-facing presentation.

Implemented 2026-11-12: proposal review supports dated session changes, hidden
evidence tags, individual acceptance, and expandable comparisons. The intro uses
a compact focus statement with confidence details collapsed. Current
presentation direction places concise rationale paragraphs before the activity
table, with follow-up after it; the coach's `references/proposal-format.md`
defines this format. Pending-proposal revision with a stable review link was
implemented and verified on 2026-11-12: the coach edits an existing draft,
the app retains revision history and highlights changed sessions, and acceptance
requires the reviewed revision. Invalid edits preserve the saved draft;
accepted/rejected proposals remain fixed. Manual counterproposals are IDEA-007.

## Feature ideas inbox

Capture new ideas here over time. These entries record desired behavior, not
implemented features or commitments to a particular design. Keep stable IDs so
later conversations can refine an idea and link its implementation.

### IDEA-001 — Athlete context for personalized coaching

Recorded 2026-11-11. Status: idea.

Add editable height, birthday (derive age for the date being reviewed), and
dated weight observations with explicit units. Use confirmed athlete context
alongside goals, training history, and current feedback when assessing research
applicability. Preserve weight history rather than overwriting it, and leave
unreported fields unknown. Personal values belong in private app storage, not
the shared research corpus. This entry does not add fields or change current
recommendations.

### IDEA-002 — Conversational coach with research and lasting context

Recorded 2026-11-11. Status: initial Codex skill built; dashboard chat deferred.

The versioned skill is in `skills/going-bananas-coach/`. It uses the local
context endpoint and integrity-checked KB loader, supports check-in writes,
and stores confirmed memory in the existing versioned profile facts. It does
not add a dashboard chat UI, change the local rule engine, or persist chat
proposals as dashboard recommendations. Personal context still has no dedicated
height/birthday/weight UI; the skill can remember confirmed dated facts.

Support occasional conversations about progress, new goals, priorities, and
schedule constraints, plus morning check-ins and periodic reviews. The coach
skill should receive current app-computed training/recovery summaries,
confirmed athlete context, goals, prior decisions/outcomes, and selectively
loaded KB workflows, relevant research, applicability limits, and open research
gaps. The KB supplies evidence context; the skill supplies the interaction and
reasoning workflow. Save confirmed goals/preferences and review summaries for
future conversations, with explicit acceptance of proposed plan changes.
The dashboard's local rule flow remains separate from the conversational skill.

### IDEA-003 — Morning readiness within a disciplined plan

Recorded 2026-11-11. Status: idea.

Make a morning check-in use the previous night's synced sleep and show data
freshness. Support an evening preview followed by morning confirmation. The
user wants the agreed training schedule to remain the default commitment and
good sleep to be an expectation of preparation. Distinguish an isolated poor
sleep observation from sustained deterioration and current symptom/function
concerns; explain proposed deviations and preserve explicit plan acceptance.
This preference is captured here for future design, not activated as a coaching
rule or saved athlete-profile setting.

### IDEA-005 — Vacation, travel, and temporary schedule exceptions

Recorded 2026-11-11. Status: idea.

Allow the athlete to enter vacation/travel date ranges and other temporary
schedule disruptions. Capture relevant constraints when known: available
training days/time, gym or equipment access, running access, travel days, and
destination timezone. Distinguish unavailable days from days where a shorter
or alternative session is possible; don't assume vacation means no training.
Make exceptions visible on the calendar and include them in coach context so
the conversational coach can propose adapted placement, reduced sessions,
alternatives, or a planned break consistent with current goals and recovery.
Preserve the underlying alternating schedule and run parity unless the user
explicitly chooses a lasting change. Show how the normal rhythm resumes after
the exception; don't turn missed travel sessions into catch-up debt. Proposed
plan changes still require explicit acceptance. No implementation yet.

### IDEA-006 — Strength goals and integrated hybrid coaching

Recorded 2026-11-11. Status: idea; dedicated research round planned, not started.

Extend the Strong integration beyond browsing imported lifting history so the
coach can recommend how to pursue explicit lifting goals alongside running
goals. Treat strength as a coequal objective, not only support work for running.
Use recorded exercises, sets, reps, loads, user-reported effort/tolerance, and
confirmed goals to inform progression, exercise selection, training volume,
and placement around runs. Explain tradeoffs when running and lifting priorities
compete, and preserve explicit acceptance of proposed changes. Strong remains
the lifting workflow; this idea does not imply workout write-back support.

Conduct a separate research round to build a strength and hybrid-training KB,
complementing the running KB. Cover strength/hypertrophy development, progression
and autoregulation, concurrent-training interactions, session sequencing and
recovery, and applicability to the athlete's goals and constraints. Preserve
source provenance, evidence certainty, applicability limits, research gaps,
and evaluation scenarios. Route relevant context from both KBs to the coach
rather than treating either sport's recommendations in isolation.

Before interpreting load progression, resolve the Strong export's unknown
weight units and dumbbell recording convention where relevant. Do not compare
loads across an unverified convention change or infer effort from load alone.
No research or implementation is authorized merely by recording this idea.

### IDEA-007 — Athlete counterproposals with coach review

Recorded 2026-11-12. Status: idea. Priority: Unspecified.

**Problem / context**
The athlete may want to suggest a change to a pending coaching proposal, with
the coach checking how it fits the current plan and explaining any consequences.
The existing proposal review should remain the place to consider the plan.

**Desired behavior**
Allow the athlete to record a counterproposal against a pending proposal. The
coach reviews it against the plan and relevant athlete context, explains its
tradeoffs, and prepares a revised proposal for the athlete to review. For
example, the athlete suggests moving a workout; the coach assesses the effect
on recovery and schedule, then presents a revision or explains why it does not
fit.

**Acceptance checks**
- An athlete can propose a change to a pending plan and receive a coach critique
  that addresses its fit and material tradeoffs.
- The athlete can review a resulting plan revision while retaining the pending
  proposal's identity and review link.

**Constraints**
The coach's response remains advisory and any plan change remains pending until
the athlete accepts it. This entry records a future feature request; it does
not authorize implementation or imply that manual counterproposal editing is
currently available.

**Open questions**
Unspecified.

### IDEA-008 — Schedule and share training plans in Google Calendar

Recorded 2026-11-12. Status: idea. Priority: Unspecified.

**Problem / context**
The athlete wants planned sessions to fit predetermined times they assign and
to share the resulting schedule with friends.

**Desired behavior**
Integrate with Google Calendar so the training plan can sync with athlete-
assigned workout times and be shared with friends through the calendar.

**Acceptance checks**
- Planned sessions can sync to Google Calendar at the times assigned by the
  athlete and appear in a calendar that can be shared with friends.

**Constraints**
Unspecified.

**Open questions**
Whether calendar sync should be one-way or keep edits synchronized in both
directions; how the athlete chooses which calendar to share.

### IDEA-009 — Support integrated HYROX training

Recorded 2026-11-12. Status: idea. Priority: Unspecified.

**Problem / context**
The athlete wants HYROX training supported alongside the existing running and
strength training context.

**Desired behavior**
Support integrated HYROX training planning that considers running and strength
work together with HYROX preparation.

**Acceptance checks**
- HYROX preparation can be considered alongside running and strength when
  planning training.

**Constraints**
Unspecified.

**Open questions**
Unspecified.

## Coaching depth and evaluation

### Product direction — dashboards plus conversational coaching (IDEA-004)

Recorded 2026-11-11. Status: desired direction; UI changes not yet implemented.

The user finds Generate daily guidance too deterministic. Prioritize dashboards
that visualize progress and a conversational coach that reasons using relevant
KB research, health/recovery metrics, performance, confirmed athlete context,
and goals. The rule-generated daily/weekly cards should not be presented as the
primary coaching experience. Decide how to retire or demote that UI while
preserving stored recommendations/outcomes and the useful context/KB services.
Keep deterministic data calculations and freshness/coverage reporting as the
foundation for model reasoning. The installed Codex skill is the current
conversational entry point; dashboard chat would be a separate implementation.

The runtime-depth follow-ups below describe the existing rule flow and are not
the primary product priority under this direction.

The current Coach runtime is an explicit local evidence-guided rule flow. It
supports conservative daily options and weekly proposals with uncertainty,
research references, current check-in context, accepted-plan context, and
outcome recording. It does not use an external model or automatically change a
plan. The research corpus contains 15 behavioral cases; the release checklist
records which behaviors have actually been verified. Do not claim all 15 are
implemented or that a favorable trend yields a calibrated progression.

Follow-ups: exercise each supplied case through the actual API/UI; add 28-day and
previous-14-day comparisons; account for delayed symptom timing and event history
in weekly review; evaluate useful progression with the
athlete's confirmed recurring strength schedule; calibrate recommendations against real outcomes
without inventing a numeric injury threshold. Review policy applicability and
source updates before adding new rules. An optional model-based flow would need
privacy, cost, evaluation, and user-approval design first.

## Historical run labels

The deterministic classifier is deliberately bounded to whole-run summary
fields. A future evaluation should compare suggestions with user-corrected labels
and test weather/route and sensor confounding. Intrarun HR streams, drift, and
interval analysis are unsupported by the current canonical fields. Do not
introduce per-activity model calls to label history. Future model token use, if
implemented and evaluated, belongs to explicit daily coaching skill invocation
and weekly recap/next-one-to-two-week planning, with cost and privacy controls.
The current Coach runtime remains local rules, without that skill architecture.

## Strong source evolution

The inspected Strong CSV is imported and replay-safe. Future CSV shapes need
schema inspection before mapping. Resolve the unknown dumbbell recording
transition only with an explicit user-provided date/convention; do not infer a
factor from weights. Add user-reviewed cross-source reconciliation for ambiguous
same-day strength candidates. Historical source-local times have no verified
zone or weight unit. Keep older than 18 months in history, outside current
running recommendations.

## Garmin and product work

The inspected Garmin export is imported for supported activity and recovery
fields. Export coverage remains partial. Future export shapes and additional
Health Status metrics require schema/API comparison before mapping. Private
phone access or hosting needs authentication. Detailed streams/maps, workout
publishing, broader provider-history verification, and optional agent evaluation
remain separate projects. No calorie logging is required.
