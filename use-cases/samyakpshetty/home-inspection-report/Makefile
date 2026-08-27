# Every target runs in Docker (Python 3.12) so local matches CI byte for byte.
# The lint/type/test targets use --no-deps: the keyless suite needs no Postgres.

.DEFAULT_GOAL := help
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm --no-deps api

.PHONY: help build lint fmt typecheck typecheck-web test check demo verify test-db seed up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## Build the app image
	$(COMPOSE) build api

lint: build ## Ruff lint
	$(RUN) ruff check .

fmt: build ## Ruff format (writes)
	$(RUN) ruff format .

typecheck: build ## mypy --strict, a real gate
	$(RUN) mypy src

test: build ## Run the keyless test suite
	$(RUN) pytest

typecheck-web: ## TypeScript, strict, in the same container the UI runs in
	$(COMPOSE) run --rm --no-deps --entrypoint sh web -c "npx tsc -b --noEmit"

check: build ## The full gate: lint + format check + typecheck + tests + frontend types
	$(RUN) sh -c "ruff check . && ruff format --check . && mypy src && pytest"
	$(MAKE) typecheck-web

demo: build ## Build the sample report end to end (fakes by default; live if .env says so)
	$(RUN) python -m inspection_report.cli demo

verify: build ## Read the exported files back and prove the grouping
	$(RUN) python -m inspection_report.cli verify

test-db: build ## Run the tests that need a real Postgres (the rest of the suite does not)
	$(COMPOSE) run --rm api pytest -m postgres -q

seed: build ## Put the sample property in the database so the UI opens onto real data
	$(COMPOSE) run --rm api python -m inspection_report.cli seed --reset

up: ## Start the whole application (db + api + web)
	$(COMPOSE) up --build

down: ## Stop and remove containers
	$(COMPOSE) down

clean: ## Remove containers, images and volumes for this project
	$(COMPOSE) down --rmi local --volumes --remove-orphans
