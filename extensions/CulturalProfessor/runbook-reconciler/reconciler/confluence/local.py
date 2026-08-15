"""The corpus, served through the same interface as Confluence Cloud.

This is what makes "a stranger can run it in minutes" true. `rr check` against
the bundled corpus needs no Confluence site, no token and no network, and it
exercises the same extraction, checking and review code that the live adapter
drives — the only thing swapped is where the bytes come from.

It is also the honest place to put the write path for a demo. `LocalSource.write`
applies a splice to a file on disk and bumps a version number, so the resume,
concurrency and byte-identity tests can prove their properties against something
that really persists rather than against a mock that agrees with them.

The interface both sources share is small on purpose: list pages, read one, write
one back with an expected version. Anything larger would be a Confluence client
leaking into the parts of this project that should not know what Confluence is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from reconciler.extract.storage import Document, parse


@dataclass(frozen=True)
class PageRef:
    page_id: str
    title: str
    version: int
    labels: tuple[str, ...]
    url: str = ""
    #: Who last edited the page, where the source can say. Empty from the
    #: corpus, and empty from Confluence too when the token cannot resolve it —
    #: the watcher treats "unknown" as "not us" rather than guessing.
    author_id: str = ""


class VersionConflict(RuntimeError):
    """Somebody else wrote to the page since it was read.

    Not an error to retry blindly. The passage this tool meant to edit may not
    be where it was, or may not say what it said, so the anchor is re-resolved
    and the finding re-proposed rather than the write being repeated.
    """


class LocalSource:
    """A directory of `<id>.page.json` + `<id>.storage.xhtml` pairs."""

    def __init__(self, directory: Path, label: str = "runbook") -> None:
        self.directory = Path(directory)
        self.label = label

    def pages(self) -> list[PageRef]:
        out: list[PageRef] = []
        for meta_path in sorted(self.directory.glob("*.page.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            labels = tuple(meta.get("labels") or ())
            if self.label and self.label not in labels:
                continue
            out.append(
                PageRef(
                    page_id=str(meta["id"]),
                    title=str(meta.get("title", "")),
                    version=int((meta.get("version") or {}).get("number", 1)),
                    labels=labels,
                    url=str((meta.get("_links") or {}).get("webui", "")),
                )
            )
        return out

    def read(self, page_id: str) -> Document:
        meta = json.loads(self._meta_path(page_id).read_text(encoding="utf-8"))
        body = self._body_path(page_id).read_text(encoding="utf-8")
        return parse(
            body,
            page_id=page_id,
            version=int((meta.get("version") or {}).get("number", 1)),
            title=str(meta.get("title", "")),
        )

    def write(self, page_id: str, body: str, expected_version: int) -> int:
        """Persist a new body, refusing if the page moved on underneath us.

        The same optimistic-concurrency contract the real API gives for free via
        `version.number`. Implementing it here rather than letting the local
        source be permissive is what lets the concurrency test be about the
        product's behaviour instead of about Confluence's.
        """
        meta_path = self._meta_path(page_id)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        current = int((meta.get("version") or {}).get("number", 1))
        if current != expected_version:
            raise VersionConflict(
                f"page {page_id} is at version {current}, not {expected_version}; "
                f"re-resolve the anchor rather than retrying this write"
            )
        self._body_path(page_id).write_text(body, encoding="utf-8")
        meta["version"] = {**(meta.get("version") or {}), "number": current + 1}
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return current + 1

    def comment(self, page_id: str, text: str) -> str:
        """The fallback for a passage this tool refuses to edit.

        Appended to a sidecar file rather than the page body: a comment is not
        page content, and writing one into the body would be exactly the
        unrequested edit the whole design is built to avoid.
        """
        path = self.directory / f"{page_id}.comments.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        existing.append({"body": text})
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return f"local-comment-{len(existing)}"

    def comments(self, page_id: str) -> list[dict]:
        path = self.directory / f"{page_id}.comments.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def _meta_path(self, page_id: str) -> Path:
        return self.directory / f"{page_id}.page.json"

    def _body_path(self, page_id: str) -> Path:
        return self.directory / f"{page_id}.storage.xhtml"


__all__ = ["LocalSource", "PageRef", "VersionConflict"]
