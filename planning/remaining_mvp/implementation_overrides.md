# Current user implementation priorities — 2026-11-12

Latest user instruction overrides earlier compatibility/staging constraints in task packets:

“continue implementing until done … batch [decisions] up and keep implementing until actually blocked … don't worry about things like backwards compatibility … breaking temporarily for faster iteration is totally fine … quickest path to the working end to end behavior … use this for my training”.

Proceed autonomously on ordinary engineering decisions. Batch high-impact scope/behavior choices through the question tool; continue independent work until an answer is truly required. No repeated blanket approval gates.

Prioritize calendar → exception check-in → Codex pending changeset → review/accept → persisted updated training plan, followed by complete deterministic evidence/metric integration. Temporary local breakage and direct replacement of old interfaces are authorized. Old API/helper/UI compatibility adapters, staged navigation and elaborate old-interface rollout tests are not release requirements. Retain useful work already implemented; do not rewrite working foundation merely to remove compatibility.

Actual training data preservation remains required: do not discard activities, recovery, confirmed schedules, plans or links. Back up before real schema migration. Immutable new review lineage, explicit acceptance, source freshness, idempotency, protected completed facts and missing-data correctness remain functional requirements. Preserve old stored history without requiring an elaborate legacy UI/undo adapter to ship the new workflow.

Root may merge complete functional slices to main and perform required local additive migration/setup after verification. No push, remote deployment or external messaging authorized. Real-device evidence is still honestly reported; missing evidence is not fabricated. Synthetic checks and user-readable missing outcomes allow independent implementation to proceed.
