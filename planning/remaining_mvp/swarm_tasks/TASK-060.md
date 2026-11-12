# TASK-060 — Add section routing to the installed KB loader without breaking existing consumers

Planner note (2026-11-11): amendment A1 is APPROVED (`coaching_contract.md` §6 step 6). Procedure step1 verifies/applies it only if still needed.

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce + merged dependencies per dependency_graph.md; spec planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag
Wave / priority: P0-B; wave 7 (dependency_graph.md).
Dependencies: TASK-050; all earlier DAG dependencies remain required.
File ownership: `running_coach_kb/manifest.json` (routing heading correction only), `backend/app/services/knowledge.py`, `backend/tests/test_knowledge.py`
Forbidden changes: every other path. Do not edit `backend/app/cli.py`, `backend/app/api/**`, `backend/app/services/snapshot.py`, `backend/app/services/proposals.py`. Do not change any KB file other than as listed below. No new dependencies.

## Objective and observable end state
`load_route` returns operation-specific sections/records with verified provenance. Current load_knowledge callers and their tests remain operational.

## Inputs and fixed contracts
- `coaching_contract.md` §6 (loader steps 1–6, trigger table, policy map, P011 exclusion), §2 (operation keys).
- Error type kept: `KnowledgeIntegrityError(ValueError)` (callers map it to CLI exit 4 / HTTP 503 in TASK-063/064).
- Current loader guards kept verbatim in behaviour: path must be relative, no `..`, `str(PurePosixPath(rel)) == rel`; target must be a regular file, not a symlink, resolve inside root; size ≤ `MAX_FILE_BYTES = 100_000`.

## Implementation procedure
1. Verify the installed package remains 1.1.0+privacy1. Do not copy an overlay, change baseline provenance, or replace package files. If the manifest route still contains the old "Two demanding exposures within seven runs per fortnight" heading, replace that routing string only with the existing "…within the agreed rolling-cycle run count" heading. Already corrected means no edit.
2. Preserve `load_knowledge`, `KnowledgeContext`, `WORKFLOWS`, `MAX_CONTEXT_CHARS` and all legacy selective-loader behavior/tests. Add the following routed API beside it. `_read` invalid paths raise KnowledgeIntegrityError (ValueError subclass), retaining current path/size/hash/privacy guards.
3. Add module constants:
   - `SUPPORTED_OPERATIONS = ("proceed_or_modify_today", "review_rolling_plan", "select_quality_session", "review_training_block", "recalibrate_intensity", "handle_goal_or_race_change")`
   - `CONDITIONAL_TOPICS` (trigger-table order): `topics/ptt_and_load_tolerance.md`, `topics/recovery_and_daily_adaptation.md`, `topics/hybrid_strength_and_scheduling.md`, `topics/long_runs_and_race_development.md`, `topics/aerobic_progression.md`, `topics/intensity_and_workout_methods.md`, `topics/intensity_calibration_and_testing.md`, `topics/periodization_and_training_blocks.md`, `topics/races_tapers_and_transitions.md`
   - `POLICY_MAP: dict[str, tuple[str, ...]]` copied exactly from `coaching_contract.md` §6.5 table (P011 in no tuple).
   - `TOKEN_BUDGET = {"proceed_or_modify_today": 1800, "review_rolling_plan": 3000, "select_quality_session": 5000, "review_training_block": 5000, "recalibrate_intensity": 5000, "handle_goal_or_race_change": 5000}`
   - `POLICY_FILES = ("policies/coaching_policy_candidates.json", "policies/periodization_policy_candidates.json")`, `RECIPE_FILE = "recipes/running_session_families.json"`, `EVIDENCE_FILES = ("references/evidence_matrix.md", "references/periodization_evidence_addendum.md")`, `EVIDENCE_ROW = re.compile(r"^\| (E-[A-Z]+-\d{2}) \|", re.M)`, `HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")`.
5. Add frozen dataclasses:
   - `KbExcerpt(path: str, section: str | None, record_id: str | None, text: str)` with `to_json() -> dict` returning `{"path", "section", "text"}` when `section` set, `{"path", "record_id", "text"}` when `record_id` set, else `{"path", "text"}`.
   - `KbBundle(package_version: str, excerpts: tuple[KbExcerpt, ...], chars: int, approx_tokens: int, routes: tuple[dict, ...])` with `to_json() -> {"package_version", "excerpts": [e.to_json()...], "chars", "approx_tokens"}`.
   - `KbIndex(package_version: str, policy_ids: frozenset[str], recipe_ids: frozenset[str], evidence_ids: frozenset[str])`.
