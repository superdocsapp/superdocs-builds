"""One CA bundle for every benchmark script.

Homebrew/python.org Python on macOS ships no CA bundle, so every HTTPS
request dies with CERTIFICATE_VERIFY_FAILED until someone runs
'Install Certificates.command'. certifi carries one and is already in this
project's venv.

This lives in one place because the same eight lines were pasted into
run_benchmark.py, demo.py and helper/helper.py one at a time, each after
the trap had bitten again — and run_template_suite.py, which nobody
remembered, then failed all four templates on the same error months later.
demo.py and helper/helper.py keep their own copies on purpose: both are
run standalone from outside this directory and must not import from it.
"""

import ssl


def ssl_context_for(backend_url: str) -> ssl.SSLContext | None:
    """A verifying context for https:// backends, None for plain http."""
    if not backend_url.startswith("https://"):
        return None
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
