# TASK-063 — Coach API: proposals list/detail/decision (daily guidance remains owned by TASK-013)


Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce + merged dependencies per dependency_graph.md; spec planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag
Wave / priority: P0-B; wave 9 (dependency_graph.md).
Dependencies: TASK-061, TASK-062; all earlier DAG dependencies remain required.
File ownership: create `backend/app/api/coach.py`, `backend/tests/integration/test_coach_api.py`
Forbidden changes: `backend/app/main.py` (router registration is TASK-064), `backend/app/services/**`, `backend/app/cli.py`, models, migrations. No snapshot or submit routes (CLI-only, `schemas.md` §3.5).

## Objective and observable end state
`APIRouter(prefix="/coach")` with the four routes of `schemas.md` §3.5. Example: a pending proposal with changes c1, c2, c3; `POST /api/v1/coach/proposals/{id}/decision` with `{"expected_head": 7, "accept_change_ids": ["c1","c3"], "reject_change_ids": ["c2"]}` → 200, `data.status == "partially_accepted"`, `data.calendar_version == 8`.

## Inputs and fixed contracts
- `schemas.md` §0 (envelope, errors via `fail()`), §2.3, §2.6, §3.5; `coaching_contract.md` §5.
- `app.api.core.envelope(session, data)`, `app.api.core.fail(code, message, status)`; `app.db.get_session`.
- `app.services.proposals`: `DecisionRequest`, `DecisionError`, `decide_proposal`, `anchor_key`, `session_fields`, `load_context` (TASK-061).
- `app.services.timezone.athlete_tz`, `local_date`.

## Implementation procedure
1. Define resolve_kb(selection)=VerifiedKnowledge(**knowledge.verify_selection(selection)); import VerifiedKnowledge from decision_inputs and knowledge from services. Create `backend/app/api/coach.py` with `router = APIRouter(prefix="/coach", tags=["coach"])`.
2. Helper `proposal_summary(p) -> dict`: `{id, operation, status, submitted_at, decided_at, summary, base_calendar_version, change_count}`.
3. Helper `proposal_detail(session, p) -> dict`: all `coach_proposals` columns except `payload`, `input_hash` (keys: `id, operation, snapshot_id, status, submitted_at, decided_at, summary, rationale, confidence, evidence_ids, policy_ids, recipe_ids, follow_up, escalation, base_calendar_version, base_block_version_id, block_change, validation_errors, skill_version`) plus:
   - `anchor_changes`: each stored item plus `anchor_key` (computed with `proposals.anchor_key` using a `AnchorChange.model_validate(item)` and `athlete_tz(session)`).
   - `head`: current `AppState.calendar_head_version`; `is_current`: status pending with matching head/block and collector fingerprint/KB digest.
   - `changes` (ordered by numeric part of `change_id`): `{change_id, op, session_uid, before, after, reason, decision, material_flags, current}`; `material_flags` from `p.payload["changes"]` item with the same `change_id` (default `[]`); `current` = `session_fields(...)` of that `session_uid` in the current head state, or `None` (add, or deleted at head). Load `snapshot=session.get(CoachSnapshot,p.snapshot_id)` from app.coach_v2_models, then use `proposals.load_context(session, p.snapshot_id, now=datetime.now(UTC), kb=resolve_kb(tuple(snapshot.kb_routes))).head_sessions` for the head state.
4. `GET /proposals` — query `status: Literal["pending","accepted","partially_accepted","rejected","stale","invalid"] | None = None`; newest `submitted_at` first, limit 50 → `envelope(session, {"items": [proposal_summary...]})`.
5. `GET /proposals/{proposal_id}` (`uuid.UUID`) → `envelope(session, proposal_detail(...))`; missing → `fail("proposal_not_found", "Proposal not found", 404)`.
6. `POST /proposals/{proposal_id}/decision` body `proposals.DecisionRequest`:
   ```python
   try:
       result = decide_proposal(session, proposal_id, body, now=datetime.now(UTC), resolve_kb=resolve_kb)
   except DecisionError as exc:
       if exc.commit: session.commit()
       else: session.rollback()
       raise HTTPException(exc.http_status, detail={"code": exc.code, "message": exc.message, "fields": exc.fields})
   session.commit()
   return envelope(session, {"proposal_id": result.proposal_id, "status": result.status, "calendar_version": result.calendar_version, "block_version_id": result.block_version_id, "anchor_keys": result.anchor_keys, "stale_proposals": result.stale_proposals})
   ```
   Status200. Preserve structured code/message/fields; TASK064 extends main handler to retain fields. Do not drop errors or compress them into one issue.
8. Do not edit `main.py`. Tests mount the router on their own app (below).

