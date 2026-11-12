# TASK-064 — Integration: `coach snapshot|query|submit` CLI, coach router registration, staleness wiring, retain legacy readers

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce + merged dependencies per dependency_graph.md; spec planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag
Wave / priority: P0-B; wave 10 (dependency_graph.md).
Dependencies: TASK-062, TASK-063; all earlier DAG dependencies remain required.
File ownership: `backend/app/cli.py`, `backend/app/main.py` (router registration and preservation of structured error fields), `backend/app/services/calendar.py` (staleness call only), `backend/tests/integration/test_coach_cli.py` (create)
Forbidden changes: everything else, including `services/snapshot.py`, `services/proposals.py`, `services/knowledge.py`, `api/coach.py`, conflicts routes (kept), models, migrations, frontend.

## Objective and observable end state
`./scripts/with-mode test bash -c 'cd backend && uv run python -m app.cli coach snapshot --operation review_rolling_plan'` prints `{snapshot_id, payload, kb, approx_tokens}` and exits 0; `coach submit --file p.json` prints `{proposal_id, status, errors}` and exits 0/2/3; KB tampering → exit 4. `GET /api/v1/coach/proposals` is served by the main app. A manual calendar edit marks pending proposals `stale` and lists them in `stale_proposals`. `export-context`, GET /context and services/summary.py remain operational for current consumers.

## Inputs and fixed contracts
- `schemas.md` §5 (commands, args, exit codes 0/1/2/3/4), §3.1 (`stale_proposals` in edit/rollback responses); `coaching_contract.md` §5.4, §6.2 (integrity → exit 4).
- `app.services.snapshot.build_snapshot, DRILL_DOWN_QUERIES` (TASK-062); `app.services.proposals.submit_proposal, mark_pending_stale; app.services.decision_inputs.VerifiedKnowledge` (TASK-061); `app.services.knowledge.verify_selection, SUPPORTED_OPERATIONS, KnowledgeIntegrityError` (TASK-060; `KnowledgeIntegrityError` subclasses `ValueError`, so catch it first); `app.api.coach.router` (TASK-063); `app.services.timezone.athlete_tz, local_date`.

## Implementation procedure
1. `backend/app/cli.py` `_parse()`: retain the `export-context` parser. Add `coach = sub.add_parser("coach")`, `coach_sub = coach.add_subparsers(dest="coach_command", required=True)`:
   - `schema`: no arguments; output `{protocol:"coach_proposal.v1",activation:"manual",required_authority:"calendar",proposal:ProposalDoc.model_json_schema()}` from services/proposals.py, exit0, no DB/network.
   - `snapshot`: `--operation` (required, `choices=SUPPORTED_OPERATIONS`), `--as-of` (`type=date.fromisoformat`, default None).
   - `query`: positional `name` (`choices=DRILL_DOWN_QUERIES`); `--activity-id` (`type=uuid.UUID`), `--start`, `--end` (`date.fromisoformat`), `--from` (`dest="from_version"`, int), `--to` (`dest="to_version"`, int), `--result-id` (`type=uuid.UUID`).
   - `submit`: `--file` (`type=Path`, required).
