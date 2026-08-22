# SuperDocs Task 2: Supplier ESG & Code-of-Conduct Cycle Makefile
# All commands run locally without Docker

.PHONY: help install test test-backend test-frontend test-all reset-db dev-backend dev-frontend backend frontend build clean

help:
	@echo "================================================================="
	@echo " SuperDocs Task 2: Supplier ESG Cycle (No Docker)"
	@echo "================================================================="
	@echo " Available commands:"
	@echo "   make install       - Install backend (uv) and frontend (bun/npm) dependencies"
	@echo "   make reset-db      - Reset database & seed fresh suppliers to test from scratch"
	@echo "   make test          - Run the backend test suite (27 pytest tests)"
	@echo "   make test-frontend - Run the frontend test suite (14 bun tests)"
	@echo "   make test-all      - Run both backend & frontend test suites"
	@echo "   make backend       - Start the FastAPI backend on http://localhost:8001"
	@echo "   make frontend      - Start the Next.js frontend on http://localhost:3031"
	@echo "   make build         - Build the Next.js frontend production bundle"
	@echo "   make clean         - Remove temporary cache and build artifacts"
	@echo "================================================================="

# --- Dependency Installation ---
install:
	@echo "==> Installing backend dependencies with uv..."
	cd backend && uv sync
	@echo "==> Installing frontend dependencies with bun..."
	cd frontend && bun install

# --- Database Reset ---
reset-db:
	@echo "==> Resetting database and seeding fresh base suppliers..."
	cd backend && uv run python reset_db.py

# --- Automated Testing ---
test: test-backend
test-backend:
	@echo "==> Running Task 2 backend test suite (pytest)..."
	cd backend && uv run pytest -v

test-frontend:
	@echo "==> Running Task 2 frontend test suite (bun test)..."
	cd frontend && bun test

test-all: test-backend test-frontend

# --- Local Services (Run in 2 separate terminal windows) ---
backend: dev-backend
dev-backend:
	@echo "==> Starting FastAPI backend on http://localhost:8001..."
	cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

frontend: dev-frontend
dev-frontend:
	@echo "==> Starting Next.js frontend on http://localhost:3031..."
	cd frontend && bun run dev

# --- Production Build ---
build:
	@echo "==> Building Next.js frontend with Turbopack..."
	cd frontend && bun run build

# --- Cleanup ---
clean:
	@echo "==> Cleaning cache and temporary artifacts..."
	rm -rf backend/.pytest_cache backend/__pycache__ backend/app/**/__pycache__
	rm -rf frontend/.next
