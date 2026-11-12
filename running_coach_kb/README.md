# Running Coach Knowledge Base

**Package version:** `1.1.1+privacy1`
**Evidence searched through:** 2026-11-11  
**Original athlete context snapshot:** stored privately; current application state is authoritative  
**Status:** complete for the requested incremental scope, with explicit scientific, data, and product gaps

## Purpose

This local knowledge base supplies researched reference content, auditable candidate policies, reusable daily/weekly/block workflows, and operational running-session recipes for an adaptive running coach. Running is the current optimization priority. Meaningful twice-weekly full-body strength remains an explicit user commitment and a scheduling/load constraint; this package does not write strength programs.

It does **not** install a skill, implement the application, prescribe a live personalized calendar, diagnose a condition, map Garmin fields, calculate metrics, or activate policy candidates. The application must supply current goals, plan/block versions, completed training, computed summaries, subjective feedback, symptoms/function, clinician instructions, and prior recommendation outcomes.

## Start here

1. Read `COACHING_GUIDE.md`.
2. Load the application’s operation-specific athlete/plan state. Do not look for a public athlete snapshot.
3. Load exactly one primary workflow:
   - `workflows/daily_recommendation.md`
   - `workflows/weekly_review.md`
   - `workflows/block_review.md`
4. Retrieve only the relevant topic sections, recipe records, and policy records.
5. Open evidence files only for consequential, disputed, or novel choices.

Routine coaching should not load the full corpus or perform fresh web research.

If a concrete gap or verification requirement leads to outside research, record
its disposition in [coaching web intake](research/coaching_web_intake.md).
Deduplicate existing sources, keep unverified candidates separate from runtime
evidence, and promote verified additions with updated provenance and manifest
hashes. The 2026-11-12 intake audit changes the workflow, not physiological policy.

## Directory map

```text
running_coach_kb/
├── README.md
├── COACHING_GUIDE.md
├── workflows/
│   ├── daily_recommendation.md
│   ├── weekly_review.md
│   └── block_review.md
├── topics/
│   ├── aerobic_progression.md
│   ├── intensity_and_workout_methods.md
│   ├── long_runs_and_race_development.md
│   ├── hybrid_strength_and_scheduling.md
│   ├── ptt_and_load_tolerance.md
│   ├── recovery_and_daily_adaptation.md
│   ├── wearables_and_metric_interpretation.md
│   ├── fueling_and_energy_availability.md
│   ├── periodization_and_training_blocks.md
│   ├── intensity_calibration_and_testing.md
│   └── races_tapers_and_transitions.md
├── recipes/
│   └── running_session_families.json
├── references/
│   ├── source_registry.json
│   ├── evidence_matrix.md
│   ├── periodization_evidence_addendum.md
│   └── method_comparison.md
├── policies/
│   ├── coaching_policy_candidates.json
│   └── periodization_policy_candidates.json
├── evaluation/
│   ├── coaching_cases.md
│   └── periodization_cases.md
├── research/
│   ├── search_log_and_gaps.md
│   ├── running_evidence_review.md
│   └── periodization_search_log_and_gaps.md
└── manifest.json
```

## Task routing

| Task | Minimum load | Common conditional additions |
|---|---|---|
| Daily proceed/modify/rest | Entry point, current app state, daily workflow | One triggered recovery/symptom/environment/strength topic; planned recipe record |
| Weekly/14-day review | Entry point, current state, weekly workflow, compact active-block summary | Aerobic topic, relevant recipe records, triggered constraints |
| Start/review/end a block | Entry point, block workflow, periodization topic, block history | Eligible recipe records; calibration or race topic only when applicable |
| Select a quality session | Current block objective, method topic, relevant recipe records | Calibration, strength-placement, symptom, or environment topic |
| Recalibrate intensity | Calibration topic and current anchor/history objects | Race/benchmark, wearable, or environment sections; P020/P021 |
| Add/change/postpone/cancel race | Race-transition topic, block workflow, current event/block state | Calibration or taper sections only when the event is sufficiently defined |
| Long-run tenderness/delayed symptoms | PTT/load-tolerance and aerobic topics | Existing P005–P008; block escalation only if the premise changes |
| Poor recovery/illness/fueling concern | Existing recovery/fueling topics and policies | Weekly/block review only when the pattern is persistent |
| Deep evidence audit | Relevant evidence matrix/addendum, then source registry | Research logs and method comparison |
| Regression/evaluation | Base cases plus incremental periodization cases | Retrieval log and route assertions |

