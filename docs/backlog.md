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
in [live-progress.md](archive/live-progress.md). Strength prescription remains outside
this phase; preserve the confirmed hybrid schedule as running context.

Proposal presentation (structured short form, implemented 2026-11-23): the app shows a brief card with a headline, a typed why-list (observed, research, inference, priority), uncertainty, change triggers, and a next check; each session change carries an effort, focus cues, adjust-if rules, and a one-line why behind its row; sources appear as titles, never IDs. Every field has a character limit that validation enforces, and one optional coach note of 400 characters or fewer is the only free text. Depth (observations, research, trade-offs, alternatives) stays in the chat with the coach, which also keeps the day table, the would-change-this list, and the next check-in. Notes on a session belong to the athlete only.

Implemented 2026-11-12: proposal review supports dated session changes, hidden
evidence tags, individual acceptance, and expandable comparisons. The intro was
later replaced by the structured brief card, with confidence details collapsed;
the coach's `references/proposal-format.md` defines the saved fields and the
chat format. Pending-proposal revision with a stable review link was
implemented and verified on 2026-11-12: the coach edits an existing draft,
the app retains revision history and highlights changed sessions, and acceptance
requires the reviewed revision. Invalid edits preserve the saved draft;
accepted/rejected proposals remain fixed. Manual counterproposals are IDEA-007.

Implemented (AC-1, adaptive coaching and lean UI; plan in the external planning workspace at `adaptive_coaching/README.md`): the five-page app; the deterministic exception detector (`exceptions.v1`), which replaces daily guidance; exception review with tracked patches; the weekly and block `exception_summary`; post-race review; and the block-ending benchmark with a manual match and benchmark history. Follow-ups: **O2** — a default cross-training mode for low-impact substitutions (REC010) is not modeled; the coach asks. **O3** — tune the expected-RPE ranges and detector thresholds (`session_class.v1`, `exceptions.v1`) after 2–3 weeks of real findings.

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

Recorded 2026-11-11. Status: partly delivered by GCAL v1: detected and manual trips with dates, destination timezone, travel days, running and gym access, and per-day availability, shown as calendar badges and in coach context. Remaining: daily training-time windows and non-travel disruption kinds. AC-1 still logs a `travel` context tag as a finding.

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
plan changes still require explicit acceptance.

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

Read-only travel detection shipped on 2026-11-23 in `ce8408f`, alongside structured coach proposals and KB version `1.3.0+privacy1`. The real app completed migration `0025_coach_output_v2` and its first Calendar sync. Coaching reviews use the travel topic when a trip falls within scope. [Travel KB](../running_coach_kb/topics/travel_and_time_zones.md)

Workout scheduling and calendar sharing remain open.

**Problem / context**
The athlete wants planned sessions to fit predetermined times they assign and
to share the resulting schedule with friends. Flights also affect when and
where the athlete can train.

**Desired behavior**
Integrate with Google Calendar so the training plan can sync with athlete-
assigned workout times and be shared with friends through the calendar. Use
flight information from the calendar when building training plans so sessions
fit around travel.

**Acceptance checks**
- Planned sessions can sync to Google Calendar at the times assigned by the
  athlete and appear in a calendar that can be shared with friends.
- Flight information is available to the coach and considered when building a
  training plan around travel.

**Constraints**
Unspecified.

**Open questions**
Decide whether workout publishing should be one-way or reflect edits made in Google Calendar, and how the athlete selects the calendar to share.

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

### IDEA-010 — Integrate PTT and hip mobility work with benchmarks

Recorded 2026-11-19. Status: idea. Priority: Unspecified.

**Problem / context**
The athlete wants PTT and hip mobility routine work included in training, with
benchmarks to track progress.

**Desired behavior**
Support scheduling and tracking PTT and hip mobility routine work alongside
the training plan, with benchmarks that show progress over time.

**Acceptance checks**
- The athlete can include PTT and hip mobility work in the plan and track
  progress against relevant benchmarks.

**Constraints**
Unspecified.

**Open questions**
The meaning of PTT, the specific routine, and the desired benchmarks are
unspecified.

### IDEA-011 — Reduce Garmin sync time spent refreshing local metrics

Recorded and implemented 2026-11-20.

**Problem / context**
A live benchmark of a one-day sync took 74.7 s from request to completion. The
request queued in 9 ms, and the worker picked it up after 6.2 s. The activity
fetch took about 0.5 s and returned zero activities. Writing the coverage
interval triggered 33.0 s of local metric refresh. Sleep and HRV took 1.3 s
combined. Resting HR changed one observation and took 33.4 s, including 32.8 s
of metric refresh. Each refresh revisited nine metric windows. Together the
refreshes accounted for about 88% of the measured wall time.

**Desired behavior**
Routine incremental sync finishes sooner by avoiding redundant metric refresh
work while keeping coverage, matching, prompts, and metrics current.

