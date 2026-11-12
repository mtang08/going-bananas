# Coach planning readiness audit — §H fresh pass

**Verdict: NOT READY** for independent implementation of TASK-061 and TASK-039. This is a specification audit against the pinned baseline and cited contracts; no implementation or tests were run.

## TASK-061 — proposal service

1. **Freshness input is not executable as specified.** The binding collector signature in TASK-061 takes `kb_digest` and optionally `selected_records`, while `submit_proposal(session, raw, *, now, kb: KbIds)` supplies only three ID sets and `load_context(session, snapshot_id, *, now, kb)` likewise has no digest or selected-record provenance. TASK-062 calls the fingerprint helper without `selected_records`. Schemas §6.4 explicitly hashes KB digest **and selected records**. Two workers can hash different vectors or skip verified KB content. Specify the one authoritative verified KB input type, how it reaches submit and acceptance, whether selected records are reconstructed from the snapshot or reselected, and the exact call signature shared with TASK-062. Include a fixed vector/hash fixture that changes when selected KB content changes but ignores proposal insertion and derived writes.

2. **Decision replay and conflict rules disagree.** TASK-061 step 13.1 says same key with different content or changed terminal selection is `decision_conflict`; coaching_contract §5 and schemas §6.4 require a new key with the **same** terminal selection to replay, and a key reused on another proposal to yield `idempotency_conflict`. TASK-061 step 13.2 collapses moved heads and changed source fingerprints into `proposal_stale`, whereas §5 requires `stale_evidence` for changed sources. Define the canonical selection hash (whether `expected_head` participates), global key lookup, replay ordering, and distinct stale codes in one binding algorithm. Test all four combinations: same/new key × same/changed selection, cross-proposal key reuse, and head-only versus source-only drift.

3. **Accepted anchor-only decisions leave pending proposals fresh.** Step 13.8 stales other proposals only after a calendar or block version, yet schemas §6.4 includes effective anchors in the fingerprint. An anchor-only acceptance changes decision inputs with no calendar/block version. State that pending proposals are staled after any accepted source change, including anchors, and test anchor-only acceptance. Also make `validate_subset` take the accepted anchor keys: its stated signature has no anchor selection, although the binding paragraph requires selected-anchor validation.

4. **Write integration is ambiguous.** Step 13.6 describes direct `CalendarVersion`/revision writes while also requiring the TASK-012 calendar write/post-write service; step 13.7 initially instructs calling the anchor route's function, then the binding paragraph specifies TASK-011 `create_anchor` and forbids route-handler calls. Pin the actual service signatures and the single point responsible for version allocation, metric/prompt invalidation, and source-revision bump. This prevents duplicate writes and duplicate invalidation. Clarify how a block-only or anchor-only accepted decision triggers the same post-write effects.

## TASK-039 — frontend contracts

5. **The exact-code instruction conflicts with canonical DTOs.** Step 1 requires the six files to contain the displayed types exactly, but the binding reconciliation says schemas §6 / metrics contracts supersede obsolete examples. For example, displayed `MetricResult` lacks `dependency_hash`, `timezone`, and source provenance; displayed volume/SRPE values omit missingness counts; the displayed `CalendarView` omits the §6 undo field and `CalendarWriteResult` omits `preserved_session_uids`. Supply a single amended, complete TypeScript source of truth or a field-by-field replacement list, plus representative wire fixtures. “Mirror §6” does not uniquely determine every nested metric value because §6 points onward to metrics.md, whose descriptive rules are not a full TS interface.

6. **Fixtures and authority DTO lack a legal owner/dependency.** TASK-039 forbids every file except its seven listed files, yet binding acceptance asks for fixtures shared with backend TASK-012/013/014/030. TASK-039 depends on those tasks as already merged and cannot add their fixtures. It also requires `planningAuthority` from TASK-068, a wave-12 successor, while TASK-039 is wave 4. Assign fixture file ownership and the producing task; either define the authority field and its wire location now (with a pre-cutover value) or defer that addition to TASK-068. The baseline `Envelope<T>` in `frontend/src/api.ts` has no such field.

7. **Query-key instruction is internally inconsistent.** The displayed `qk` object contains unprefixed arrays, while adjacent prose and the test require `['v2', ...]`; `profile` must remain its existing unprefixed key. Replace the code block with the exact exported values, identifying the profile exception, so independent workers and downstream invalidation use one cache namespace.

## Planning amendments after this audit (experience lead; awaiting fresh recheck)

The original NOT READY findings above are retained. No application implementation or runtime tests were performed.

