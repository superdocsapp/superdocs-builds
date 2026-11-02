"""The Confluence Cloud adapter: auth discovery, reads, and the splice.

`page_source` is the one place that decides between the live site and the
bundled corpus. Every command takes a source rather than constructing one, so
the decision is made once, at the edge, from configuration -- and the pipeline
underneath genuinely cannot tell which it is talking to. That is not a
convenience: it is what makes `rr check` on a fresh clone exercise the same
extraction, checking, splice and review code that the live path does, instead of
an offline imitation of it that is free to drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from reconciler.confluence.local import LocalSource, PageRef
from reconciler.extract.storage import Document

if TYPE_CHECKING:
    from reconciler.config import Config


class PageSource(Protocol):
    """List, read, write, comment. Deliberately no larger than this.

    Anything wider would be a Confluence client leaking into modules that should
    not know Confluence exists.
    """

    def pages(self) -> list[PageRef]: ...

    def read(self, page_id: str) -> Document: ...

    def write(self, page_id: str, body: str, expected_version: int) -> int: ...

    def comment(self, page_id: str, text: str) -> str: ...


def page_source(config: Config) -> PageSource:
    """The live site when `config.wants_confluence`, the corpus otherwise.

    Configured means all three of site, email and token -- a half-filled `.env`
    resolves to the corpus rather than to a client that fails on its first call,
    because a stranger who has filled in one of the three deserves output and a
    clear line about what it read, not a traceback from `discover()`. Asking for
    Confluence explicitly and not having it configured is the one case that is
    an error rather than a fallback: silently reading the corpus when somebody
    said `RR_SOURCE=confluence` would report the corpus's drift as their wiki's.

    The import is local because `client.py` pulls in httpx and the whole offline
    path -- `rr check`, the tests, the demo's free half -- has no use for it.
    """
    if not config.wants_confluence:
        return LocalSource(config.runbook_source or Path("fixtures/runbooks"), config.runbook_label)
    if not config.has_confluence:
        raise RuntimeError(
            "RR_SOURCE=confluence, but CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL and "
            "CONFLUENCE_API_TOKEN are not all set. See .env.example."
        )

    from reconciler.confluence.client import ConfluenceSource

    return ConfluenceSource.from_config(config)


def describe_source(source: PageSource) -> str:
    """What a run says it read, so no output is ambiguous about its own inputs."""
    if isinstance(source, LocalSource):
        return f"the bundled corpus at {source.directory}"
    space = getattr(source, "space_key", "") or "every space the token can see"
    return f"Confluence ({space}, label {getattr(source, 'label', 'runbook')!r})"


__all__ = ["PageSource", "describe_source", "page_source"]
