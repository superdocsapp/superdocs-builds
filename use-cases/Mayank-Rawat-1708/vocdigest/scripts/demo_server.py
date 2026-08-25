"""
@file: scripts/demo_server.py
@description: Runs the real API server with the external clients replaced by the test
    fakes. Lets the full HTTP surface be exercised end to end with no API keys — the
    server, routing, database, background execution and SSE are all genuine; only Groq
    and SuperDocs are stubbed.
@flow: import the app -> swap GroqClient/SuperDocsClient in every backend module ->
    uvicorn.run
@dependencies: uvicorn, backend.main, backend.tests.conftest
"""
import sys
import uvicorn

import backend.main  # noqa: F401  - ensures all backend modules are imported first
import backend.tests.conftest as fakes


def patch_clients() -> int:
    patched = 0
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith("backend."):
            continue
        if hasattr(module, "GroqClient"):
            module.GroqClient = fakes.FakeGroqClient
            patched += 1
        if hasattr(module, "SuperDocsClient"):
            module.SuperDocsClient = fakes.FakeSuperDocsClient
            patched += 1
    return patched


if __name__ == "__main__":
    n = patch_clients()
    print(f"[demo] patched {n} client references — no live API keys will be used")
    uvicorn.run(backend.main.app, host="127.0.0.1", port=8000, log_level="warning")
