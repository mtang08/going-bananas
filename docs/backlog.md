# Deferred work

## Strong strength history (confirmed 2026-11-10)

The athlete records lifting in Strong and intends to keep that workflow. Treat
Strong as a future independent source, potentially a CSV import. No export is
available and no parser or integration is authorized for the current MVP.

Current strength coverage is incomplete. Count imported/manual sessions as
**recorded** sessions only. Missing Garmin strength recordings cannot establish
that lifting was skipped. The twice-weekly strength preference remains meaningful
and should be preserved in manual planning and later coaching.

When an export is available: inspect its actual schema locally; preserve original
bytes; map source identities, dates/timezones, exercises and sets only after
verification; retain provenance; reconcile overlapping manual/Garmin entries
without silent merging. Source adapters feed the same canonical history; do not
make Garmin the owner of all strength records. No invented strength targets or
calorie logging requirement.

## Local research knowledge base

Integrate the future `running_coach_kb/` by loading guide → requested workflow →
relevant topic sections/policies. Preserve explanatory prose, sources, conflicts,
and uncertainty. Research stays separate from dated athlete profile and current
observations. Use a simple local file index initially. No runtime coach, automatic
prescriptions, rigid policy engine, or model calls are active in the MVP.

## Historical Garmin export

Implement a parser only after the real export arrives and its formats/identities
are inspected. The official Personal API is the validated real ingestion path.
Do not infer export paths or claim arbitrary ZIP/CSV compatibility.

## Later product work

Private phone access/hosting with authentication, detailed activity streams/maps,
workout publishing, broader history bootstrap beyond manually selected windows,
and optional agent recommendation evaluation follow the local analytics core.
