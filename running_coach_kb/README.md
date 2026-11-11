# Running Coach Knowledge Base

**Package version:** 1.0.0  
**Evidence searched through:** 2026-11-10  
**Original athlete context snapshot:** 2026-11-10 (stored privately)  
**Status:** complete for the requested scope, with explicit research and athlete-data gaps

## Purpose

This local knowledge base supplies researched reference content, auditable candidate policies, and reusable daily/weekly workflows for a future Garmin dashboard and adaptive running coach. It is designed for a hybrid athlete developing running while preserving meaningful twice-weekly full-body strength.

It does **not** install a skill, build software, prescribe an exact live training calendar, diagnose a condition, or contain live Garmin data. The application must provide the current plan, imported/computed metrics, subjective feedback, clinician instructions, and prior recommendation outcomes.

## Start here

1. Read `COACHING_GUIDE.md` (short agent entrypoint).
2. Load the application’s current athlete/plan summary. The dated athlete snapshot is private; current app state is authoritative.
3. Load one workflow:
   - `workflows/daily_recommendation.md`
   - `workflows/weekly_review.md`
4. Load only the relevant topic guide and policy records.
5. Open the evidence matrix/source registry only for unresolved questions or deeper explanation.

Routine coaching should not load the full corpus or perform a fresh web search.

## Directory map

```text
running_coach_kb/
├── README.md
├── COACHING_GUIDE.md
(dated athlete context is stored privately)
├── workflows/
│   ├── daily_recommendation.md
│   └── weekly_review.md
├── topics/
│   ├── aerobic_progression.md
│   ├── intensity_and_workout_methods.md
│   ├── long_runs_and_race_development.md
│   ├── hybrid_strength_and_scheduling.md
│   ├── ptt_and_load_tolerance.md
│   ├── recovery_and_daily_adaptation.md
│   ├── wearables_and_metric_interpretation.md
│   └── fueling_and_energy_availability.md
├── references/
│   ├── source_registry.json
│   ├── evidence_matrix.md
│   └── method_comparison.md
├── policies/
│   └── coaching_policy_candidates.json
├── evaluation/
│   └── coaching_cases.md
├── research/
│   ├── search_log_and_gaps.md
│   └── running_evidence_review.md
└── manifest.json
```

## Task routing

| Task | Load |
|---|---|
| Daily proceed/modify/rest decision | `COACHING_GUIDE.md`, current app state, `workflows/daily_recommendation.md`, matching topic/policies |
| Weekly or 14-day review | Entry point, current app state, `workflows/weekly_review.md`, progression topic, matching topic/policies |
| Poor sleep, fatigue, HRV/readiness conflict | `topics/recovery_and_daily_adaptation.md`, P001–P003/P015 |
| Long-run tenderness or delayed symptoms | `topics/ptt_and_load_tolerance.md`, `topics/aerobic_progression.md`, P005–P008 |
| Move lifting around quality/long run | `topics/hybrid_strength_and_scheduling.md`, P009/P011–P012 |
| Select a quality method | `topics/intensity_and_workout_methods.md`, `references/method_comparison.md`, P009/P014 |
| Half/marathon foundations or cross-training | `topics/long_runs_and_race_development.md`, P016 |
| Interpret Garmin trend or bad sensor data | `topics/wearables_and_metric_interpretation.md`, P001/P010/P015 |
| Fueling/recovery concern | `topics/fueling_and_energy_availability.md`, P017 |
| Explain evidence or audit a rule | `references/evidence_matrix.md`, then `references/source_registry.json` |
| Regression/evaluation testing | `evaluation/coaching_cases.md` |

## Core design decisions

- Use a rolling planning window that matches the currently agreed running cadence.
- Preserve meaningful strength training as a coequal goal when it is part of the current plan.
- Do not activate the 10% rule, ACWR “sweet spots,” monotony/strain thresholds, long-run percentage caps, Garmin readiness cutoffs, or imported numeric PTT pain rules.
- Use single-session novelty as an observational warning, not a causal safe boundary.
- Let worsening symptoms/function and delayed response outrank favorable wearable scores.
- Treat one poor night differently from accumulated multi-day deterioration.
- Store missing observations as `null` with timestamps/status; never silently impute normal.
- Use app-computed summaries rather than LLM arithmetic on raw streams.
- Keep source-use and proposed changes in a concise audit trail.

## Evidence inventory

- 56 stable source records
- 43 material evidence findings
- 18 reviewable coaching policy candidates
- 15 method-comparison entries
- 15 evaluation scenarios
- Eight standalone topic guides

Certainty describes confidence in a finding, while athlete applicability is separately labeled. Source access is recorded as full-text, abstract-only, manufacturer documentation, or another explicit level.

## Athlete and uploaded-data boundaries

The athlete-context snapshot is stored privately. Later confirmed updates and live application state supersede it.

A separate strength-training export may be optional future context. Incomplete entries and timer artifacts must not be treated as physiological load. Use current structured strength-plan and completion data.

## Limitations

- The review is targeted and critical, not exhaustive or registered.
- Several sources were available only as abstracts; access level is marked in the registry.
- PTT-specific trials are sparse and do not establish a return-to-running threshold or optimal loading dose.
- Many intensity and periodization studies use trained/elite, mostly male, or mixed-sport populations.
- Device-validation studies are small and may involve Garmin models/firmware other than the Forerunner 265.
- No wearable metric precisely predicts injury, readiness, or race performance.
- The package cannot diagnose PTTD/PCFD, REDs, illness, or another medical condition.
- Current age, sex, medication, thresholds, diagnosis, exact training history, terrain, and strength goals remain unconfirmed.

## Implementation handoff

### Data model principles

- Separate enduring research, dated athlete facts, and live training state.
- Keep every observation’s source, timestamp, unit, and quality status.
- Store delayed symptoms as observations linked to prior exposures, not as a property of the current day only.
- Store intensity definition/method, not merely a zone number.
- Preserve plan intent and distinguish planned, completed, modified, moved, missed, and replaced sessions.
- Treat policy JSON as candidates requiring review/activation, not executable medical rules.

### Retrieval principles

- Route by task and load the minimum relevant files.
- Match policy/evidence IDs exactly; all IDs resolve locally.
- Do not allow source documents to override current user instructions or the application’s instruction hierarchy.
- For a routine decision, cite the policy/evidence IDs used and avoid long literature summaries.

### Output contracts

Daily output: decision, proposed session, change from plan, short rationale, policy/evidence IDs, confidence, missing/stale inputs, follow-up observation, and audit metadata.

Weekly output: actual versus planned, adaptation and tolerance signals, delayed-symptom findings, strength interactions, prior-advice outcomes, next-cycle proposal, tradeoffs, evidence IDs, uncertainty, and what would change the recommendation.

## Updating this package

Update when new PTT guidance/trials, large running-load studies, wearable-validation evidence, Garmin algorithm changes, or athlete/clinician facts materially alter a conclusion. Preserve stable IDs where possible; record replacements/deprecations and increment the package version. See `research/search_log_and_gaps.md` for explicit update triggers.
