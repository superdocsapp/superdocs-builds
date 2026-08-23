SHELL := /bin/bash
COMPOSE := docker compose
DEV := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml

.DEFAULT_GOAL := help
.PHONY: help up dev down logs health test lint clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

up: ## Build and run — the command in README.md
	@mkdir -p data
	$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory health

dev: ## Run with reload-on-save
	@mkdir -p data ui/dist
	$(DEV) up --build

down: ## Stop everything this Makefile can start
	$(DEV) down

logs: ## Follow the service log
	$(COMPOSE) logs -f splitter

health: ## What this instance can and cannot do
	@sleep 1
	@curl -s http://localhost:8080/health | python3 -m json.tool || echo "not up yet — 'make logs'"

test: ## The suite: no key, no network
	uv run pytest -q
	cd ui && npm test

lint:  ## ruff + tsc
	uv run ruff check .
	cd ui && npm run typecheck

clean: ## Tool droppings. Leaves data/ alone
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name .DS_Store -delete
