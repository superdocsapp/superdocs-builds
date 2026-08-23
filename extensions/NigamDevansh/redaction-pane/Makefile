# Shortcuts. Every one of them is a command from README.md — nothing here is a
# secret path, and the add-in runs without this file.
#
#     make certs      once, on the host: Office refuses an http:// task pane
#     make up         the documented run — builds the image, serves it
#     make dev        the same, plus reload-on-save (docker-compose.dev.yml)
#     make sideload   copy manifest.xml where Word looks for it
#     make health     what this instance can and cannot do right now

SHELL := /bin/bash
COMPOSE := docker compose
DEV := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
WEF := $(HOME)/Library/Containers/com.microsoft.Word/Data/Documents/wef

.DEFAULT_GOAL := help
.PHONY: help certs up dev restart down logs health sideload sample test lint clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

certs: ## Generate and trust the localhost certificate (host keychain, asks for your password)
	npx office-addin-dev-certs install

up: ## Build and run the real image — the command in README.md
	@mkdir -p data
	$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory health

dev: ## Run with reload-on-save: service/ and ui/dist mounted, vite in watch mode
	@mkdir -p data ui/dist
	$(DEV) up --build

restart: ## Re-read .env. Editing .env alone does nothing — it is read at container start
	@mkdir -p data ui/dist
	$(DEV) up -d --force-recreate
	@$(MAKE) --no-print-directory health

down: ## Stop everything this Makefile can start, dev containers included
	$(DEV) down

logs: ## Follow the service log
	$(COMPOSE) logs -f redaction

health: ## Which detection tiers this configuration can actually run
	@sleep 1
	@curl -sk https://localhost:8443/health | python3 -m json.tool || \
	  echo "not up yet — 'make logs' to see why"

sideload: ## Copy the manifest into Word's sideload folder (then RESTART Word)
	@mkdir -p "$(WEF)"
	cp manifest.xml "$(WEF)/"
	@echo "Copied. Word caches manifests at launch: quit Word and reopen it."

sample: ## Build the demo document — one of everything, in every place it hides
	uv run python scripts/make_sample.py

test: ## The suite that needs no keys, no network and no Word
	uv run pytest -q
	cd ui && npm test

lint: ## ruff + tsc. `make dev` skips typechecking; this is where it happens
	uv run ruff check .
	cd ui && npm run typecheck

clean: ## Remove build output and tool droppings. Leaves data/ alone
	rm -rf ui/dist .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name .DS_Store -delete
