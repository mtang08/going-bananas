# Historical PostgreSQL upgrades

The Go application owns the dashboard, HTTP API, domain logic and operator
commands. This directory keeps the historical Alembic upgrade chain and Python
verification tools. Inherit the root iteration-speed policy.

| Task | Entry points |
| --- | --- |
| Historical upgrades | `migrations/versions/`, `app/migrations_head.py`, `tests/integration/test_schema_upgrade.py` |
| Schema metadata | `migrations/env.py`, `app/models.py`, `app/*_models.py`, `tests/unit/test_schema_models.py` |
| Database and mode guards | `app/config.py`, `app/db.py`, `tests/unit/test_config.py` |
| Native test inputs | `tests/fixtures/` |

Verify migrations using a dedicated synthetic PostgreSQL workspace. Preserve
historical migrations and their dependencies so old databases can upgrade to
the current schema. Keep real athlete records, credentials and raw payloads
private. Coordinate schema changes with the native baseline and verify both
upgrade paths.

From the repository root, run `make check-backend` and
`make test-integration TESTS=tests/integration/test_schema_upgrade.py`.
