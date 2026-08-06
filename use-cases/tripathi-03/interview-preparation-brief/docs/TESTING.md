# Testing Guide

All tests are designed to run **without live OpenAI/Anthropic API keys**.

## Backend (Pytest)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest
```

### Suites

| Path | Purpose |
|------|---------|
| `tests/unit/` | Parsers, guards, assemblers, mocked services |
| `tests/langgraph/` | Graph wiring + node/workflow tests with mocked LLM |
| `tests/integration/` | FastAPI TestClient routes with dependency overrides |
| `tests/mocks/openai_mocks.py` | Deterministic structured LLM fixtures |

### Mocking strategy

- `OPENAI_API_KEY` is set to a dummy value in fixtures
- `invoke_structured` / `invoke_text` are patched via `mock_llm`
- Embeddings are patched via `mock_embeddings`
- DB lifespan is no-op’d in API integration tests

```bash
pytest tests/unit -q
pytest tests/langgraph -q
pytest tests/integration -q
```

## Frontend (Vitest + React Testing Library)

```bash
cd frontend
npm install
npm test
```

## CI

GitHub Actions workflow: `.github/workflows/ci.yml`

Runs backend pytest (unit + langgraph + integration) and frontend vitest/typecheck/build on push/PR.
