"""sdmock -- an offline mock of the SuperDocs REST API and MCP server.

Serves recorded responses so integration tests run with no key, no quota and no flake,
and ships a contract suite that runs the same assertions against the live service to
prove the two still agree.

Built on SuperDocs, not a copy of it: there is no document engine here.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
