# Every target runs in Docker (Python 3.12) so local == CI, byte for byte.
# The lint/type/test targets use --no-deps: the keyless suite needs no Postgres.

.DEFAULT_GOAL := help
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm --no-deps app

.PHONY: help build lint fmt typecheck test check demo send review watch status up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## Build the app image
	$(COMPOSE) build

lint: build ## Ruff lint
	$(RUN) ruff check .

fmt: build ## Ruff format (writes)
	$(RUN) ruff format .

typecheck: build ## mypy (strict, a real gate)
	$(RUN) mypy src

test: build ## Run the keyless test suite
	$(RUN) pytest

test-postgres: build ## Run the Postgres-backed store test against the real db service
	RUN_POSTGRES_TESTS=1 $(COMPOSE) run --rm -e RUN_POSTGRES_TESTS=1 app pytest -m postgres

check: build ## The full CI gate: lint + typecheck + tests
	$(RUN) sh -c "ruff check . && ruff format --check . && mypy src && pytest"

demo: build ## Full round-trip on the fake providers — no keys, no ops, no Postgres
	$(RUN) python -m notion_review.cli demo

# --- Live targets. All need SUPERDOCS_API_KEY + NOTION_TOKEN in .env ---
LIVE := PROVIDER=live $(COMPOSE) run --rm --no-deps app python -m notion_review.cli

send: build ## Send a page for review: make send PAGE=<notion-page-id> (lands in outbox/)
	$(LIVE) send --page-id $(PAGE)

review: build ## Apply a returned review: make review FILE=inbox/<marked-up.docx>
	$(LIVE) review --markup $(FILE) --interactive

watch: build ## Run the service unattended (ARGS=--once for a single pass, e.g. under cron)
	$(LIVE) watch --inbox inbox --outbox outbox $(ARGS)

status: build ## What every review round is doing (add ROUND=<id> for one in full)
	$(LIVE) status $(if $(ROUND),--round-id $(ROUND),)

up: ## Start db + app in the background
	$(COMPOSE) up -d

down: ## Stop and remove containers
	$(COMPOSE) down

clean: ## Remove containers, images, volumes for this project
	$(COMPOSE) down --rmi local --volumes --remove-orphans
