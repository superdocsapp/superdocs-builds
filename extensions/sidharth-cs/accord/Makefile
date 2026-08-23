.DEFAULT_GOAL := help
.PHONY: help setup dev test smoke

help:  ## Show this help
	@echo "Fresh clone to a running Milestone 0 server:"
	@echo "    make setup && make dev"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

setup:  ## Create a venv and install dependencies
	python3 -m venv .venv
	./.venv/bin/pip install -q --upgrade pip
	./.venv/bin/pip install -q -r requirements-dev.txt
	@echo ""
	@echo "Now: cp .env.example .env, fill in ZOOM_WEBHOOK_SECRET_TOKEN, then make dev"
	@echo "(add SUPERDOCS_API_KEY too if you're about to run 'make smoke')"

dev:  ## Run the backend (serves the panel and the webhook receiver on :8010)
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8010

test:  ## Run the test suite (no Zoom account, tunnel, or API key needed)
	cd backend && ../.venv/bin/python -m pytest

smoke:  ## Exercise the real SuperDocs API end to end (needs SUPERDOCS_API_KEY in .env)
	cd backend && PYTHONPATH=. ../.venv/bin/python scripts/smoke_superdocs_contract.py
