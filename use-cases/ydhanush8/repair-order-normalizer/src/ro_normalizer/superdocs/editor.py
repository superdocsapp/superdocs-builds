"""The document editor interface.

Business logic depends on this protocol, never on HTTP. Two implementations:
`MockDocumentEditor` for the whole test suite, and the SuperDocs client for real
runs.

The minimum contract the assignment names is four calls: upload a document, send
an edit instruction, approve the proposed changes, export the finished file.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class DocumentRef:
    document_id: str
    filename: str


@dataclass
class ProposedChange:
    change_id: str
    section: str
    before: str
    after: str


@dataclass
class ProposedChanges:
    document_id: str
    changes: list[ProposedChange] = field(default_factory=list)


class DocumentEditor(Protocol):
    def upload(self, filename: str, content: str) -> DocumentRef: ...
    def propose_edit(self, document_id: str, instruction: str) -> ProposedChanges: ...
    def approve(self, document_id: str, change_ids: list[str]) -> int: ...
    def export(self, document_id: str) -> str: ...


def parse_proposed_content(payload: object) -> object:
    """Proposed-change content arrives as a JSON-encoded string.

    Documented by SuperDocs as the single most common reason integrators see
    empty diff cards where every field reads `undefined`: the first parse yields
    a string, and the string is itself JSON. The final result is already an
    object and must not be parsed again.

    Written as its own function so the behaviour can be tested without a network.
    """
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


class MockDocumentEditor:
    """An in-memory editor that behaves like the real one, including its quirks.

    It re-encodes proposed-change content as a JSON string, so the double-parse
    is exercised by every test rather than only against the live API.
    """

    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.filenames: dict[str, str] = {}
        self.pending: dict[str, list[ProposedChange]] = {}
        self.calls: list[tuple[str, str]] = []

    def upload(self, filename: str, content: str) -> DocumentRef:
        document_id = str(uuid.uuid4())
        self.documents[document_id] = content
        self.filenames[document_id] = filename
        self.pending[document_id] = []
        self.calls.append(("upload", document_id))
        return DocumentRef(document_id=document_id, filename=filename)

    def propose_edit(self, document_id: str, instruction: str) -> ProposedChanges:
        if document_id not in self.documents:
            raise KeyError(f"unknown document {document_id!r}")
        self.calls.append(("propose_edit", document_id))

        current = self.documents[document_id]
        changes: list[ProposedChange] = []

        # Parses the same natural-language instruction the real editor is given.
        # An earlier version matched a private `SECTION: X` format, which passed
        # here and produced "I am not sure what you would like help with" from
        # the live API. A mock that accepts something the real thing rejects is
        # worse than no mock.
        for match in re.finditer(
            r"^(COMPLAINT|CAUSE|CORRECTION): (.*?)(?=\n\n(?:COMPLAINT|CAUSE|CORRECTION): |\Z)",
            instruction,
            re.DOTALL | re.MULTILINE,
        ):
            section, replacement = match.group(1), match.group(2).strip()
            before = _section_text(current, section)
            if before != replacement:
                changes.append(
                    ProposedChange(
                        change_id=str(uuid.uuid4()),
                        section=section,
                        before=before,
                        after=replacement,
                    )
                )

        self.pending[document_id] = changes

        # Mirrors the real API: the transport hands back a JSON-encoded string.
        encoded = json.dumps(
            [
                {
                    "change_id": c.change_id,
                    "section": c.section,
                    "before": c.before,
                    "after": c.after,
                }
                for c in changes
            ]
        )
        decoded = parse_proposed_content(encoded)
        return ProposedChanges(
            document_id=document_id,
            changes=[ProposedChange(**item) for item in decoded],
        )

    def approve(self, document_id: str, change_ids: list[str]) -> int:
        self.calls.append(("approve", document_id))
        approved = [c for c in self.pending.get(document_id, []) if c.change_id in change_ids]

        content = self.documents[document_id]
        for change in approved:
            content = _replace_section(content, change.section, change.after)
        self.documents[document_id] = content

        # Rejected changes are dropped, not applied later.
        self.pending[document_id] = []
        return len(approved)

    def export(self, document_id: str) -> str:
        self.calls.append(("export", document_id))
        return self.documents[document_id]


def _section_text(document: str, section: str) -> str:
    match = re.search(rf"^{section}:\n(.*?)(?=\n[A-Z]+:\n|\Z)", document, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _replace_section(document: str, section: str, replacement: str) -> str:
    pattern = re.compile(rf"^({section}:\n)(.*?)(?=\n[A-Z]+:\n|\Z)", re.DOTALL | re.MULTILINE)
    if pattern.search(document):
        return pattern.sub(lambda m: m.group(1) + replacement, document)
    return document.rstrip() + f"\n\n{section}:\n{replacement}\n"
