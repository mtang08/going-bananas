# Follow-up work

## Coaching depth and evaluation

The current Coach runtime is an explicit local evidence-guided rule flow. It
supports conservative daily options and weekly proposals with uncertainty,
research references, current check-in context, accepted-plan context, and
outcome recording. It does not use an external model or automatically change a
plan. The research corpus contains 15 behavioral cases; the release checklist
records which behaviors have actually been verified. Do not claim all 15 are
implemented or that a favorable trend yields a calibrated progression.

Follow-ups: exercise each supplied case through the actual API/UI; add 28-day and
previous-14-day comparisons; account for delayed symptom timing and event history
in weekly review; evaluate useful progression and strength placement with the
athlete's confirmed schedule; calibrate recommendations against real outcomes
without inventing a numeric injury threshold. Review policy applicability and
source updates before adding new rules. An optional model-based flow would need
privacy, cost, evaluation, and user-approval design first.

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
