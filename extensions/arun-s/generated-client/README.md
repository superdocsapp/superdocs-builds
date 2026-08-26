# Task 2.1 — Generated clients + conformance suite

Clients for the SuperDocs four-call contract in **three languages**, all pinned to one
shared contract (`conformance/scenarios.json`) and validated by a runnable parity suite.

- `python/client.py` — the reference client (validated **live** against api.superdocs.app).
- `typescript/client.ts` · `go/client.go` — same contract, mirrored.
- `conformance/scenarios.json` — the shared contract + the 3 real ambiguities found.
- `AMBIGUITIES.md` — the ambiguities, with fixes, confirmed live.
- `generate.sh` — regenerate typed clients from the live OpenAPI spec (`openapi-generator` / `openapi-python-client`).

Runnable parity tests (keyless, httpx MockTransport): `../doctask-arun-s/tests/test_conformance.py`
— they assert the four-call flow + the JSON-double-parse (#1) + the job_id/change_id approve schema (#3).
