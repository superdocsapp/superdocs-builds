.PHONY: dev
dev:
	@echo "Backend :8001  Frontend :5174  (Ctrl-C stops both)"
	@trap 'kill 0' EXIT INT TERM; \
	( cd backend && .venv/bin/uvicorn app.main:app --reload --port 8001 ) & \
	( cd frontend && npm run dev -- --port 5174 ) & \
	wait