1. **Verified KB/source input:** TASK061 now owns one VerifiedKnowledge type and resolver callback;060 verify_selection reconstructs current verified bytes for the snapshot's saved selection.062/063/064 pass the same object; collector takes kb, not digest-only. Snapshot pins kb_routes and selected records. Static canonical vector and expected hashes are in contracts/coach-fingerprint.json. Old competing collector signature was removed from061/062; schemas owner notified.
2. **Replay/conflict taxonomy:**061 step13 replaced in full: selection hash includes proposal ID and sorted selections, excludes expected_head/key; global CoachDecisionKey aliases cover new-key replay. Same/new key same selection replay; changed selection decision_conflict; cross-proposal key idempotency_conflict. Base/TTL stale differs from source stale_evidence; terminal replay precedes freshness. Regression matrix specified.
3. **Anchor-only decisions:** validate_subset now receives accepted_anchor_keys; selected whole-state validation and any-source-change staleness include anchor-only and block-only decisions.
4. **Write ownership:**061 now calls exact apply_edits/create_anchor services; no direct calendar version/revision inserts or handler discovery.030 owns coalesced source bump/derived refresh;061 block writes enqueue one scope. Models reference coach_v2_models, including decision-key table.050 uses explicit seed_demo_calendar(history_edits), not forbidden historical ordinary edits.
5. **Concrete DTOs:**039 displayed interfaces now include undo/preserved IDs, complete metric provenance, missing duration/distance/load counts, intensity distributions, recovery baseline fields, interval rep/count/target fields and precise nested structure. ConfirmedSchedule is explicit (no undefined Profile import). Actual fixture source is contracts/frontend-wire.json; optional fields represent producer-specific activity/window variants, not guessed missing values.
6. **Ownership/authority:**039 owns frontend/tests/fixtures/planning-wire.json and api-format tests; no later backend fixture edits. TASK003 emits planning_authority at GET/profile.data,039 extends Profile,050 reads profile.data.data.planning_authority; no068 DTO dependency or envelope field.
7. **Query keys:**039's actual exported qk block now prefixes every new key with v2; profile is explicitly the sole unchanged ['profile'] exception. Tests assert exact arrays.

Cross-owner confirmations received: data lead pinned calendar/anchor service signatures, global decision-key table,030 sole bump and003 authority field; metrics lead added both SRPE missingness count keys and pinned spacing sessions shape. Fresh independent recheck is still required; these amendments are not a PASS declaration.

## Fresh recheck of amended specs — NOT READY

The original seven findings are resolved **within TASK-061/TASK-039** as described above: one verified KB object and static fingerprint vector; pinned replay hash and global key aliases; accepted-anchor subset/staleness; single calendar/anchor services and TASK-030 invalidation owner; concrete DTOs and owned fixture; GET profile authority from TASK-003; exact prefixed query keys. Two cross-file blockers remain:

1. **Anchor units contradict the canonical schema.** TASK-061 constants/V14 permit only `bpm|mps|s` and require every `performance_*` anchor to use `s`. TASK-039 `IntensityAnchor`, `AnchorCreate`, and `ANCHOR_UNIT` do the same. Yet schemas §2.5 and metrics §3.1 require `performance_3min` in `m` and `performance_20_30min` in `mps`; the database CHECK will reject the former as TASK-061 validates it, and the TS DTO cannot represent it. Change both tasks to the explicit eight-kind mapping in schemas §2.5, including `m`, and add valid/invalid examples for both special performance kinds.

2. **The collector's public signature still has two definitions.** TASK-061/062 now require `collect_decision_inputs(..., *, now, kb:VerifiedKnowledge)` and the same argument for `decision_input_fingerprint`; schemas §7.2 still publishes `(..., *, now, kb_digest:str, selected_records:tuple[dict,...]=())`. A TASK-030 or downstream worker following §7.2 will call an incompatible API. Replace the §7.2 signatures with the VerifiedKnowledge form and point to TASK-061 for construction/resolution. Keep the static vector fixture as the shared hash oracle.

No implementation, live data, web research, or runtime tests were used for this recheck.

## Final contract recheck — READY

Both remaining blockers are resolved. TASK-061 V14 and TASK-039 anchor DTOs now use the same explicit eight-kind map as schemas §2.5: `performance_3min` is `m`, `performance_20_30min` is `mps`; valid and invalid cases are specified. Schemas §7.2 now gives the same `kb:VerifiedKnowledge` collector signature as TASK-061/062, with TASK-060 owning verification and the saved selection reused at submit and acceptance.

The added legacy safety path is coherent across TASK-061, TASK-062, schemas, coaching_contract, and the static fingerprint vector: original schema-1 check-ins remain categorical, inclusive within the last 72 hours, appear once in snapshots, enter the source fingerprint, and activate V12 through `legacy_safety_active` without a manufactured numeric severity. The fixture has an explicit empty `legacy_checkins` vector and refreshed expected hashes. Planning readiness only; no app code, live data, or runtime tests were accessed.

## Second amendment round (awaiting recheck)

- Replaced039/061 anchor unit assumptions with explicit eight-kind mapping: performance_3min=m and performance_20_30min=mps; updated044 metre input/rendering and valid/invalid examples.
- Data lead confirmed schemas§7.2 now uses the same kb:VerifiedKnowledge collector signature as061/062.
- Preserved recent legacy safety across authority cutover:061 collector fingerprints original schema1 categorical check-ins within inclusive72h,062 exposes them separately with severity_numeric:null, and legacy_safety_active joins V12. Tests cover gaitaffected/severe/moderate+worse, exact72h boundary, older/future exclusion, newer mild v2 coexistence and no duplicate imported facts/no numeric conversion. Static hash oracle updated with explicit empty legacy_checkins vector.
- Coordinated helper manifest/schema markers and deterministic historical seed UUIDs with data lead. Added manager-pinned isolated browser18000 instructions to050/070; real8000 service untouched.

No application changes or runtime tests; original audit/recheck findings remain above.
