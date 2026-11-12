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
- `submit --file PATH`: save under `private/MODE/coach/proposals` and submit pending. The server validates linkage and source freshness. The helper never changes proposal source fields.
- `history`: saved calendar versions.
- `proposal UUID`: inspect the changeset, decisions, and current state.
- `undo --expected-head N --target-version N --reason TEXT`: protected calendar rollback, only after an explicit user request.

Exit codes: 0 success; 1 sanitized runtime failure; 2 invalid input/protocol; 3 stale proposal; 4 unavailable verified research or missing query subject. Read structured errors and apply the bounded retries in SKILL.md. A successful submission must say `pending`; any other successful response is treated as a protocol error.

Snapshot/query/submit invoke the repository CLI through `scripts/with-mode` using subprocess argument arrays. There is no automatic mode switch, shell command interpolation, direct SQL, accept command, or fallback to `/coach/agent/proposals`. Plans are accepted in the app review page. This package is installed from its verified manifest during the app's calendar-authority cutover.
