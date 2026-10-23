# Testing

All tests run **without live OpenAI/Anthropic keys**.

```bash
# Backend
cd backend && pip install -r requirements.txt && pytest

# Frontend
cd frontend && npm install && npm test
```

CI: `.github/workflows/ci.yml`  
Details: [docs/TESTING.md](docs/TESTING.md)
