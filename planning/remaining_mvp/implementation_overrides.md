# Current user implementation priorities — 2026-11-12

Latest user instruction overrides earlier compatibility/staging constraints in task packets:

“continue implementing until done … batch [decisions] up and keep implementing until actually blocked … don't worry about things like backwards compatibility … breaking temporarily for faster iteration is totally fine … quickest path to the working end to end behavior … use this for my training”.

Proceed autonomously on ordinary engineering decisions. Batch high-impact scope/behavior choices through the question tool; continue independent work until an answer is truly required. No repeated blanket approval gates.

Prioritize calendar → exception check-in → Codex pending changeset → review/accept → persisted updated training plan, followed by complete deterministic evidence/metric integration. Temporary local breakage and direct replacement of old interfaces are authorized. Old API/helper/UI compatibility adapters, staged navigation and elaborate old-interface rollout tests are not release requirements. Retain useful work already implemented; do not rewrite working foundation merely to remove compatibility.

Actual training data preservation remains required: do not discard activities, recovery, confirmed schedules, plans or links. Back up before real schema migration. Immutable new review lineage, explicit acceptance, source freshness, idempotency, protected completed facts and missing-data correctness remain functional requirements. Preserve old stored history without requiring an elaborate legacy UI/undo adapter to ship the new workflow.

Root may merge complete functional slices to main and perform required local additive migration/setup after verification. No push, remote deployment or external messaging authorized. Real-device evidence is still honestly reported; missing evidence is not fabricated. Synthetic checks and user-readable missing outcomes allow independent implementation to proceed.

## Release integration amendments — 2026-11-12

Valid research routing can exceed the inherited 70,000-character legacy context
limit: the richer synthetic rolling snapshot selected 111,101 characters, and
the largest permitted verified selection across six operations measured 158,458.
The reviewed route/selection path uses a separate finite 180,000-character cap;
legacy loading retains 70,000. Per-file size/hash checks, explicit overflow
failure, budget warnings, and all selected evidence remain intact. No silent
truncation or safety-topic dropping is allowed. This is an implementation
correction to make the defined full-topic routing usable, not a new product
choice requiring athlete approval.

Final integration also includes imported prescription notes in Activity details,
a read-only fallback for historical linked imports outside current membership,
and calendar-mode production browser verification. Legacy undo adaptation
remains deferred as authorized above.


Full-history release validation found that embedding the full source-version
vector in the model payload produced roughly 396k daily / 411k rolling tokens.
The external snapshot now uses `snapshot_meta.source_provenance` with a SHA256
and per-collection kinds/counts. `CoachSnapshot.source_versions` retains the
complete vector, and canonical source fingerprints, safety checks, acceptance
validation, and metric explanations are unchanged. Real snapshots measured
11,971 daily and 26,964 rolling proxy tokens after this correction. This
representation change replaces the earlier full-vector payload requirement.