## Tests and expected results
`backend/tests/integration/test_coach_api.py` (`pytestmark = pytest.mark.integration`). Fixture `client`: rollback-isolated connection exactly like the existing `tests/integration/test_coaching.py::coach_client` (savepoint session override of `get_session`), but the app is `test_app = FastAPI(); test_app.include_router(coach.router, prefix="/api/v1"); test_app.add_exception_handler(HTTPException, app.main.handle_http); test_app.add_exception_handler(RequestValidationError, app.main.handle_validation)`. Seed helper `seed(session)` inserts directly via models: profile (America/New_York, anchor = today, confirmed); `AppState.calendar_head_version = 7` with `calendar_versions` 1…7; head sessions: runs at today+2, today+4, today+8 (REC001, 1800 s), strength on every Monday and every Friday dated today…today+13; `w2 = (today+7) - timedelta(days=(today+7).weekday())` (Monday of a week fully inside the scope); a `CoachSnapshot` (op `review_rolling_plan`, `generated_at = now-1h`, payload `{"snapshot_meta": {"safety_guard": {"window_hours": 72, "gait_change_yes": false, "max_symptom_severity": null, "illness_present": false, "clinical_restriction_active": false,"legacy_safety_active":false}}}`); proposals inserted through `proposals.submit_proposal(..., resolve_kb=verified_fixture_resolver)`. Names marked * are binding (`acceptance.md` §4).
- `test_partial_accept_writes_version_with_lineage`* : proposal c1 modify today+2 `planned_duration_s` 2100, c2 modify today+4 `intent`, c3 modify today+8 `planned_duration_s` 1500; decision accept c1, c3 / reject c2 → 200, `status == "partially_accepted"`, `calendar_version == 8`; DB: version 8 `kind="proposal_accept"`, `actor="coach"`, `parent_number == 7`, `proposal_id` set; 2 revision rows at version 8 with `revision == 2`; today+4 session unchanged; change decisions `accepted/rejected/accepted`.
- `test_reject_all_recorded`* : same proposal, accept `[]`, reject all → `status == "rejected"`, `calendar_version is None`, head still 7, 0 rows in `calendar_versions` with `number == 8`.
- `test_accept_stale_409`* : insert calendar version 8 and set head 8 after submitting; decision → 409 `error.code == "proposal_stale"`; proposal row status `stale` persisted (read via a fresh query in the same connection after the request).
- `test_accept_block_change_appends_decision`* : snapshot + proposal op `review_training_block`, `changes: []`, block_change `start` (eligible REC001, REC002, REC003, start today, review today+42); decision `accept_block_change: true` → `status == "accepted"`, `calendar_version is None`, `block_version_id` set; 1 `blocks`, 1 `block_versions` (version 1, status active), 1 `block_decisions` (`decision == "start"`, `from_version is None`, `to_version == 1`).
- `test_empty_proposal_accept`: proposal with `changes: []`, no block/anchors; decision with empty lists → `status == "accepted"`, `calendar_version is None`.
- `test_decision_incomplete_422`: c1, c2 proposal; accept `["c1"]`, reject `[]` → 422 `decision_incomplete`; nothing written.
- `test_subset_invalid_422`: proposal c1 add strength at `w2+2` (intent "Full body"), c2 delete the strength session at `w2+4`; accept c2 only → 422 `proposal_invalid_subset`, message contains `V9.strength_count`; head unchanged.
- `test_detail_includes_current_and_flags`: GET detail → `changes[0].current.planned_duration_s == 1800`, `material_flags == []`, `is_current is True`; list endpoint with `status=pending` returns it.
- `test_no_snapshot_or_submit_routes`* : `POST /api/v1/coach/snapshot` → 404 or 405; `POST /api/v1/coach/submit` → 404 or 405; no route path in `coach.router.routes` contains `snapshot` or `submit`.
Commands: `make test-integration` (runs `pytest tests/integration` in test mode); `make check`.

## Acceptance checklist
- [ ] 10 tests pass; binding names verbatim; `make check` green.
- [ ] Errors use `{code, message}` detail dicts (no string `HTTPException` details); no edits outside the two owned files.

## Completion report
Changed files; test output; proposal field-error and replay response samples; blockers.

## Escalation rule
If an exact file/function/contract differs from the pinned source or a requirement is underspecified, STOP and return a short blocker. Do not invent a new schema, behavior, dependency, UX, or alternative implementation.

## Coexistence and replay
TASK013 exclusively owns GET /coach/v2/daily and its created_at ordering; do not register another daily handler here. Remove the daily-route procedure/tests from this packet and test only the proposal routes here. Existing GET /coach/daily retains its legacy DTO. DecisionRequest includes idempotency_key; API returns stored result on identical terminal replay,409 decision_conflict on changed terminal decision. Mutating proposal decision endpoints require calendar authority; before068 ->409 planning_not_active. Read routes return an inspectable immutable projection. Source/safety validation delegates061 inside transaction; no endpoint-side duplicate validation.