2. `main()`: retain the `export-context` branch. Add `elif args.command == "coach": return _coach(args)` before the generic handling.
3. Add `_coach(args) -> int`. `now = datetime.now(UTC)`. Wrap the body: `except KnowledgeIntegrityError` → stderr `{"error": "knowledge_unavailable"}`, return 4; `except Exception` → stderr `{"error": "unexpected_error"}`, return 1 (never print exception text).
   - **schema**: print `{protocol:"coach_proposal.v1",activation:"manual",required_authority:"calendar",proposal:ProposalDoc.model_json_schema()}` as JSON, return0; do not open DB.
   - **snapshot**: `with SessionLocal.begin() as session:` `as_of = args.as_of or local_date(now, athlete_tz(session))`; `result = build_snapshot(session, args.operation, as_of, now=now)`. After the block commits: `print(json.dumps(result, default=str, ensure_ascii=False))`; return 0.
   - **submit**: read file; `json.JSONDecodeError`, `OSError`, or not a dict → print `{"proposal_id": null, "status": "invalid", "errors": [{"code": "V1.schema", "path": "", "message": "File is not a JSON object"}]}`, return 2. `resolve_kb = lambda selection: VerifiedKnowledge(**knowledge.verify_selection(selection))`; `with SessionLocal.begin() as session: res = submit_proposal(session, raw, now=now, resolve_kb=resolve_kb)`. Print `{"proposal_id": str(res.proposal_id) or null, "status": res.status, "errors": [i.to_json() for i in res.issues]}`; return 0 for `pending`, 3 for `stale`, 2 for `invalid`.
   - **query** (`with SessionLocal() as session:`, read-only). Required args per name, missing → stderr `{"error": "missing_argument", "message": "<flag> required"}`, return 2. Call the existing route handler function directly, passing **every** parameter of its signature explicitly (FastAPI `Query()` defaults are not resolved outside a request) and `session=session`, then use `["data"]`:
     Import exact plain read exports from app.api.metrics (TASK030), with no FastAPI dependency defaults: activity_execution(session,activity_id:UUID), recovery_nights(session,start:date,end:date), explain_metric(session,result_id:UUID), long_run_history(session,start:date,end:date). Each returns data directly (not envelope). Long-run helper selects current dependency-valid long_run_exposure activity results only and excludes not_long/unknown. Do not query obsolete metric rows directly. calendar_diff uses TASK012 calendar_diff(session,from_version:int,to_version:int) -> dict.
     An `HTTPException` from a handler: status 404 → stderr `{"error": <detail code>}`, return 4; other → return 2. Success → print `{"query": name, "data": data}` (`default=str`), return 0.
4. In main.handle_http retain optional detail.fields in the error envelope (no change for responses without fields); test structured422 survives. Keep core.get_context, GET /context, services/summary.py, export-context, Makefile context target and all legacy consumer tests. Do not alter current /coach/agent writes in this task; TASK068 owns atomic authority cutover.
5. Register the new proposal router beside existing routers; no duplicate /coach/daily route. New /coach/v2/daily was registered by013.
6. Add coach CLI tests without deleting prior context checks. Context privacy rules remain unchanged until explicitly adapted; new compact snapshot privacy tests are separate.
7. `backend/app/services/calendar.py`: in each function that writes a `calendar_versions` row with `kind` `manual_edit` or `rollback`, after the new head is set and before return, add `from app.services.proposals import mark_pending_stale` (function-local import, avoids a cycle) and `stale = mark_pending_stale(session, except_id=None)`, and put `[str(x) for x in stale]` in the returned `stale_proposals`. If TASK-012 left a staleness hook (a function whose name contains `stale`), put the call in that hook's body instead and keep its callers. Touch nothing else in the file.

