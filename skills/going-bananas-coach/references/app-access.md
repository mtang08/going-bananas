# Local app access and persistence

Use Python 3.12+ and `scripts/coach_app.py` relative to this skill. The helper
uses only the standard library. Default origin: `http://127.0.0.1:8000`;
`--base-url` permits another loopback HTTP port. Proxies/redirects are disabled.
No credentials or `.env` reads are needed. Do not send context to another service.

Examples assume `HELPER` is this script's absolute path. Global flags precede
commands. Athlete coaching uses default `--mode real`; demo/test are reserved
for explicitly synthetic verification. Every response checks mode, and writes
verify mode with a read first.

```sh
python3 "$HELPER" review-week
python3 "$HELPER" today
python3 "$HELPER" status
python3 "$HELPER" sync
python3 "$HELPER" schema
python3 "$HELPER" inspect
python3 "$HELPER" knowledge --repo /Users/mtang/dev/going-bananas --workflow daily --topics recovery_and_daily_adaptation --policies P001 P002
python3 "$HELPER" knowledge --repo /Users/mtang/dev/going-bananas --workflow block --topics periodization_and_training_blocks --policies P019 --recipes REC001
```

`today`, `review-week`, and `context --workflow daily|weekly` GET
`/api/v1/coach/agent/context`, optionally with `--as-of YYYY-MM-DD`. They retrieve
facts and research, not generated advice. `data.context` contains training,
profile, active plan, feedback, metrics and revision chronology. Top-level data
includes `as_of`, `evidence_hash`, `current_revision_id`, `knowledge`, `prose`,
and selected file/record provenance. The invoking Codex agent reads and reasons
from this data. Calendar/UI requests and sync never invoke a model.

`status` GETs `/sync/status`; `sync` POSTs `/sync` only when no active job exists.
Poll status briefly (about a minute maximum) with updates; report pending/failed
or incomplete datasets. A completed sync is not proof of observation coverage.

`knowledge` uses the integrity-checked repository loader without API/database
access. Select `daily`, `weekly`, or `block` research workflows, up to four topic
stems, eight policy IDs (P001–P023), twelve source IDs (S001–S072), and three
recipe IDs (REC001–REC010). Only requested recipe records are returned, with
their prerequisites, exclusions, illustrative-dose qualifications, and evidence.
Block retrieval supplies reference material; the app context commands remain
`daily|weekly`. No block lifecycle or intensity-anchor persistence is added.
Use actual source IDs from selected policy records. Do not bypass integrity
errors by editing KB files. Output includes the dated research cutoff.

## Author and apply a proposal

Read `schema` (GET `/coach/agent/schema`) for the exact current JSON schema.
Write personal payloads beneath ignored `private/real/` with restrictive
permissions, never tracked examples. Keep a stable UUID-like `idempotency_key`
for the same operation. Then run:

```sh
python3 "$HELPER" apply --file /absolute/private/path/proposal.json
```

`apply` POSTs `/coach/agent/proposals`. The backend validates the current evidence
hash/revision, profile/schedule, source IDs, and prescription completeness before
atomically activating the proposal and retaining history. It does not use a
model or validate whether the coach's substantive inference is scientifically
sound; that remains your responsibility. A routine daily/weekly invocation has
standing authorization to persist this validated decision. Do not require
manual reconstruction or a second routine acceptance.

Proposal fields:

- `workflow`: `weekly|daily`; `as_of`: context's local ISO date.
- `evidence_hash` and `expected_revision_id`: exact values from the fresh context
  (`null` is valid only when no agent revision exists).
- `idempotency_key`: stable identifier; `summary` and `rationale`: actual decision.
- `source_ids`: nonempty list of read, relevant KB `Sxxx` IDs (up to twelve).
- `review`: strings `actual_vs_plan`, `progression`, `recovery`, `symptoms`,
  `strength`, `weekly_strategy`; arrays `uncertainty`, `follow_up`, `evidence`.
  Evidence entries should identify the claim, actual activity/check-in IDs or
  recovery dates, the KB policy/evidence/source IDs used, and the inference.
