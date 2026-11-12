# App access

Run the helper with Python 3 and an explicit `--mode real|demo|test`. It locates the repository from its source path, `--repo`, `GB_REPO`, or `~/dev/going-bananas` when installed. `--base-url` defaults to `http://127.0.0.1:8000`; HTTP access permits loopback origins only and checks the response mode.

Commands:

- `schema`: live JSON proposal schema and manual-activation protocol.
- `snapshot --operation OP [--as-of YYYY-MM-DD]`: compact source facts and verified research excerpts.
- `query activity_execution --activity-id UUID`
- `query long_run_history --start DATE --end DATE`
- `query recovery_nights --start DATE --end DATE`
- `query calendar_diff --from N --to N`
- `query explain_metric --result-id UUID`
- `active-proposal`: read the current open proposal summary, or `data.proposal: null` when none exists.
- `submit --file PATH`: save under `private/MODE/coach/proposals` and submit pending. The server validates linkage and source freshness. The helper never changes proposal source fields.
- `revise UUID --expected-revision N --reason TEXT --file PATH`: save a replacement draft privately and revise the same pending proposal. Returns the revision number and stable review link. A concurrent edit returns `proposal_revision_conflict`.
- `history`: saved calendar versions.
- `proposal UUID`: inspect the changeset, decisions, and current state.
- `proposal UUID --document`: get the complete reusable JSON document for the current revision. Add `--revision N` for a historical document.
- `discarded` proposals are terminal, alongside accepted, partially accepted, and rejected proposals; they cannot be revised or restored.
- `undo --expected-head N --target-version N --reason TEXT`: protected calendar rollback, only after an explicit user request.

Exit codes: 0 success; 1 sanitized runtime failure; 2 invalid input/protocol; 3 stale proposal; 4 unavailable verified research or missing query subject. Read structured errors and apply the bounded retries in SKILL.md. A successful submission must say `pending`; any other successful response is treated as a protocol error.

Snapshot/query/submit/revise invoke the repository CLI through `scripts/with-mode` using subprocess argument arrays. `active-proposal`, `history`, and `proposal` use read-only API GET requests. There is no automatic mode switch, shell command interpolation, direct SQL, accept command, or fallback to `/coach/agent/proposals`. Plans are accepted in the app review page. This package is installed from its verified manifest during the app's calendar-authority cutover.

## Reusable access without repeated prompts

For `schema`, `snapshot`, `query`, `active-proposal`, `history`, and `proposal`, use this stable command prefix:

`python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real --read-only`

The flag rejects `submit`, `revise`, and `undo` before calling the app. “Read-only” means no plan/calendar/anchor decisions; snapshots may persist derived metrics and an evidence snapshot, and saved responses write private local files.

Append `--save-response` to the subcommand when its JSON may be large. It returns `response_file`; read that returned file in bounded sections. The helper saves the complete response under `private/MODE/coach/responses`, creates a unique file with mode 0600, and never overwrites a previous response. Do not wrap a normal helper call in shell redirection, pipes, or a script just to capture its output: those wrappers can defeat narrowly scoped reusable command approvals.

When sandbox access fails, request the platform's normal escalation with a reusable prefix for the exact helper plus `--mode real --read-only`. Pending submissions use a separate prefix ending in `--mode real submit`. Never request a blanket Python, shell, database, all-helper, or undo approval. A persistent allow rule is the user's choice in the platform approval UI; do not edit approval rules or disable the sandbox to avoid a prompt. Managed policy may still require individual approval.

Routine reads and pending proposals are authorized by the coaching request. Actual plan application remains manual in the app; protected undo requires an explicit athlete request. Use the repository helper in this workspace; keep the installed copy in sync through an explicitly authorized, hash-verified update.
