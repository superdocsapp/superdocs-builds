# Declare FastAPI backend

The Next.js client in `../web` calls this server at `http://localhost:8000/api` by default. No frontend code change is required for local development.

## Run locally

```powershell
cd use-cases/shashank-poola/declare/app
py -3.12 -m pip install -e ".[test]"
py -3.12 -m pytest -q
py -3.12 -m uvicorn main:app --reload --port 8000
```

Copy `.env.example` to `.env` and add provider keys only when using real GLM or SuperDocs calls.

## Layout

- `routes/analyze.py` and `routes/statements.py` own the Declare HTTP endpoints.
- `utils/analysis.py`, `utils/review.py`, and `utils/statements.py` contain independently tested business rules.
- `routes/superdocs.py` is the provider boundary; its provider calls are mocked in tests.
- `tests/` contains API-contract, focused utility, and provider-failure coverage.