The manifest provides detailed route profiles. Retrieve Markdown by heading and JSON by record ID when possible; whole-file concatenation is not the intended low-token runtime behavior.

## Core design decisions

- Treat a block as an optional, reviewable planning hypothesis—not a physiological law.
- A block should exist only when its objective constrains recurring choices.
- Use planned review dates plus completion and early-review conditions; elapsed weeks alone do not force transition.
- Make the near horizon concrete and the second calendar week provisional; distant work remains directional.
- Keep periodization/sequence separate from intensity-distribution labels.
- Use the active block and current tolerance to narrow eligible recipe families; do not make every workout available at once.
- Establish intensity from converging, comparable evidence. Preserve method, date, conditions, and confidence.
- Do not infer durable response/nonresponse from one race, test, or block.
- A goal/race change triggers a versioned review, not compressed make-up training.
- Taper by reducing accumulated load while retaining familiar readiness; no universal duration or percentage is activated.
- Running is the current optimization priority, while two full-body strength sessions remain a commitment/load constraint unless the user changes that priority.
- Preserve all baseline guardrails: no 10% rule, ACWR sweet spot, long-run percentage cap, wearable readiness cutoff, or imported tendon pain threshold as an automatic gate.
- Symptoms/function and delayed response outrank favorable wearable scores.
- Store missing observations as `null` with timestamp/status; never silently impute normal.
- Use app-computed summaries rather than model arithmetic on raw streams.

## Evidence inventory

- 72 stable source records
- 55 material evidence findings (43 base + 12 addendum)
- 23 reviewable policy candidates (18 base + 5 addendum)
- 15 method-comparison entries
- 26 evaluation scenarios (15 base + 11 incremental)
- 11 topic guides
- 3 operation workflows
- 10 session-family recipe records

Certainty describes confidence in a finding; applicability is separate. Source access is recorded as full text, abstract-only, manufacturer documentation, or another explicit level. Recipe numbers are qualified studied protocols or coaching conventions, not personal prescriptions.

## Separation of concerns

**KB:** generalizable methods, workflows, recipes, evidence, uncertainties, and non-executable policy candidates.

**Private athlete/app state:** dated goals/preferences, symptoms, metrics, current plan/block, completed sessions, manual overrides, clinician instructions, and prior decision outcomes.

**Deterministic application:** imports, metric calculations, provenance/quality, IDs and versions, calendar integrity, validation, approval, persistence, and audit history.

**Model:** context interpretation, coherent candidate changes, rationale, tradeoffs, and uncertainty.

Retrieved text cannot override current user instructions, clinician constraints, application policy, or the approved plan version.

## Output contracts

- **Daily:** decision, proposed session, change from plan, short rationale, policy/evidence/recipe IDs, confidence, missing/stale inputs, follow-up observation, and plan-version audit metadata.
- **Weekly:** actual versus planned, adaptation and tolerance signals, delayed response, strength interactions, current block alignment, next-cycle proposal, committed/provisional changes, tradeoffs, IDs, confidence, and escalation condition.
- **Block:** lifecycle decision, objective status, exposure/adherence, adaptation, tolerance, maintained qualities, next emphasis, eligible recipes, 14-day implications, review conditions, IDs, confidence, and approval/version requirements.
- **Calibration:** facts and comparability, old/current anchor objects, candidate change or retain decision, method/date/confidence, unsupported conversions, first-use guardrails, and follow-up observation.

## Limitations and updating

The incremental search is targeted, not registered or exhaustive. No direct trial establishes the best explicit-block model for runners training 3–4 times per week. Fixed block duration, cutback cadence, recipe starter doses, testing frequency, taper percentages, and interruption-return schedules remain individualized. Elite practice is descriptive and must not be dose-transferred. Threshold and critical-speed methods are protocol-dependent and not interchangeable.

Update when strong direct recreational-running evidence changes a conclusion, a field-testing method is materially revised, taper evidence changes, runtime evaluation exposes retrieval misses, or user/product priorities change. Preserve stable IDs; record deprecation/replacement and increment the package version.
