"""HTTP API surface (optional machine driver).

The FastAPI instance lives on the ``generator.api.app`` *module* (``app.app``),
so the package does not shadow that submodule name.
"""

from .app import create_app

__all__ = ["create_app"]
