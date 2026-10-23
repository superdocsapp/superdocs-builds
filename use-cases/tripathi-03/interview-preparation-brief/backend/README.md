# Backend — Interview Preparation Brief

## Modules

- `app/api` — FastAPI routers + dependency injection
- `app/services` — parsers, RAG, company research, brief services
- `app/agents` — LangGraph 7-node workflow
- `app/models` — SQLAlchemy ORM
- `app/schemas` — Pydantic models
- `app/database` — engine, sessions, bootstrap
- `app/utils` — evidence guard / helpers
- `app/core` — config, logging, exceptions

## Run

```bash
# from repo root
docker compose up -d db
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs
