"""
app.config raises at import time if SUPERDOCS_API_KEY isn't set - a
deliberate fail-fast for the real app. The offline test suite imports
modules that transitively import app.config (e.g. nightly_batch ->
report_pipeline -> report_extractor -> superdocs_service -> app.config)
without ever making a live call (SuperDocsClient is never instantiated
in the offline tests; process_report is monkeypatched where needed).

Setting a placeholder here - before any test module imports the app -
satisfies that import-time guard without requiring a real key or
touching app/config.py's behavior.
"""

import os

os.environ.setdefault("SUPERDOCS_API_KEY", "offline-test-placeholder-not-a-real-key")
os.environ.setdefault("SUPERDOCS_BASE_URL", "https://example.invalid")