- `sessions`: weekly contains each run-parity date in `as_of..as_of+13`; daily
  is `[]` for no change or a bounded patch of affected run slots in that window. Each has `date`,
  `kind: run`, and `target` with `intent: easy|quality|long|rest`, `purpose`,
  `prescription`, `intensity`, `reason`, and concrete `duration_minutes`,
  `distance_km`, with `steps` additionally specifying repetitions where applicable. Use the returned schema
  for step/target details. Rest must be justified rather than silently omitted.

Full weekly planning preserves accepted dates outside the horizon and historical
completion links; strength/mobility remain separate commitments. Daily decisions
require an existing accepted running plan and retain its weekly strategy. They
may patch affected future run slots while retaining all untouched sessions,
weekly strategy, and cadence. `sessions: []` records a
confirmation without manufacturing calendar edits. Repeat equivalent inputs do
not create duplicate revisions. The response returns `revision`, `plan`,
`unchanged`, and a reasoned calendar `diff`. Fetch fresh `today`/`review-week`
afterward to verify the saved active sessions.

HTTP 409 stops. For stale evidence or a revision conflict, reread observations,
then reconsider and construct a new proposal. After a timeout, `inspect` first;
retry only the identical payload/key when the result remains uncertain. Do not
blindly rebase a rejected proposal or regenerate a new key for the same write.

## Inspect and revert

`inspect` GETs `/coach/agent/revisions`. Identify the current revision from fresh
context, inspect the revision being undone, then, for an explicit rollback
request, run:

```sh
python3 "$HELPER" revert --revision REVISION_UUID --expected-revision CURRENT_UUID --reason 'Athlete requested the prior prescription'
```

This POSTs `/coach/agent/revisions/{id}/rollback` with `expected_revision_id`
and `reason`. Rollback is version checked and records history; verify the
returned diff and active context. Do not promise removal of actual training,
feedback, or historical evidence.

## Check-ins and completion

Create a private JSON payload and use `checkin --file /absolute/path/checkin.json`.
It POSTs `/checkins`. Required: stable `idempotency_key`, offset-aware
`observed_at`, `symptoms: none|mild|moderate|severe`,
`gait: normal|affected|unsure`, `feeling: fresh|usual|tired`. Optional:
`change: better|same|worse|unsure`, `effort` (0–10), `activity_id`, `note`
(max 4000). Symptoms/energy without a gait report do not establish normal gait.
Illness, soreness, clinician restrictions and delayed timing belong in the note.
Corrections use the app UI. Fetch fresh context after saving.

`link-completion --file /absolute/path/link.json` POSTs `/completion-links`.
Body: `planned_session_id` plus exactly one of `activity_id` or
`manual_session_id`. Use only an unambiguous actual match or the athlete's
explicitly selected match. A daily note alone is not a completion. The API
rejects duplicate links; after an ambiguous request inspect plan context before
retrying. Completion links and later reported check-ins flow into future reviews.
Never record outcomes on unrelated legacy local-rule recommendations.

## Durable memory

`profile` reads the full profile. `remember --file /absolute/path/entry.json`
appends to `profile.facts.coach_memory = {"schema_version": 1, "entries": [...]}`.
Required: stable UUID `id`, `kind: athlete_fact|goal|preference|review|follow_up`,
offset-aware `recorded_at`, and nonempty object `content`. Optional `supersedes`
references an existing entry. Keep facts concise, sourced, and dated with units;
include timeframe/status for agreed goals. Derive age from birth date when
needed rather than storing an aging integer. Plan review revisions remain the
primary structured coaching record.

The helper preserves all profile/schedule fields and PUTs `/profile` with
`expected_version`. An identical entry ID/content is a no-op; a changed payload
under the same ID fails. On a conflict reload before retrying. After a timeout
read the profile to check the original ID. Profile writes may stale existing
advice; fetch new context before another running decision. Do not silently
change goals, cadence, or confirmed strength configuration through memory.
