# TASK-010 — Persist idempotent FIT ingestion and fix sync timezone/retry isolation

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce; manager-supplied dependency-complete gb-mvp1-* tag; planning/remaining_mvp MVP-1.0
Wave / priority: P0-A; wave 1a (dependency_graph.md).
Dependencies: TASK-003, TASK-004; TASK-002 already delivered
File ownership: Create backend/app/services/fit_ingest.py; modify backend/app/services/sync.py, backend/app/adapters/garmin/normalize.py, backend/app/services/export_import.py; create backend/tests/unit/test_fit_ingest.py and backend/tests/integration/test_fit_ingest.py.
Forbidden changes: No decoder/schema/CLI/router/frontend/dependency edits. No actual fit-backfill invocation or G2 claim. API duration is not promoted without approved field evidence.

## Objective and observable end state
Run ingestion stores raw ZIP privately and canonical decoded facts once per SHA. Repeated ingestion preserves IDs/source revisions; isolated failure does not lose working decoded facts or abort page neighbors.

## Inputs and fixed contracts
schemas§§2.1,6.2; FitSource Protocol.download_activity(activity_id:str)->bytes; ingest_activity_fit(session:Session,source:FitSource,private_dir:Path,activity:Activity)->str (fit status), never commits. backfill_fit(session_factory,source,private_dir:Path,since:date)->dict counts attempted/decoded/unavailable/failed; one transaction per run, returned errors use codes only. fit files retain successful identity and separate last attempt/error fields from003. Raw ZIP hash separate from extracted FIT SHA. GarminRemoteError.status_code404→unavailable only if no prior decode.

## Implementation procedure
1. Resolve remote provider activity ID through ActivitySource/SourceRecord provenance, never assume internal UUID is Garmin ID; missing/ambiguous remote ID records failure code without API call. Download before replacing canonical rows. Use byte-safe private store helper in this module preserving digest path0600/parent0700; `.zip` suffix, atomic replace/link+hash verification, never JSON encode bytes.
2. Create/find RawObject by SHA and canonical relative path using existing model fields. Keep original SourceRecord/activity-source chain unchanged. Extract/decode with004. Save ZIP identity+last attempt on failure, extracted SHA only when extraction succeeds. Existing good decode remains fit_status decoded with last_error set; initial404 unavailable, initial decode failure decode_error.
3. Success: lock activity; same FIT SHA + decoded_at skips replacement and source revision bump. Otherwise replace lap/step/stream rows delete+insert in same transaction; update Activity timer/end/RPE/feel/status and FitFile decoder metadata. end_at=start_at+elapsed when known; never use timer duration as wall end. Session-start mismatch to Activity start must be recorded as FIT_START_MISMATCH and withhold attaching stream (decode_error) rather than shifting offsets.
4. Upsert source garmin_fit RPE only when decoded valid RPE exists, collected_at=end_at (if absent use session start+elapsed only; no invented timestamp, omit RPE if end unknown). Manual source remains effective. On replacement FIT with RPE missing, remove prior garmin_fit row to avoid stale value, never manual row.
5. `_reconcile` retains FIT timer_s and its provenance when fit_status decoded so summary sync cannot oscillate canonical_revision. CanonicalActivity add nullable timer_s last, but parse_activity leaves it None until G2 explicitly verifies API duration semantic mapping. Resolve import_activity_page timezone defaultNone from athlete_tz(session); sync calls pass athlete timezone key. import_export timezone defaultNone resolves same; explicit overrides still honored.
6. `run_one_job` initialize job_id=None before try; assign immediately after loading job, before error-prone source calls. Failure handler uses loaded ID only, otherwise re-raises original error safely. Add ReadTimeout retry class preserving retry bounds. After each activity-page commit, identify run rows from that page and open one session/try-except per FIT ingest; failed decode affects its row only. Never nest FIT network calls in the committed page transaction.
7. Implement backfill service filtered since and not_fetched/decode_error; no CLI ownership. TASK030 wires CLI. Mark affected source revision once on changed decode;030 later installs metrics invalidation. Tests use fake source and synthetic raw store tempdir.

## Tests and expected results
`cd backend && uv run pytest tests/unit/test_fit_ingest.py` covers fake404, timeout classification, tz propagation and job failure before ID.
`./scripts/with-mode test bash -c 'cd backend && uv run pytest tests/integration/test_fit_ingest.py -m integration'`: first fixture ingest588 records+2laps+4steps+RPE6.5; identical replay same counts/IDs/source revision; changed valid FIT atomically replaces; injected flush exception rolls everything back; corrupt retry preserves good decode and records error; initial corrupt→decode_error with ZIP hash. Manual RPE7 persists and wins over6.5. Three-activity page with middle failure ingests first/third. Asia/Tokyo explicit profile around UTC midnight assigns correct local date; DST test uses timezone helper. Raw path permissions0600 and hash exact bytes.

## Acceptance checklist
- [ ] Raw/source provenance and successful decode survive failures.
- [ ] Idempotent SHA ingestion and manual RPE precedence.
- [ ] Each activity transaction isolated, no implicit commit in service.
- [ ] CLI/live backfill/device evidence deferred explicitly.

## Completion report
List changed paths, exact test commands actually run and their outputs, fixture coverage, remaining device gates and blockers. No real athlete data, invented verification or design essay. Include baseline/runtime tag and resulting schema head when relevant.

## Escalation rule
If the pinned source or an exported contract differs, STOP with the exact path/signature and a short blocker. Do not invent schema, physiology, DTO, migration, UX, field observation or dependency. Historical handoff notes do not override this packet or schemas §§6–7. Tests use synthetic fixtures and a guarded disposable TEST_DATABASE_URL only; no real-mode startup, live Garmin or athlete DB. Planning approval is required before implementation begins.
