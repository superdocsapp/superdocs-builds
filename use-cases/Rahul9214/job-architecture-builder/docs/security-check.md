# Secret and history check

Performed 2026-08-26 on branch `task2-job-architecture-builder` at commit `274866eda8d266221853e79bff6862bfe653a9fc` plus uncommitted Phase 9 docs/screenshots/CSS. No real API key was printed.

## Commands

```text
git ls-files "use-cases/Rahul9214/job-architecture-builder"
git ls-files "use-cases/Rahul9214/job-architecture-builder" | findstr /i ".env .runtime exports artifacts .venv node_modules dist"
git grep -n -I -E "SUPERDOCS_API_KEY=|Bearer |sk_live|sk_test_|api_key|Authorization:" -- "use-cases/Rahul9214/job-architecture-builder"
git log --oneline -- "use-cases/Rahul9214/job-architecture-builder/.env"
git log --all --oneline -S "sk_live_" -- "use-cases/Rahul9214/job-architecture-builder"
Test-Path use-cases/Rahul9214/job-architecture-builder/.env
```

## Tracked generated / secret paths

`git ls-files` listed **155** paths under the use-case at HEAD. None matched `.env`, `.runtime/`, `exports/`, `artifacts/`, `.venv/`, `node_modules/`, or `web/dist/`.

`.gitignore` ignores those directories plus `.env` (keeps `.env.example`).

Local `.env` **does not exist** in this working tree (`Test-Path` false).

## Pattern matches in tracked content (false positives investigated)

| Match | Verdict |
| --- | --- |
| `.env.example`: `SUPERDOCS_API_KEY=your-key-here` | Placeholder only |
| `tests/*`: `sk_test_offline_not_a_real_key` | Offline fake; not a live credential |
| `tests/test_web_api.py`: `sk_live_should_never_appear` | Test sentinel; assert it never appears in API JSON |
| `superdocs/client.py`: builds `Authorization: Bearer {api_key}` | Runtime header construction; key is redacted in logs/repr |
| `live/state.py`: names `api_key` / `superdocs_api_key` | Refusal list so runtime JSON cannot store those fields |
| `web/service.py`: `SECRET_SUBSTRINGS` | Redaction filter for SuperDocs status payloads |

`git log` for path `.env` is empty (file never tracked).

`git log -S "sk_live_"` points at commit `274866e` (the web-app test sentinel), not a real key.

## Web API

`GET /api/superdocs/status` is covered by `tests/test_web_api.py`: even when `SUPERDOCS_API_KEY` is set in the test env, the response body must not include the sentinel, `SUPERDOCS_API_KEY`, or Authorization material.

## Outcome

No live SuperDocs key, Bearer token, or `.env` contents found in tracked files or in `.env` history for this use-case. Runtime state, exports, artifacts, venv, node_modules, and production `web/dist` are gitignored.
