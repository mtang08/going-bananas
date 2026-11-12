# TASK-065 — Repo-local Codex skill and pending-proposal helper

Baseline: main `5ebf981aa4517f4f73f3c97aa5d43232204466ce` plus064. Planning only until approval.
Wave / priority: P0-B; wave 11 (dependency_graph.md).
Dependencies: TASK-064; all earlier DAG dependencies remain required.
File ownership: create `.codex/skills/going-bananas-coach/coach-helper.manifest.json`; create `.codex/skills/going-bananas-coach/SKILL.md`, `agents/openai.yaml`, `scripts/coach_app.py`, `references/app-access.md`, `references/coaching-workflows.md` under that skill directory; `scripts/test_coach_skill_v2.py`.
Forbidden changes: installed `/Users/mtang/.codex/skills/going-bananas-coach`, app services/routers, DB, existing helper tests, other platform skills. No install occurs here.

## Objective and observable end state
The repo-local Codex skill reads compact snapshots, writes a proposal JSON and submits it as pending. Its final message links the app review page. It never calls an acceptance endpoint or activates a plan. Current installed skill remains intact until068 performs controlled update.

## Inputs and fixed contracts
coaching_contract §§2–6/10, schemas §§4–6 and064 CLI. Existing installed helper is a compatibility reference only: preserve loopback-only API URL checks, explicit mode, timeouts, structured errors and no credential/GPS output. Operation enum contains the six contract operations; no deep_evidence_audit command. Backend interfaces remain platform-neutral.

## Implementation procedure
1. Create frontmatter name `going-bananas-coach`, description covering daily/weekly/block/calibration/race reviews, excluding dashboard development. Source version `running-coach.v1`. Name entry point Codex. Copy contract§3.2 procedure with explicit same GB_MODE for every command. Use repo-root absolute working directory resolved from script location; reject unknown modes.
2. Helper subcommands: `snapshot --operation OP [--as-of DATE]`, `query NAME` plus064 args, `submit --file PATH`, `history`, `proposal ID`, `undo --expected-head N --target-version N --reason TEXT`. Snapshot/query/submit call the064 CLI via subprocess argument arrays (no shell interpolation); history/detail/undo use loopback API with existing timeout/error handling. Undo delegates protected calendar endpoint and is only used on explicit user request. No accept/decision helper command.
3. Store proposal under mode-specific private directory (`private/real/coach/proposals` or `private/demo/coach/proposals`, matching app settings); use UTC filename and exclusive creation. No athlete data in skill references. Schema loaded with exact command `scripts/with-mode MODE bash -c 'cd backend && uv run python -m app.cli coach schema'` (helper uses argv/cwd without a shell); require source_fingerprint/snapshot linkage exactly as returned, never synthesize missing data. Validation exit2 permits max2 corrected submissions; exit3 reruns snapshot once and regenerates a new pending proposal; exit4 reports KB unavailable; exit1 reports sanitized failure. No acceptance retry.
4. Output summary, changes/reasons, preserved items, uncertainty/follow-up and `Review in the app: #proposal/<id>`. State “Pending your review; nothing applied.” Empty proposal still requires explicit no-change acknowledgment. If planning authority is legacy, report upgrade required and do not fall back to automatic /coach/agent/proposals.
5. Write coach-helper.manifest.json last: artifact_version going-bananas-coach.MVP-1.0,protocol coach_proposal.v1,required_authority calendar,activation manual,files sorted by relative path with sha256 of exact bytes for every skill artifact excluding the manifest. Reject symlinks; no self-hash. TASK068 verifies this manifest before explicit install/update. Verify064 coach schema protocol/manual/authority markers match; mismatch stops without falling back.
6. references/app-access documents current and replacement routes, mode isolation, installation source and068 switch; workflows references the six operations and current-data-first/selective KB rules. agents/openai.yaml points to this skill with no tools that auto-accept.

## Tests and expected results
`python3 -m unittest scripts/test_coach_skill_v2.py` and existing `python3 -m unittest scripts/test_coach_skill.py`: mocked subprocess/HTTP only; no live API. Tests enforce exact mode/args, unsafe URL rejection, no shell=True, snapshot/submit linkage, pending-only success wording, malformed/stale response handling, no decision endpoint calls, source fields unchanged, no automatic legacy fallback, and explicit undo guard payload. `make check` passes.

## Acceptance checklist
- [ ] Existing installed skill unchanged; source/helper package versioned in repo.
- [ ] Each submission remains pending and review URL references returned ID.
- [ ] Old and new helper tests pass; no external request or live-data fixture.

## Completion report
Changed paths, test output, source/install manifest and hashes (no athlete data); unresolved interface mismatch.

## Escalation rule
If backend schema/path differs, stop and return exact mismatch. Do not invent a second API, install early or add Claude Code support.
