.PHONY: install test lint run down migrate
install:
	python -m pip install -e './backend[test]'
	cd frontend && npm install
test:
	cd backend && pytest
lint:
	cd backend && ruff check src tests && mypy src
	cd frontend && npm run build
run:
	docker compose up --build
migrate:
	cd backend && alembic upgrade head
down:
	docker compose down