6. Add `load_manifest(root: Path | None = None) -> dict`: same missing/symlink/size/JSON/structure checks as the old loader (wrap failures in `KnowledgeIntegrityError`), except: each `files[]` entry needs `path: str`, `bytes: int`, `sha256: str | None`; require `schema_version == "1.1"` and `package_name == "running_coach_kb"` and `package_version: str` and `routing: dict`. Then call `_read` for every entry whose `sha256` is not None (verifies size+hash). Return the manifest.
7. Add `extract_section(text: str, heading: str, path: str) -> str`: `lines = text.split("\n")`; candidates = indexes `i` where `HEADING.match(lines[i])` and `group(2) == heading`. If count ≠ 1 → `KnowledgeIntegrityError(f"Section not found exactly once: {path} :: {heading}")`. `level = len(group(1))`; end = first `j > i` whose line matches `HEADING` with `len(group(1)) <= level`, else `len(lines)`. Return `"\n".join(lines[i:end]).strip("\n")`. No code-fence handling (planner checked: no `#` line sits inside a fence in any KB Markdown file).
8. Add `load_route(operation: str, *, recipe_ids: Iterable[str] = (), conditional_topics: Iterable[str] = (), root: Path | None = None) -> KbBundle`:
   1. `operation not in SUPPORTED_OPERATIONS` → `ValueError("unsupported_operation")`. Any topic not in `CONDITIONAL_TOPICS` → `ValueError("unknown_conditional_topic")`.
   2. `manifest = load_manifest(root)`; `route = manifest["routing"][operation]`.
   3. For each item of `route["minimum"]` in order: dict with `sections` → for each section name in order append `KbExcerpt(path, name, None, extract_section(_read(...), name, path))`; dict with `state` → skip; dict with `records` → skip (recipes come from step 5); any other shape → `KnowledgeIntegrityError("Unsupported routing item")`.
   4. For each path in `CONDITIONAL_TOPICS` order that is in the deduplicated `conditional_topics`: whole-file excerpt `KbExcerpt(path, None, None, _read(...).strip("\n"))`. If section excerpts with the same path exist, remove them all and insert the whole-file excerpt at the index of the first removed one; else append.
   5. Recipes: load `RECIPE_FILE` JSON, index `recipes` by `recipe_id`; unknown id → `ValueError("unknown_recipe_id")`; for each unique id in sorted order append `KbExcerpt(RECIPE_FILE, None, rid, json.dumps(record, ensure_ascii=False))`.
   6. Policies: load both `POLICY_FILES`, index `policies` by `policy_id`; for each id in `POLICY_MAP[operation]` append `KbExcerpt(<file holding it>, None, pid, text)` where `text` = the old loader's per-policy block without the leading `## `: `f"{pid}: {title}\nTrigger: {'; '.join(trigger)}\nSuggested action: {'; '.join(suggested_action)}\nDo not apply when: {'; '.join(do_not_apply_when)}\nRationale: {rationale}\nEvidence: {', '.join(evidence_ids)}; sources: {', '.join(source_ids)}\nCertainty: {evidence_certainty}; applicability: {athlete_applicability}\nUncertainty: {uncertainty}"`.
   7. `chars = sum(len(e.text))`; `approx_tokens = math.ceil(chars / 4)`. If `approx_tokens > TOKEN_BUDGET[operation]`: `logging.getLogger(__name__).warning("kb_budget_exceeded operation=%s approx_tokens=%d budget=%d", ...)`. Never truncate.
   8. `routes`: one dict per distinct path in first-appearance order: `{"path": p, "sections": [names]}` for section excerpts, `{"path": p, "sections": ["*"]}` for whole files, `{"path": p, "record_ids": [ids]}` for records.
9. Add `kb_index(root: Path | None = None) -> KbIndex`: `load_manifest`, then policy ids from both policy files (23), recipe ids (10), evidence ids = union of `EVIDENCE_ROW.findall` over `EVIDENCE_FILES` (55).
10. Append routed tests to `backend/tests/test_knowledge.py`; keep existing selective-loader tests.

11. Export `verify_selection(selection:tuple[dict,...],*,root:Path|None=None)->dict`. Verify manifest/package files and IDs using load_manifest/kb_index. Reconstruct saved routes exactly: section headings extract_section (including '*' whole-file); record IDs load canonical JSON records, never fresh operation routing. Reject unknown paths/IDs/headings. Return `{digest,selection,selected_records,policy_ids,recipe_ids,evidence_ids}`. selected_records sorted(path,record_id), items `{path,record_id,content}`. digest SHA256 canonical JSON `{manifest:<verified manifest>,excerpts:[{path,section,record_id,text}],selected_records}` with sorted compact keys,ensure_ascii=False,allow_nan=False. Excerpts preserve selection order; absent section/record_id null. Mapping values selection/selected_records are tuples, ID sets frozensets over whole verified package; constructor-ready for061 VerifiedKnowledge. No dependency on061 type; callers construct VerifiedKnowledge from this mapping.

