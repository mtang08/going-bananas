SHELL := /bin/bash
RUN := ./scripts/run
.PHONY: doctor setup db-start db-stop migrate seed-demo dev build start check test-integration test-e2e sync

doctor:
	$(RUN) python3 scripts/doctor.py
setup:
	$(RUN) bash -c 'cd backend && uv sync --locked --python 3.12'
	$(RUN) bash -c 'cd frontend && npm ci'
db-start:
	$(RUN) python3 scripts/local-db.py
db-stop:
	$(RUN) python3 scripts/local-db.py stop
migrate:
	$(RUN) bash -c 'cd backend && uv run alembic upgrade head'
seed-demo:
	$(RUN) bash -c 'cd backend && uv run python -m app.cli seed-demo'
dev:
	$(RUN) python3 scripts/serve.py --dev
build:
	$(RUN) bash -c 'cd frontend && npm run build'
start:
	$(RUN) python3 scripts/serve.py
check:
	$(RUN) bash -c 'cd backend && uv run ruff check . && uv run mypy app --ignore-missing-imports && uv run pytest tests/unit tests/test_ingestion.py tests/test_export_adapter.py tests/test_export_recovery.py tests/test_knowledge.py tests/test_coaching.py'
	$(RUN) bash -c 'cd frontend && npm run lint && npm run typecheck && npm test && npm run build'
test-integration:
	./scripts/with-mode test bash -c 'cd backend && uv run alembic upgrade head && uv run pytest tests/integration tests/test_ingestion_integration.py'
test-e2e:
	$(RUN) bash -c 'cd frontend && npx playwright test'
sync:
	$(RUN) bash -c 'cd backend && uv run python -m app.cli sync'

backup:
	$(RUN) bash -c 'cd backend && uv run python -m app.cli backup "$$PRIVATE_DIR/backups/backup-$$(date +%Y%m%d-%H%M%S).tar.gz"'

context:
	$(RUN) bash -c 'cd backend && uv run python -m app.cli export-context "$$PRIVATE_DIR/context-$$(date +%Y%m%d-%H%M%S).json"'
