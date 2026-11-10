SHELL := /bin/bash
RUN := ./scripts/run
.PHONY: doctor setup db-start db-stop migrate seed-demo dev build start check test-integration test-e2e sync

doctor:
	$(RUN) python3 scripts/doctor.py
setup:
	$(RUN) bash -c 'cd backend && uv sync --python 3.12'
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
	$(RUN) bash -c 'cd backend && uv run ruff check . && uv run pytest tests/unit'
	$(RUN) bash -c 'cd frontend && npm run lint && npm run typecheck && npm test && npm run build'
test-integration:
	$(RUN) bash -c 'cd backend && uv run pytest tests/integration'
test-e2e:
	$(RUN) bash -c 'cd frontend && npx playwright test'
sync:
	$(RUN) bash -c 'cd backend && uv run python -m app.cli sync'
