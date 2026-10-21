"""A working fake of the SuperDocs endpoints docs-lint uses.

Exists so the whole suite runs with no API key and no spend. It is a simulator, not a mock: it
speaks real HTTP, holds real state across calls, runs a real job lifecycle, and can be told to
fail. Tests drive the actual `SuperDocsClient` against it, so request construction, retry
behaviour and response parsing are all genuinely under test - which mocking the client object
would not achieve.
"""

from .server import FakeSuperDocs, create_app

__all__ = ["FakeSuperDocs", "create_app"]