## Tests and expected results
`backend/tests/integration/test_coach_cli.py` (`pytestmark = pytest.mark.integration`). Fixture `cli_db(monkeypatch)`: `connection = engine.connect(); trans = connection.begin(); factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)`; `monkeypatch.setattr(app.cli, "SessionLocal", factory)`; override `get_session` on `app.main.app` with a savepoint session on the same connection; yield; `trans.rollback()`. Helper `run_cli(*argv)` sets `sys.argv = ["app.cli", *argv]`, calls `app.cli.main()`, returns `(code, json.loads(stdout) if stdout else None, stderr)` via `capsys`. Inline `seed(session)` (same data as TASK-063's seed: profile anchor = today confirmed, head 7, runs today+2/+4/+8 REC001 1800 s, strength every Monday/Friday in today…today+13, two strength routine slots Mon/Fri `moderate`), plus one exception check-in at `now-30h` with `note="cli-private-canary"`, symptom severity 2. Helper `proposal(snapshot, **over)` returns a valid rolling doc (c1 modify today+2 `planned_duration_s` 2100) written to `tmp_path`. Names marked * are binding (`acceptance.md` §4).
- `test_manual_edit_stales_pending_proposal`* : snapshot → submit (exit 0, `pending`); `POST /api/v1/calendar/edits` `{expected_head: 7, edits: [{op: "modify", session_uid: <today+4>, fields: {intent: "Moved by user"}}]}` → 201 and `data.stale_proposals == [proposal_id]`; proposal status `stale`.
- `test_resubmit_same_file_idempotent`* : submit the same file twice → same `proposal_id`, 1 `coach_proposals` row.
- `test_snapshot_twice_same_payload_hash`* : two `coach snapshot --operation review_rolling_plan` → different `snapshot_id`, equal `payload_sha256` in `coach_snapshots`, `data_revision` unchanged.
- `test_submit_invalid_exit_2_nothing_written`* : doc with `"extra_field": 1` → exit 2, `status == "invalid"`, `proposal_id is None`, `errors[0].code == "V1.schema"`, 0 proposal rows; daily snapshot + doc modifying today+4 → exit 2, `errors[0] == {"code": "V5.out_of_scope", "path": "changes.0", ...}`; calendar head still 7 in both cases.
- `test_submit_stale_exit_3`* : snapshot; manual edit via API (head → 8); submit doc with base 7 → exit 3, `status == "stale"`, `errors[0].code == "V3.stale_base"`.
- `test_snapshot_kb_integrity_exit_4`* : copy KB to `tmp_path`, append one byte to `workflows/weekly_review.md`, `monkeypatch.setattr(knowledge, "DEFAULT_ROOT", tmp_copy)` → snapshot exit 4, stderr `error == "knowledge_unavailable"`, 0 `coach_snapshots` rows; submit with the same tampering → exit 4.
- `test_kb_failure_does_not_affect_metrics_api`* : same tampering → `GET /api/v1/metrics/windows` → 200.
- `test_snapshot_excludes_checkin_notes`: snapshot `review_rolling_plan` stdout does not contain `cli-private-canary`, and `payload.symptoms.reports` has the severity-2 report.
- `test_coach_router_registered`: `GET /api/v1/coach/proposals` via `app.main.app` → 200, envelope `schema_version == "v1"`.
- `test_query_commands`: `coach query calendar_diff --from 6 --to 7` → exit 0, `data` has key `changes`; `coach query activity_execution` (no id) → exit 2, `missing_argument`.
- `test_export_context_removed`: `run_cli("export-context", "x.json")` raises `SystemExit` with code 2 (argparse); `GET /api/v1/context` → 404 (SPA catch-all returns HTML or 404 — assert the response is not a JSON envelope with `context_version`).
Commands: `make check`; `make test-integration`; `./scripts/with-mode demo bash -c 'cd backend && uv run python -m app.cli coach snapshot --operation proceed_or_modify_today'` on a seeded demo DB → exit 0 (record `approx_tokens`).

## Acceptance checklist
- [ ] 11 tests pass (binding names verbatim); `make check` and `make test-integration` green.
- [ ] `rg -n "export-context|build_context|get_context" backend scripts Makefile` → no output; `backend/app/services/summary.py` absent.
- [ ] Conflicts routes untouched; `git diff --stat` shows only owned files.

## Completion report
Changed/deleted files; test and command output (incl. demo `approx_tokens`); exact shared read exports used; blockers.

## Escalation rule
If an exact file/function/contract differs from the pinned source or a requirement is underspecified, STOP and return a short blocker. Do not invent a new schema, behavior, dependency, UX, or alternative implementation.

## Authority and immutable snapshot guard
CLI submit creates pending proposals only; no activate/accept command. Decision endpoint is the only approval path. CLI snapshot includes source_fingerprint/kb_digest; failures never fall back to old automatic submit. Test legacy context/agent reads alongside new snapshot. CLI errors preserve field paths and exit codes; stale input exits3, no automatic resubmission. All commands select explicit same GB_MODE; fixtures set calendar authority, real writes remain gated until068.
