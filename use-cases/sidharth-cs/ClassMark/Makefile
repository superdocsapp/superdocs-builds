.DEFAULT_GOAL := help
.PHONY: help setup dev frontend-dev build-frontend test smoke

help:  ## Show this help
	@echo "Google Classroom Feedback add-on — quick start:"
	@echo "    make setup && make dev"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup:  ## Create a venv, install dependencies, build the frontend
	python3 -m venv .venv
	./.venv/bin/pip install -q --upgrade pip
	./.venv/bin/pip install -q -r requirements-dev.txt
	cd frontend && npm install && npm run build
	@echo ""
	@echo "Now: cp .env.example .env, fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,"
	@echo "     SUPERDOCS_API_KEY, SESSION_SECRET. Then: make dev"

dev:  ## Run the backend on :8020 (serves the built frontend at /)
	cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8020

frontend-dev:  ## Run the Vite dev server (proxy /api -> :8020)
	cd frontend && npm run dev

build-frontend:  ## Build the frontend for production
	cd frontend && npm run build

test:  ## Run unit + integration tests (no network, no API keys needed)
	cd backend && ../.venv/bin/python -m pytest

smoke:  ## Live end-to-end loop (needs GOOGLE_CLIENT_ID/SECRET, SUPERDOCS_API_KEY, test Classroom)
	cd backend && PYTHONPATH=. ../.venv/bin/python scripts/smoke_classroom_loop.py
