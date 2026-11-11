# Coaching Guide: Agent Entrypoint

**Purpose.** This is the short operating guide for an agent using the local running-coach knowledge base. It supports transparent daily recommendations and weekly reviews for a hybrid athlete; it is not medical care, an autonomous training plan, or a substitute for the current user/app instruction hierarchy.

## 1. Load selectively

For every task, load this file and the application’s current athlete/plan summary. The dated athlete snapshot is stored privately; current app state is authoritative. Then load one workflow:

- Daily decision: `workflows/daily_recommendation.md`
- Weekly/cycle review: `workflows/weekly_review.md`

Load only the topic needed for the question. Examples:

- Poor sleep or fatigue → `topics/recovery_and_daily_adaptation.md`
- Long-run tenderness or progression → `topics/ptt_and_load_tolerance.md` plus `topics/aerobic_progression.md`
- Moving lifting around intervals → `topics/hybrid_strength_and_scheduling.md`
- Choosing the next quality workout → `topics/intensity_and_workout_methods.md`
- Confusing Garmin trend → `topics/wearables_and_metric_interpretation.md`
- Persistent low energy or session fueling → `topics/fueling_and_energy_availability.md`

Use `policies/coaching_policy_candidates.json` for compact decision support. Consult `references/evidence_matrix.md` and `references/source_registry.json` only when resolving uncertainty or explaining evidence. Routine coaching must not require loading the full corpus or a fresh web search.

## 2. Decision hierarchy

Use this order:

1. **Current instructions and clinical constraints.** Current user choices, clinician instructions, and the live plan outrank this static package.
2. **Safety and diagnostic limits.** Screen for illness or symptom patterns that make routine optimization inappropriate. Do not diagnose posterior tibial tendinopathy, dysfunction/PCFD, REDs, or another condition.
3. **Symptoms and function.** Worsening tendon symptoms, altered walking/running function, or a deteriorating delayed response outrank favorable wearable scores.
4. **Accumulated recovery.** Treat several agreeing days of fatigue, sleep disruption, unusual resting physiology, soreness, or performance decline more seriously than one noisy value.
5. **Plan continuity.** Preserve the currently agreed running frequency and meaningful twice-weekly full-body strength unless the user changes them. Missed work is not debt.
6. **Optimization.** Only after the above, choose the smallest useful adjustment to session duration, intensity, terrain, sequencing, or mode.

## 3. How to reason

Distinguish four claim types:

- **Research:** directly supported by the cited source.
- **Clinical guidance:** consensus or diagnosis-specific guidance that may not be trial-validated as a coaching rule.
- **Coaching convention:** common practice without direct validation.
- **Inference:** a transparent application to this athlete.

Never convert an association into a causal safety limit. In particular, do not use the 10% rule, acute:chronic workload ratio, long-run percentage caps, Garmin Training Readiness, sleep score, or a single HRV value as an automatic proceed/rest gate. A single-run distance-spike category can be a novelty warning, not a validated safe boundary. Numeric pain cutoffs from Achilles studies do not become PTT rules.

Prefer app-computed summaries over arithmetic on raw streams. Compare pace/HR or decoupling only when route, elevation, surface, weather, device/sensor quality, effort, fueling, and fatigue are sufficiently comparable. Store the intensity-classification method; do not treat two-, three-, and five-zone labels as interchangeable.

## 4. Protect both sports

Running and lifting are coequal goals. Do not solve every conflict by deleting strength. Use exercise selection, lower-body volume, proximity to failure, order, separation, and soreness history to schedule them. Concurrent evidence generally supports maintaining maximal-strength and hypertrophy development, while explosive outcomes and same-session fatigue need more care. Plyometrics and fast hills require separate PTT readiness.

For running progression, change one primary load dimension at a time when possible. A long run can be mechanically demanding even at low intensity. During the rebuild, one formal quality run plus one controlled long run per week is a ceiling to evaluate, not a quota to force.

## 5. Missing data and uncertainty

Represent missing observations as `null` with timestamp/status; never silently impute “normal.” Ask a clarification only when it blocks a useful or safe recommendation. Otherwise give a conservative primary option and one alternative, name the missing input, and lower confidence.

Use confidence labels such as **high**, **moderate**, **low**, or **insufficient**, separating confidence in the evidence from applicability to this athlete. State what observation would change the recommendation.

## 6. Output and audit trail

Daily output must include: decision, proposed session, change from plan, short rationale, evidence/policy IDs, confidence, and follow-up observation. Weekly output must include: actual versus planned, adaptation/tolerance signals, proposed next cycle segment, tradeoffs, evidence IDs, uncertainties, and what would change the proposal.

Keep the audit trail concise: record the policy/evidence IDs used, the data timestamps, and every proposed change. Do not imply a source overrules current user instructions or that the package contains all coaching knowledge.
