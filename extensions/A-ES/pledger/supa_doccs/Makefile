.PHONY: up down seed migrate demo clean test

# -------------------------------------------------------------------
# One command to bring the whole system up and seed the demo pile
# -------------------------------------------------------------------

demo: up migrate seed  ## Full bring-up + seed (the only command you need)
	@echo ""
	@echo "✔ System running. API at http://localhost:8000/health"
	@echo "  Frontend at http://localhost:5173 (run 'make frontend' separately)"
	@echo "  Postgres at localhost:5432 (user: postgres / pass: postgres / db: docdb)"
	@echo ""

up:  ## Start all containers (postgres + api)
	docker compose up -d --build --wait

down:  ## Stop all containers
	docker compose down

migrate:  ## Apply database migrations
	DATABASE_URL=postgresql://postgres:postgres@localhost:5432/docdb \
		uv run python migrations/run_migrations.py

seed:  ## Generate and insert synthetic demo pile
	DATABASE_URL=postgresql://postgres:postgres@localhost:5432/docdb \
		uv run python scripts/seed_demo.py

test:  ## Run full test suite (no DB required for most tests)
	uv run pytest tests/ -v --ignore=tests/test_schema

test-schema:  ## Run schema tests (requires running postgres)
	DATABASE_URL=postgresql://postgres:postgres@localhost:5432/docdb \
		uv run pytest tests/test_schema/ -v

frontend:  ## Start frontend dev server (requires node_modules installed)
	cd frontend && npm run dev

clean:  ## Remove containers and volumes
	docker compose down -v
	@echo "Cleaned."

help:  ## Show this help
	@grep -E '^[a-z_-]+:.*## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
