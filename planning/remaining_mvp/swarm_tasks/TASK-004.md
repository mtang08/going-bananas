# TASK-004 — Decode FIT into one frozen canonical contract and redacted inventory

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce; manager-supplied dependency-complete gb-mvp1-* tag; planning/remaining_mvp MVP-1.0
Wave / priority: P0-A; wave 0 (dependency_graph.md).
Dependencies: TASK-002 delivered; no G2 prerequisite for synthetic work
File ownership: Modify backend/app/adapters/garmin/personal.py; create backend/app/adapters/garmin/fit.py, backend/app/services/fit_inventory.py, backend/tests/unit/test_fit_decode.py, backend/tests/unit/test_fit_inventory.py, backend/tests/fixtures/fit/synthetic.py.
Forbidden changes: No schema, DB, sync, CLI, dependency or frontend edits. No live calls/device inventory during implementation tests. G2 real-device acceptance remains later.

## Objective and observable end state
Synthetic FIT ZIP decodes to588 samples, timer588s, distance1764m, RPE6.5, feel75, max_gap13; only canonical allowlisted stream values leave decoder. TASK010 consumes exactly this type.

## Inputs and fixed contracts
schemas§6.2 is complete dataclass/decoder API authority; no duplicated dictionary return shape. Copy the synthetic builder from swarm_tasks/_synthetic_fit_builder.py.txt (synthetic fixture only). SDK21.221.0 already locked. Wrapper names download_activity(id:str)->bytes, activity_workouts(id:str)->object, activity_detail(id:str)->object call existing _call(lambda:self._client.<method>(id)); underlying methods download_activity,get_activity_workouts,get_activity respectively. Shape errors use GarminConfigurationError; transport/re-auth unchanged.

## Implementation procedure
1. Add wrappers; assert download result bytes, otherwise invalid_fit_download_shape. Do not bypass _call token refresh or print response payloads.
2. Implement frozen dataclasses/extraction/decoder per§6.2, exactly chosen SDK flags. Use a fresh stream/Decoder for is_fit/check_integrity/read; SDK read errors yield decode_failed. Handle ZIP extraction bound by streamed byte count. Never extract member names to disk.
3. Read exactly one session and map run sport/subsport to canonical RUN_SPORTS. Map UTC start/lap timestamps, optional elapsed/timer/distance and values. Raw RPE65→6.5. Never use absent values as0. Inventory stores field names/counts, not raw messages.
4. Sort/dedupe stream channels and reconstruct timer segments/flags exactly§6.2; record/lap origins remain session start. Preserve watch step order by message_index and repeats as structural references; do not confuse watch structure with app execution reference. Numeric repeat fields are indexes/counts, not SI durations.
5. Device allowlist only manufacturer,product,software_version; exclude serials/names/positions and arbitrary unknown fields. Inventory API `merge_key_paths(values:Iterable[object])->dict[str,list[str]]` recursively records JSON type names at normalized paths; numeric/date-like object keys become <key>, array elements path[]. No values.
6. `build_inventory(decoded:DecodedFit, api_shapes:dict)->dict` emits schema_version fit_inventory.v1, sdk/profile versions, message counts, per-message field-name sets from sanitized decode inventory, record_interval_s(count/min/median/max/gaps_over_10s), timer segments, presence flags and normalized API shapes. Extend DecodedFit with `field_names:dict[str,tuple[str,...]]` if needed: this field is REQUIRED shared decoder output; update no private alternate type. `collect_inventory(source,activity_ids)->dict` downloads selected IDs via wrappers and aggregates redacted shapes; source supplied, no hidden client construction. CLI030 owns real-mode/empty-run enforcement.
7. Add fixtures for bad ZIP, zero/two FIT members, declared/actual oversize, garbage FIT, CRC flip, missing/multiple session, no records, duplicate records, absent enhanced channels, absent/ambiguous timer and repeats. Test sanitization recursively against canary123456789 and prohibited coordinate/secret keys in output, not a brittle ban on source-code words.

## Tests and expected results
`cd backend && uv run pytest tests/unit/test_fit_decode.py tests/unit/test_fit_inventory.py` (no DB/network).
Synthetic expectations: file_id1,event4,record588,lap2,session1,workout_step4; intervals[[0,300],[312,600]], 587 successive gaps min1 median1 max13 and one>10; profile_version'21221'; laps900/864m, manual/session_end, steps0/1. Steps: time300; distance800 speed3.2..3.6; repeat_from1 repeat_count4; open HR130..145. Decoder timestamp start equals builder START_FIT_TS+631065600 UTC.
Fresh-decoder test verifies integrity probing cannot consume read stream. CRC-flip→invalid_crc; archive without FIT→zip_member_count; garbage→invalid_fit. Duplicated conflicting HR→None/flag, enhanced_speed missing→speed fallback. No timer events→empty tuple/flag, no invented coverage. Output contains neither coordinate canary nor serial/token values. Network wrappers tested with fake client/auth only.

## Acceptance checklist
- [ ] All shared fields/types/null semantics implemented, direct004→010 import possible.
- [ ] Synthetic expected values and corruption cases pass.
- [ ] No live-device claim; G2 still explicit.
- [ ] Privacy outputs contain allowlisted metadata only.

## Completion report
List changed paths, exact test commands actually run and their outputs, fixture coverage, remaining device gates and blockers. No real athlete data, invented verification or design essay. Include baseline/runtime tag and resulting schema head when relevant.

## Escalation rule
If the pinned source or an exported contract differs, STOP with the exact path/signature and a short blocker. Do not invent schema, physiology, DTO, migration, UX, field observation or dependency. Historical handoff notes do not override this packet or schemas §§6–7. Tests use synthetic fixtures and a guarded disposable TEST_DATABASE_URL only; no real-mode startup, live Garmin or athlete DB. Planning approval is required before implementation begins.
