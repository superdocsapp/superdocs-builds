.PHONY: help install backend frontend test build-frontend clean

help:
	@echo "Targets:"
	@echo "  install        - uv sync + npm install, creates .env from .env.example"
	@echo "  backend        - run the FastAPI backend on :8000 (reads .env for SUPERDOCS_API_KEY)"
	@echo "  frontend       - run the Vite dev server on :5173"
	@echo "  test           - run the offline test suite (no live SuperDocs calls)"
	@echo "  build-frontend - production build of the frontend"
	@echo "  clean          - remove venv, node_modules, build artifacts, caches"

install:
	uv sync
	cd app/frontend && npm install
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example — edit it and set SUPERDOCS_API_KEY."; \
	fi

backend:
	uv run uvicorn app.backend.main:app --reload --port 8000

frontend:
	cd app/frontend && npm run dev

test:
	uv run pytest tests/ -q

build-frontend:
	cd app/frontend && npm run build

clean:
	rm -rf .venv app/frontend/node_modules app/frontend/dist .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
