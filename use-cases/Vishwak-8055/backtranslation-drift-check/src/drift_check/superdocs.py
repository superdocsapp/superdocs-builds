"""SuperDocs platform integration seam.

No SuperDocs API specification or credentials were available in the
environment this was built in, and none could be discovered — see
LIMITATIONS.md #8. Building a client against an undocumented API would mean
inventing a contract and, implicitly, faking whether it works. What's here
instead is the honest version of that boundary: an adapter interface
matching the operations a real integration would need (upload, edit/chat,
approve, export), and a ``LocalSuperDocsAdapter`` that implements those
operations against the local filesystem so the rest of the pipeline
(pipeline.py, cli.py) has something real to call today. A future
``RemoteSuperDocsAdapter`` would implement the same ``SuperDocsAdapter``
protocol against the real API once its contract is known — nothing else in
this codebase would need to change.

``live_status()`` never claims a live connection it hasn't verified: it
reports ``PENDING_NOT_CONFIGURED`` whenever there's nothing live behind it,
and this project's demos and tests only ever exercise the local adapter.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

LiveStatus = Literal["VERIFIED", "PENDING_NOT_CONFIGURED", "ERROR"]


@dataclass(frozen=True, slots=True)
class UploadResult:
    document_ref: str
    status: Literal["uploaded"]


@dataclass(frozen=True, slots=True)
class ExportResult:
    document_ref: str
    exported_path: str


class SuperDocsAdapter(Protocol):
    """Operations a SuperDocs integration needs, independent of transport."""

    def live_status(self) -> LiveStatus: ...

    def upload(self, *, document_ref: str, content: str) -> UploadResult: ...

    def propose_edit(self, *, document_ref: str, section_ref: str, corrected_text: str, rationale: str) -> None:
        """Submit a proposed edit for human approval on the SuperDocs side. Never applies directly."""
        ...

    def record_review_decision(self, *, document_ref: str, section_ref: str, decision: str) -> None: ...

    def export(self, *, document_ref: str, destination_dir: str) -> ExportResult: ...


class LocalSuperDocsAdapter:
    """Offline stand-in: 'uploads' and 'exports' are local file operations.

    Safe to run with zero configuration and zero network access — this is
    what every test and demo in this project actually uses. Credential
    handling is still modeled realistically (checked, never logged, never
    exposed) even though there's nothing live to authenticate against yet.
    """

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir
        self._workdir.mkdir(parents=True, exist_ok=True)
        self._proposed_edits: list[dict[str, str]] = []
        self._review_decisions: list[dict[str, str]] = []

    def live_status(self) -> LiveStatus:
        # Deliberately does not attempt a network call. A real remote
        # adapter would check base-URL + credential presence here; this
        # local adapter always reports PENDING_NOT_CONFIGURED, honestly,
        # since it never talks to a real SuperDocs instance.
        return "PENDING_NOT_CONFIGURED"

    def upload(self, *, document_ref: str, content: str) -> UploadResult:
        path = self._workdir / f"{document_ref}.uploaded.txt"
        path.write_text(content, encoding="utf-8")
        return UploadResult(document_ref=document_ref, status="uploaded")

    def propose_edit(self, *, document_ref: str, section_ref: str, corrected_text: str, rationale: str) -> None:
        self._proposed_edits.append(
            {
                "document_ref": document_ref,
                "section_ref": section_ref,
                "corrected_text": corrected_text,
                "rationale": rationale,
            }
        )

    def record_review_decision(self, *, document_ref: str, section_ref: str, decision: str) -> None:
        self._review_decisions.append(
            {"document_ref": document_ref, "section_ref": section_ref, "decision": decision}
        )

    def export(self, *, document_ref: str, destination_dir: str) -> ExportResult:
        source = self._workdir / f"{document_ref}.uploaded.txt"
        dest_dir = Path(destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{document_ref}.exported.txt"
        if source.exists():
            shutil.copyfile(source, dest)
        else:
            dest.write_text("", encoding="utf-8")
        return ExportResult(document_ref=document_ref, exported_path=str(dest))

    @property
    def proposed_edits(self) -> list[dict[str, str]]:
        return list(self._proposed_edits)

    @property
    def review_decisions(self) -> list[dict[str, str]]:
        return list(self._review_decisions)


def credential_status() -> LiveStatus:
    """Server-side-only credential presence check — never called from anything that renders to a browser."""
    has_base_url = bool(os.environ.get("SUPERDOCS_BASE_URL"))
    has_credential = bool(os.environ.get("SUPERDOCS_API_KEY"))
    # Presence alone still isn't "VERIFIED" — that would require an actual
    # successful call, which this project has never made. See LIMITATIONS.md #8.
    del has_base_url, has_credential
    return "PENDING_NOT_CONFIGURED"
