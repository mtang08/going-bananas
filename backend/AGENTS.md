# Python reference and migration work

The Go application owns the dashboard, HTTP API, and normal operator commands.
This directory keeps historical Alembic upgrades and the Python reference CLI
and services used by synthetic comparisons. Inherit the root iteration-speed policy.

| Task | Entry points |
| --- | --- |
| Historical schema upgrades | `migrations/versions/`, `app/migrations_head.py`, `tests/integration/test_schema_upgrade.py` |
| Reference CLI | `app/cli.py`, `app/config.py`, `app/db.py` |
| Reference coaching | `app/services/{snapshot,proposals}/`, `app/services/decision_inputs.py`, `app/services/knowledge.py` |
| Reference metrics and projections | `app/metrics/`, `app/read/`, `app/services/derived.py` |
| Reference ingestion and provider behavior | `app/adapters/`, `app/services/{sync,export_import,fit_ingest,strong_import,gcal_sync}.py` |

Use a dedicated synthetic PostgreSQL workspace for reference tests. Keep real
athlete records, credentials and raw payloads private. Preserve historical
migrations and their dependencies so old databases can upgrade to the current
schema. When the schema changes, verify the relevant upgrade and the native
baseline in the same change.

Run from the repository root.

```sh
make check-backend
make test-integration TESTS=tests/integration/test_schema_upgrade.py
```