## Tests and expected results
Command: `cd backend && uv run pytest tests/test_knowledge.py -q` then `make check`. Tests (names marked * are binding per `acceptance.md` §4; use `DEFAULT_ROOT` unless stated; `tmp_kb` fixture = `shutil.copytree(DEFAULT_ROOT, tmp_path / "kb")`):
- `test_overlay_matches_manifest`: every `files[]` entry hashes/sizes correctly; on-disk file set minus `manifest.json` == listed set (28); `schema_version == "1.1"`, `package_version == "1.1.0+privacy1"`, `baseline_revision provenance remains unchanged from installed package`.
- `test_extract_section_bounds`: on `COACHING_GUIDE.md`, `"3. Decision hierarchy"` → starts with `"## 3. Decision hierarchy"`, `len == 1170`, contains no `"## 4."`. Synthetic `"# A\nx\n## B\ny\n### C\nz\n## D\nw"`: `B` → `"## B\ny\n### C\nz"`, `C` → `"### C\nz"`; `"Q"` → `KnowledgeIntegrityError`; text `"## B\n## B"` with `B` → `KnowledgeIntegrityError`.
- `test_route_minimum_sections` (parametrized, `recipe_ids=()`, no topics) — (section excerpt count, sum of their `len(text)`): daily (6, 6090), rolling (7, 8399), select_quality (9, 10423), block (11, 15878), calibration (9, 8645), race (11, 14462); policy excerpt ids equal `POLICY_MAP[op]` in order.
- `test_daily_bundle_totals` (with `caplog`): `chars == 15752`, `approx_tokens == 3938`, `len(excerpts) == 15`, first excerpt `("COACHING_GUIDE.md", "3. Decision hierarchy")`, last `record_id == "P018"`, `"kb_budget_exceeded"` in `caplog.text`.
- `test_conditional_topic_replaces_sections`: `load_route("select_quality_session", conditional_topics=["topics/intensity_and_workout_methods.md"])` → exactly one excerpt with that path, `section is None`, `len(text) == 12243`, at index 4.
- `test_recipe_records`: `load_route("select_quality_session", recipe_ids=["REC003", "REC001", "REC003"])` → recipe excerpts `REC001`, `REC003` in that order, text `== json.dumps(record, ensure_ascii=False)`; `to_json()` of a recipe excerpt has keys `{"path", "record_id", "text"}`.
- `test_p011_never_routed`* : for every op in `SUPPORTED_OPERATIONS`, no excerpt has `record_id == "P011"` and `"P011"` is in no `POLICY_MAP` tuple.
- `test_invalid_inputs`: `"deep_evidence_audit"` → `ValueError("unsupported_operation")`; `recipe_ids=["REC011"]` → `"unknown_recipe_id"`; topic `"topics/fueling_and_energy_availability.md"` → `"unknown_conditional_topic"`.
- Integrity tests on `tmp_kb`; each asserts `KnowledgeIntegrityError` from `load_route("proceed_or_modify_today", root=tmp_kb)`:
  - `test_manifest_1_0_rejected`* : manifest `schema_version` set to `"1.0"`.
  - `test_sha_mismatch_integrity_error`* : append one byte to `workflows/weekly_review.md` (a file the daily route does not load; proves step 6 verifies every file).
  - `test_missing_heading_integrity_error`* : in the manifest rename routing section `"Clarification rule"` to `"Nope"`.
  - `test_path_traversal_rejected`* : (a) append files entry `{"path": "../outside.md", "status": "added", "bytes": 1, "sha256": "0"*64}`; (b) separately, replace `COACHING_GUIDE.md` by a symlink to a copy of itself.
  - `test_manifest_missing_or_malformed`: manifest deleted; manifest text `"{bad json"`.
- `test_kb_index`: 23 policy ids incl. `"P011"` and `"P023"`; recipe ids `{"REC001"…"REC010"}`; 55 evidence ids incl. `"E-AER-01"`, `"E-PER-02"`.

## Acceptance checklist
- [ ] 28 KB files hash-match the manifest; no other file under `running_coach_kb/` changed or added.
- [ ] `manifest.json` diff = exactly 3 changed lines (2 baseline lines + A1).
- [ ] Existing load_knowledge/KnowledgeContext consumers and tests remain unchanged and pass alongside routed APIs.
- [ ] All tests above pass; `make check` green.

## Completion report
Changed files; installed package integrity result; pytest and `make check` output; blockers.

## Escalation rule
If an exact file/function/contract differs from the pinned source or a requirement is underspecified, STOP and return a short blocker. Do not invent a new schema, behavior, dependency, UX, or alternative implementation.

## Compatibility acceptance
No module importing load_knowledge/KnowledgeContext is a blocker or removal target. Run test_knowledge and test_coaching plus integration/test_agent_plans against disposable test DB. Existing daily/weekly contexts still have bounded topics/records and selected source references. Routed API includes kb_digest over verified manifest content and selected excerpts, used by062/061. Resource overflow raises KnowledgeIntegrityError; no silent truncation. Do not change KB policy activation or installed skill.
