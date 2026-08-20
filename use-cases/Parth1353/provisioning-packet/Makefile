.DEFAULT_GOAL := help
PY ?= python3

.PHONY: help
help:
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install the package and dev dependencies
	$(PY) -m pip install -e ".[dev]"

.PHONY: audit
audit: ## Check the templates. No API key needed.
	$(PY) -m packet audit

.PHONY: test
test: ## Run the test suite. No API key, no network.
	$(PY) -m pytest -q

.PHONY: plan
plan: ## Cost a build and a change without spending anything
	$(PY) -m packet build --dry-run
	$(PY) -m packet change --set delivery.rfs_date=2026-04-30 --dry-run

.PHONY: demo
demo: ## The full walkthrough. Needs SUPERDOCS_API_KEY.
	@bash demo.sh

.PHONY: lint
lint:
	$(PY) -m ruff check packet tests
