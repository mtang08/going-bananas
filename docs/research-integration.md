# Research integration (updated 2026-11-11)

## Periodization extension

Imported the supplied `1.1.0+privacy1` incremental package after verifying all
28 payload sizes and SHA-256 hashes against its schema 1.1 manifest: 12 changed
or added files and 16 unchanged public baseline files. Nine files are new;
README, coaching guide, and source registry are replaced. All 56 existing source
records remain identical; 16 are added. The resulting corpus has 72 sources,
55 evidence findings, 23 candidate policies, 26 evaluation cases, 11 topics,
three workflows, and ten session-family recipes.

The supplied manifest SHA-256 is
`ad34cc383230226652202e8d6e18c8ef943a46e90c34b0a3fa55392f59215a4a`.
Its exact bytes and the previous public manifest are preserved under ignored
`private/real/research-imports/periodization-20261111/`. The public manifest
retains the original privacy-transform provenance as history and records this
incremental import separately. All payloads remain byte-identical to the
supplied manifest; `.DS_Store` and private athlete snapshots are excluded.
New evaluation athletes are explicitly fictitious, and the content describes
general methods and uncertainty rather than current athlete observations.

This imports reference knowledge about optional blocks, intensity calibration,
session families, race transitions, and tapering. It does not activate candidate
policies, create blocks or anchors, change daily/weekly default topic selection,
or update saved training. Current user and application instructions govern
persistence; historical proposal-approval language in the KB does not replace
the active workflow contract.

Verification passed: 17 focused backend tests, 13 helper tests, Ruff, and mypy
across all 36 application files. The installed helper and app-access reference
were updated after private backup and byte verification. After the API restart,
read-only readiness and real daily/weekly agent-context checks reported the KB
available at `1.1.0+privacy1`; context lengths were 59,233 and 59,212 characters,
within the 70,000-character bound. Installed-helper block retrieval selected the
periodization topic, P019, REC001, and S057 successfully. These checks made no
database or plan mutations. The three incoming README Markdown hard-break
whitespace warnings are retained to preserve supplied payload checksums.

## Import and provenance

The supplied ZIP was inspected before extraction: all entries were under
`running_coach_kb/`, with no duplicate names, traversal, symlinks, or oversized
members. All 20 checkable file lengths and SHA-256 hashes matched the supplied
manifest. The four standalone Downloads files were byte-identical to their ZIP
counterparts. Original ZIP, standalone files, and the dated athlete snapshot are
preserved under ignored `private/real/research-imports/`.

The reviewed, enduring corpus is in `running_coach_kb/`. Personal athlete
observations, exact past paces, dates, and schedule particulars were changed to
conditional examples; the dated `athlete_context.md` is private only. The initial local
manifest was version `1.0.0+privacy1`. Its retained `import_provenance` records the
original archive and manifest hashes plus every changed file's original and
imported hashes. The original manifest remains private. This preserves the
source snapshot while making the tracked corpus safe for routine development.
The imported research remains a targeted review with explicit gaps, not a
systematic review. Individual applicability must still be assessed against live
data and current user or clinician instructions.

## Selective loader

`app.services.knowledge.load_knowledge(workflow, topics=(), policy_ids=(),
source_ids=(), *, recipe_ids=(), root=None)` accepts `daily`, `weekly`, or
`block`. Topic names are the eleven `topics/*.md` stems. Policy, source, and
recipe IDs must exist in the imported
records. It returns `KnowledgeContext` with `text`, `package_version`,
`searched_through`, `selected_files`, `integrity_ok`, `policies`, `sources`, and
`recipes`.
The prose is ordered guide → one workflow → selected topic guides → selected
candidate policy summaries → selected source references → selected full recipe
records. Requests are bounded to four topics, eight policies, twelve sources,
three recipes, and 70,000 characters. All read
files are checked against the local manifest; unknown IDs, unsafe paths, and
changed files fail closed. No athlete snapshot, full report, model call, network
call, or current training state is loaded by this function. Recipes are absent
unless explicitly selected. The helper's `knowledge --workflow block` and
`--recipes REC001` flags expose this research without API/database access.
Retrieval still uses whole topic/workflow files rather than heading-level
routing; the manifest's section-based token estimates are not runtime guarantees.
Evidence addenda and evaluation documents remain inspectable repository files,
not selectable loader arguments. These retrieval limitations and future block,
anchor, and race product features remain for the forthcoming implementation plan.

The caller supplies current athlete facts and app-computed metrics separately.
The KB cannot confirm that an old symptom pattern, strength day, run frequency,
or race goal still applies. The caller should keep policy/evidence IDs in each
recommendation's audit trail and cite the relevant source only when useful.

## Initial integration scope and case coverage (historical, November 10)

The following describes the original deterministic coaching endpoints. Current
Codex-driven daily/weekly planning and automatic persistence are documented in
[the P0 implementation](p0-implementation.md). The KB import adds retrieval only;
neither the 15 baseline nor the 11 incremental research cases imply implemented
product behavior or complete automated coverage.

The active runtime is **local evidence-guided decision support**, with no
external model call. It chooses conservative daily options and a weekly
proposal from current input state, recorded sessions, accepted plans, and
selected guide/workflow/topic prose. Candidate policies P001–P018 are
explanatory aids, not blanket executable rules. A proposal requires user
acceptance and never mutates a plan by itself.

Implemented branches handle unknown symptom or clinician state conservatively;
current worsening/function limits; missing recovery data; mild illness as a
conditional return question; and known strength soreness around a proposed
session. The runtime records outcomes and marks saved advice stale when its
inputs change. The targeted endpoint and browser tests in the release checklist
verify those behaviors; they do **not** execute every variant of all 15 supplied
behavioral cases.

The 15 cases in `running_coach_kb/evaluation/coaching_cases.md` remain an
evaluation set. In particular, delayed multi-day symptom response, a calibrated
favorable progression (case 15), exact session dose/placement, and full
outcome-event chronology in weekly review are unsupported. The current weekly
flow lacks 28-day and previous-14-day comparison metrics. Treat output as a
provisional option that may need fresh check-in or clinician input, never a
clearance, diagnosis, or rehabilitation prescription. Garmin readiness, HRV,
ACWR, a 10% progression rule, long-run share, and borrowed Achilles thresholds
are not used to clear or cancel training.

## Initial evidence check and limitations (historical, November 10)

Two crucial safety boundaries were checked against primary sources. The
[PTTD exercise systematic review](https://pmc.ncbi.nlm.nih.gov/articles/PMC6157513/)
reports sparse trials and missing exercise prescription parameters, supporting
the absence of a numeric PTT return-to-run rule. The
[IOC acute respiratory infection consensus](https://bjsm.bmj.com/content/56/19/1066)
supports a staged exercise challenge only for selected mild/resolving illness,
with concerning exertional symptoms prompting cessation and medical assessment.
These sources support cautious boundaries; neither establishes this athlete's
diagnosis or exact training dose.

To personalize a dated plan, the athlete should confirm the run-cycle anchor
and strength placement. For training-day advice, a fresh symptom/function
check and any current clinician restrictions matter. These are user inputs, not
development blockers: when unknown, the app can show conservative provisional
options and the missing-input list. Missing wearable fields, response calibration,
race date, and literature updates remain visible limitations.