**Acceptance checks**
- Repeat a one-day sync with no new activities and with one changed recovery
  observation. Compare end-to-end time and refresh work against the benchmark.
- Verify newly covered days and changed recovery data still update affected
  results.

**Constraints**
The incremental fetch already uses each dataset’s last fully synced date.
Preserve the local worker, async sync status, and existing history.

**Implementation and verification**
Only days that gain or lose complete, fully enumerated activity coverage trigger
coverage-based metric updates. Sleep, HRV and resting-HR changes refresh the
affected recovery nights and seven-day summaries. A sync can still initialize
today's training windows and advance time-based prompts.

The isolated PostgreSQL benchmark queued four one-day jobs, returned zero
activities, and corrected one resting-HR observation with nine reporting dates
already materialized. Request-to-completion time fell from 1.612 s to 0.166 s.
Metric calculations fell from 480 to 18 (nine recovery nights and nine summaries).
The fixture uses synthetic Garmin responses and immediate worker pickup. The
74.7 s measurement above is the original live observation.
[Benchmark and regression cases](../backend/tests/integration/test_incremental_sync_refresh.py)

### IDEA-012 — Manual pace overrides for treadmill runs

Recorded and implemented 2026-11-22. Priority: High.

**Problem / context**
The athlete reports that Garmin records inaccurate paces on treadmill runs.
Accurate interval paces are especially important when reviewing what they ran
during a workout.

**Desired behavior**
When Garmin sync finds a new treadmill run, let the athlete review the intervals
and correct their paces before importing the activity and computing its metrics.
Show the saved corrections when the athlete reopens the run.

**Acceptance checks**
- Sync a treadmill workout, an outdoor run, and a track run. The outdoor and
  track runs import normally and the treadmill run waits for confirmation.
- Enter different paces for two intervals, confirm, and reopen the activity.
  Each interval shows its saved correction alongside the watch-calibrated run totals.

**Constraints**
Overrides apply to treadmill runs and must support individual intervals.
The athlete calibrates the overall pace and distance manually on the Garmin
watch when recording the run. Interval edits preserve those calibrated totals.

**Open questions**
Should the athlete be able to enter treadmill belt speed as well as pace?

### IDEA-013 — Evaluations that catch coaching-quality regressions

Recorded 2026-11-22. Status: idea. Priority: Low (after Google Calendar travel
integration and the coach-output UI restructure).

**Problem / context**
New features change what the coach sees (snapshot sections) and what it writes
(proposal fields), but nothing checks whether coaching quality degrades. The
behavior cases in `running_coach_kb/evaluation/` describe expected behavior and
prohibited inferences, and have never been executed. The athlete does not need
this now: they are the only user, usage is light, and much of the value comes
from talking back and forth with the coach rather than from a fixed
prescription. When a feature does not fit how they use it, they adapt it.

**Desired behavior**
Run a set of synthetic scenarios through the real coach on demand and see
whether its decisions still match each case's expected behavior, compared with
an earlier run.

**Acceptance checks**
- Running the suite on demand reports, per case, whether the coach's decision
  matches the expected behavior and avoids the prohibited inferences.

**Constraints**
Synthetic data only; never real mode. Not part of routine checks. No guardrails
that restrict how the athlete uses the coach.

**Open questions**
Whether a headless Codex run can reach the local app and load the repo skill;
which model grades results; whether to start with input-only checks (snapshot
and findings for each scenario) before any model-in-the-loop runs.

### IDEA-014 — Trip-aware local dates

Shelved on 2026-11-23. The athlete chose to keep app dates in the home timezone given how rarely they travel.

**Problem / context**
GCAL v1 shows trips and destination timezones to the coach, but every app date stays in the home timezone. During a trip far east or west of home, a morning run can land on the previous `local_date` and miss its planned session, and "today" changes at home midnight.

**Desired behavior**
While a confirmed trip is active, dates and "today" follow the destination timezone, so runs match the sessions planned for the athlete's local day.

**Acceptance checks**
- A run recorded on a trip day matches that day's planned session in the destination timezone.
- Stored local dates and metric results stay consistent when a trip is confirmed, edited, or dismissed.

**Constraints**
Dates come from one profile timezone at about 70 call sites in 36 files. The metric identity hash includes the profile timezone, and each activity's `local_date` is fixed at import. A per-date zone changes metric identity and needs stored local dates re-derived when a trip changes. Back up before any real recompute.

**Open questions**
Whether the zone applies to the whole trip or only from the arrival leg; how a change to a confirmed trip re-derives stored dates and metrics.

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
phone access is paused. The proposed iPhone check-in workflow uses a private tailnet and the Mac as the server. Refresh the plan against current main and revisit the five setup decisions before resuming. Detailed streams/maps, workout
publishing, broader provider-history verification, and optional agent evaluation
remain separate projects. No calorie logging is required.
