# Research integration (2026-11-10)

## Import and provenance

The supplied ZIP was inspected before extraction: all entries were under
`running_coach_kb/`, with no duplicate names, traversal, symlinks, or oversized
members. All 20 checkable file lengths and SHA-256 hashes matched the supplied
manifest. The four standalone Downloads files were byte-identical to their ZIP
counterparts. Original ZIP, standalone files, and the dated athlete snapshot are
preserved under ignored `private/real/research-imports/`.

The reviewed, enduring corpus is in `running_coach_kb/`. Personal athlete
observations, exact past paces, dates, and schedule particulars were changed to
conditional examples; the dated `athlete_context.md` is private only. The local
manifest is version `1.0.0+privacy1`. Its `import_provenance` records the
original archive and manifest hashes plus every changed file's original and
imported hashes. The original manifest remains private. This preserves the
source snapshot while making the tracked corpus safe for routine development.
The imported research remains a targeted review with explicit gaps, not a
systematic review. Individual applicability must still be assessed against live
data and current user or clinician instructions.

## Selective loader

`app.services.knowledge.load_knowledge(workflow, topics=(), policy_ids=(),
source_ids=(), *, root=None)` accepts `daily` or `weekly`. Topic names are the
eight `topics/*.md` stems. Policy and source IDs must exist in the imported
records. It returns `KnowledgeContext` with `text`, `package_version`,
`searched_through`, `selected_files`, `integrity_ok`, `policies`, and `sources`.
The prose is ordered guide → one workflow → selected topic guides → selected
candidate policy summaries → selected source references. Requests are bounded
to four topics, eight policies, twelve sources, and 70,000 characters. All read
files are checked against the local manifest; unknown IDs, unsafe paths, and
changed files fail closed. No athlete snapshot, full report, model call, network
call, or current training state is loaded by this function.

The caller supplies current athlete facts and app-computed metrics separately.
The KB cannot confirm that an old symptom pattern, strength day, run frequency,
or race goal still applies. The caller should keep policy/evidence IDs in each
recommendation's audit trail and cite the relevant source only when useful.

## Current runtime scope and case coverage

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

## Evidence check and remaining work

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
