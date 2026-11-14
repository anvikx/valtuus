.PHONY: setup check check-be check-fe check-infra fmt dev-be dev-fe up down

# Same image as the CI infra job. actionlint 1.7.12, ships shellcheck.
LINT_IMAGE := rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667
LINT_RUN := docker run --rm -v "$(CURDIR):/repo" -w /repo

setup:
	cd backend && uv sync
	cd frontend && npm ci

# Same steps as CI. Run before every push.
check: check-be check-fe check-infra

check-be:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest

check-fe:
	cd frontend && npm run typecheck && npm run lint && npm run format:check && npm run build

check-infra:
	$(LINT_RUN) $(LINT_IMAGE)
	$(LINT_RUN) --entrypoint shellcheck $(LINT_IMAGE) scripts/deploy.sh

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

dev-be:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-fe:
	cd frontend && npm run dev

# Full stack as in prod, built locally. http://localhost
up:
	docker compose up -d --build --wait

down:
	docker compose down
