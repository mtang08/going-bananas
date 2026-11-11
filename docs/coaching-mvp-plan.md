# Research and strength integration

Requested November 10, 2026. Extend the existing local app into a usable daily
recommendation and weekly review loop, with no automatic plan rewrites.

## Implementation responsibilities

1. Research: validate the archive and duplicate deliverables; preserve original
   bytes privately; separate dated athlete context; index reviewed prose and
   candidate policies for selective guide → workflow → topic loading.
2. Strength: import the observed Strong CSV format idempotently; preserve all
   raw sets, timestamps, and unresolved units. Use only the preceding 18 calendar
   months in current running context. Earlier records remain historical.
3. Coaching: persist explicit daily/weekly generations and outcomes with evidence,
   input versions, uncertainty, and staleness. Validate selected decision aids
   against the supplied cases. Never promote the entire candidate file to rules.
4. App: daily check-in → recommendation → user decision → subsequent feedback;
   historical strength review; source/freshness and research audit visibility.

## Activation boundaries

- The initial runtime is local evidence-guided decision support. No external
  model credential is configured. It must label its engine and limited scope;
  never present template decisions as an LLM's comprehensive research synthesis.
- No automatic intensity-zone inference, mileage percentage progression,
  rehabilitation dosage, calorie logging, diagnosis, or clearance from a watch.
- Current symptoms/function and clinician restrictions take priority. Unknown
  input remains unknown. Tomorrow's preview needs a fresh check before training.
- Every-other-day run dates require a confirmed anchor; strength remains twice
  weekly. Unconfirmed schedule details yield provisional placement, not invented
  accepted plans. Accepting advice does not silently alter a plan.
- Strong dumbbell weights have an unknown convention transition. Preserve
  recorded values and show this uncertainty; never infer a correction factor,
  compare cross-regime PRs, or use historical peak weights as training targets.
- Raw exports, dated personal research context, feedback, and recommendations
  remain private. Reviewed enduring research prose may be version controlled.

## Acceptance

Verify archive hashes, privacy separation, selective loading, missing/corrupt KB
failure, CSV dates/durations/missing values and replay, source separation,
18-month filtering, and no cross-convention weight claims. Run the supplied
coaching scenarios with explicit supported/unsupported coverage. Check persisted
recommendation cache invalidation, rejection/outcome recording, no automatic plan
mutation, daily feedback precedence, and browser/mobile paths. Migrate isolated
databases before real data, back up before importing, independently compare
real source counts, and restore the resulting backup into an isolated target.

Track research gaps and remaining athlete clarifications in
`research-integration.md`; show necessary clarifications in the app rather than
blocking development or inventing facts.
