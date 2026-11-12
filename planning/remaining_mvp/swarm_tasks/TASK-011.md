# TASK-011 — Establish deterministic metric contracts and effective-date anchor history

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce; manager-supplied dependency-complete gb-mvp1-* tag; planning/remaining_mvp MVP-1.0
Wave / priority: P0-A; wave 1a (dependency_graph.md).
Dependencies: TASK-003; TASK-002 delivered
File ownership: Create backend/app/metrics/__init__.py, backend/app/metrics/contract.py, backend/app/metrics/engine.py, backend/app/metrics/anchors.py; create backend/app/api/anchors.py; create backend/tests/unit/metrics/test_contract.py and backend/tests/integration/test_metrics_foundation.py.
Forbidden changes: No metric calculators, trigger installation, schema migrations, main/CLI/frontend edits. No physiology conversion or network.

## Objective and observable end state
Consumers import one exact contract; timer coverage counts unobserved edges, historical anchor selection survives supersession, results retain old dependency versions. Fixture timer union20s partitions known3 and unknown17.

## Inputs and fixed contracts
schemas§6.3 is authoritative, metrics§§2,5–10 define missingness/provenance. Provide every listed signature, alias MetricResult=MetricResultData, RunFact/default_factory, coverage helpers, result selector, register and config upsert. Add immutable completion association hash excludes derived status/version (includes subject/match_method/user modification reasons/source user revision), preventing result→completion self-cycle. Also export metric_source_refs/completion_association_hash exactly schemas§7.2 and metrics.anchors.create_anchor(session,fields:dict)->dict exactly§7.1. No module import side effects until030 registers modules. New anchor writes require calendar authority.

## Implementation procedure
Global lock invariant: every new writer acquires advisory71382413 before app_state FOR UPDATE and before source mutations; never defer advisory until030 after taking app_state. TASK-030 owns coordinated db.bump_data_revision and source-change coalescing (schemas§7.2).

1. Create frozen dataclasses and enums per schemas; canonical JSON hashes stable across dictionary ordering and reject nonfinite numbers. MetricResultData required fields match metric_results exactly excluding ORM id/is_current; hash/timezone/calculated_at optional only until engine fills. Use timezone-aware UTC clock supplied at engine boundary, not calculator-local clocks.
2. Implement interval union/integrate_timer_on. Sort/merge timer intervals, never sort supplied sample timestamps silently. Duplicate/unordered samples raise invalid_stream_order. Interior gap>max_gap entirely unknown even when clipped overlap is short. Leading/trailing eligible portions indexNone. No last-value extrapolation.
3. Implement load_runs using Activity resolved state, effective annotation exclude/workout label and profile timezone. source_refs includes source record revision/raw SHA and FIT SHA/status flags, canonical revision and annotation version. Coverage helper requires complete intervals across every local date, not simply any data row.
4. Registry rejects duplicate metric registrations, unknown dependency and cycles when recompute prepares graph. parse_scope permits activity:<uuid>,strength:strong:<uuid>,strength:manual:<uuid>,checkin:<uuid>,calendar,anchors:<ISOdate>,recovery_dates:<ISOdate>[,<ISOdate>...],timezone,all:<ISOdate>, otherwise ValueError invalid_scope. No modules configured yet means recompute returns[]. upsert_results computes dependency identity and writes only configured calculator results; source provenance absence is explicit invalid result with INPUT_PROVENANCE_MISSING reason.
5. Atomic historical upsert: before promoting result, set prior is_current false for same metric/method/subject; ON CONFLICT historical identity updates calculated_at/value only for identical deterministic dependency. Preserve history row IDs on replay, never delete old anchors/results. latest_results only is_current; no selection by calculated_at.
6. Anchors GET {items}, POST fields§2.5. Validate enum/unit ranges, finite values, low≤high, HR30..230, speed0..10 (strictlypositive for boundaries), performance time/distance>0. Automatic anchor_key kind-valid_from plus -2/-3 collision suffix under transaction lock. First version active; replacement requires supersedes_key matching latest same-kind successor or409 anchor_supersede_required/anchor_superseded. review_after defaults calibrated local date+84 days. Later valid_from closes predecessor effective range logically, preserves predecessor history; same-date correction explicit chain only.
7. active_anchors chooses greatest applicable effective date then calibrated_at/key, excluding rejected/invalid; expiration by review_after is quality flag not erasure. Hash immutable full content incl provenance. API serializer includes id/key/kind/value/unit/protocol/confidence/status/calibrated_at/valid_from/review_after/source IDs/conditions/notes/supersedes_key/content_hash; added content_hash is derived response, can be computed not DB column.
8. Integration test bare FastAPI includes standard envelope/exception handlers and anchors router under/api/v1, overrides get_session with guarded test session, seeds authoritycalendar. Main router installation030 owns integration.

## Tests and expected results
`cd backend && uv run pytest tests/unit/metrics/test_contract.py`: t=[0,1,2,3,20,21],timer[(0,2),(3,21)],maxgap10→eligible20, known intervals lengths1,1,1, unknown17. With values100,None,140,160,170,170 caller bins valid2/invalid1/unknown17; sum20. Empty samples+timer[(0,10)]→(None,10,False); t[2,4],timer[(0,6)]→unknown2,known2,unknown2. Overlaps[(0,4),(2,6)] count6 once; unsorted samples reject. coverage9/10 good,7/10 limited,6.99/10 insufficient,0/0 None.
`./scripts/with-mode test bash -c 'cd backend && uv run pytest tests/integration/test_metrics_foundation.py -m integration'`: repeat config createsone; changed dependency creates history2/current1; rollback restores prior current. AnchorNov1value140 supersededNov10value145: Nov9 selects140,Nov10 selects145; same-date correction explicit chain selects corrected. Backdated successor422; duplicate active without predecessor409. Headlegacy POST409 planning_not_active. No DB access in pure tests.

## Acceptance checklist
- [ ] Exact shared signatures imported by downstream packets.
- [ ] Timer union/edges/missing arithmetic and thresholds tested.
- [ ] Historical anchors/results retained, current signature deterministic.
- [ ] Registry foundation has no live trigger or calculator side effects.

## Completion report
List changed paths, exact test commands actually run and their outputs, fixture coverage, remaining device gates and blockers. No real athlete data, invented verification or design essay. Include baseline/runtime tag and resulting schema head when relevant.

## Escalation rule
If the pinned source or an exported contract differs, STOP with the exact path/signature and a short blocker. Do not invent schema, physiology, DTO, migration, UX, field observation or dependency. Historical handoff notes do not override this packet or schemas §§6–7. Tests use synthetic fixtures and a guarded disposable TEST_DATABASE_URL only; no real-mode startup, live Garmin or athlete DB. Planning approval is required before implementation begins.

Integrator exact public signature: integrate_timer_on(t_s:list[int],timer_on:list[tuple[float,float]],max_gap_s:int)->list[tuple[int|None,float,bool]]. Integer timer endpoints accepted as numeric subset. Validate finite endpoints and end>start, union sorted overlapping/adjacent segments; preserve fractional lap-clipping boundaries. Record t_s stays integer and strictly increasing. Fixture t=[0,1,2], timer=[(.25,1.75)] yields [(0,.75,True),(1,.75,True)], eligible1.5.
