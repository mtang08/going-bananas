SHELL := /bin/bash
RUN := ./scripts/run
API_TYPES := $(RUN) env APP_MODE=test DATABASE_URL=postgresql+psycopg://localhost/garmin_test \
	PRIVATE_DIR="$(CURDIR)/private/test" PYTHONPATH=backend uv run --project backend python scripts/api-types.py
BACKUP := cd backend && uv run python -m app.cli backup "$$PRIVATE_DIR/backups/backup-$$(date +%Y%m%d-%H%M%S).tar.gz"
TESTS ?= tests/integration tests/test_ingestion_integration.py
.PHONY: doctor setup db-start db-stop migrate seed-demo dev build start check test-db-start test-db-stop test-integration test-integration-external test-e2e sync backup check-backend check-frontend check-docs complexity

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
	$(RUN) bash -c 'if [ "$$APP_MODE" = real ]; then ( $(BACKUP) ) || { echo "Backup failed; migration aborted." >&2; exit 1; }; fi; cd backend && uv run alembic upgrade head'
seed-demo:
	./scripts/with-mode demo bash -c 'cd backend && uv run alembic upgrade head && uv run python -m app.cli seed-demo'
dev:
	$(RUN) python3 scripts/serve.py --dev
build:
	$(RUN) bash -c 'cd frontend && npm run build'
start:
	$(RUN) python3 scripts/serve.py
check: check-docs check-backend check-frontend
check-docs:
	$(RUN) python3 scripts/check-docs.py
check-backend:
	python3 scripts/test_phone_gateway.py
	$(RUN) bash -c 'cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app --ignore-missing-imports && uv run pytest tests/unit tests/test_*.py -m "not integration"'
.PHONY: generate-api-types check-api-types
generate-api-types:
	$(API_TYPES)
check-api-types:
	$(API_TYPES) --check
check-frontend: check-api-types
	$(RUN) bash -c 'cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build'
complexity:
	$(RUN) bash -c 'cd backend && uv run ruff check app --select C901 --config "lint.mccabe.max-complexity=15" --output-format concise || true'

test-db-start:
	python3 scripts/test-db.py start
test-db-stop:
	python3 scripts/test-db.py stop
test-integration:
	python3 scripts/test-db.py test $(TESTS)
test-integration-external:
	python3 scripts/test-db.py test-external $(TESTS)
test-e2e:
	$(RUN) bash -c 'cd frontend && npx playwright test'
sync:
	$(RUN) bash -c 'cd backend && uv run python -m app.cli sync'

backup:
	$(RUN) bash -c '$(BACKUP)'

.PHONY: phone-access
phone-access:
	python3 scripts/phone_gateway.py
