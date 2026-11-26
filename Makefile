SHELL := /bin/bash
RUN := ./scripts/run
GO_TOOLS := $(CURDIR)/private/go-tools/bin
export PATH := $(GO_TOOLS):$(PATH)
export GOTOOLCHAIN := go1.27.4
export GOPATH ?= $(CURDIR)/private/cache/go
export GOCACHE ?= $(CURDIR)/private/cache/go-build
export GOLANGCI_LINT_CACHE ?= $(CURDIR)/private/cache/golangci-lint
API_TYPES := python3 scripts/api-types.py
BACKUP := cd backend && uv run python -m app.cli backup "$$PRIVATE_DIR/backups/backup-$$(date +%Y%m%d-%H%M%S).tar.gz"
TESTS ?= tests/integration tests/test_ingestion_integration.py
.PHONY: doctor setup db-start db-stop migrate seed-demo dev build start check test-db-start test-db-stop test-integration test-integration-external test-e2e sync backup check-backend check-frontend check-docs complexity

doctor:
	$(RUN) python3 scripts/doctor.py
setup: setup-go
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
.PHONY: setup-go check-go check-go-vuln demo-go-proposals test-proposal-go test-proposal-go-external
setup-go:
	mkdir -p "$(GO_TOOLS)"
	GOBIN="$(GO_TOOLS)" go install github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.9.0
	GOBIN="$(GO_TOOLS)" go install github.com/sqlc-dev/sqlc/cmd/sqlc@v1.30.0
	GOBIN="$(GO_TOOLS)" go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.15.0
check-go: check-api-types
	cd backend-go && go build ./... && golangci-lint run --config ../.golangci.yml ./... && go test -race ./...
check-go-vuln:
	cd backend-go && go run golang.org/x/vuln/cmd/govulncheck@v1.10.0 ./...
demo-go-proposals:
	./scripts/with-mode demo bash -c 'cd backend-go && go run ./cmd/going-bananas serve'
test-proposal-go:
	python3 scripts/test-db.py proposal
test-proposal-go-external:
	python3 scripts/test-db.py proposal-external
check: check-docs check-backend check-frontend check-go
check-docs:
	$(RUN) python3 scripts/check-docs.py
check-backend:
	python3 scripts/test_phone_gateway.py
	$(RUN) bash -c 'cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app --ignore-missing-imports && uv run pytest tests/unit tests/test_*.py -m "not integration"'
.PHONY: generate-api-types check-api-types api-schema
api-schema:
	@$(API_TYPES) --schema
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
