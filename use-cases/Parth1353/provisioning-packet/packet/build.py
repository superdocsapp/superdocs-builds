"""Building a pack.

One order record in, six documents out, twice — once for the delivery team and
once for the customer. Both renders come from the same record through the same
templates; the only thing that differs is the audience passed to the renderer,
which is what makes the card's "differ only in what should be hidden" a
structural property rather than a promise.

The documents are uploaded into **one SuperDocs session** so the pack behaves
like a pack: the AI can see all six at once, edits can target any of them by id,
and a later change can be applied across the set in a single conversation.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from packet.order import Order
from packet.superdocs import SuperDocs, SuperDocsError
from packet.templates import DOCUMENTS, render

log = logging.getLogger(__name__)

AUDIENCES = ("internal", "customer")


@dataclass
class BuiltDocument:
    slug: str
    title: str
    audience: str
    session_id: str
    document_id: str | None
    durable_id: str | None
    local_path: str
    chunk_count: int | None = None
    content_sha256: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Pack:
    """A built pack, and everything needed to change it later."""

    order_reference: str
    order_fingerprint: str
    audience: str
    session_id: str
    documents: list[BuiltDocument] = field(default_factory=list)
    built_at: float = field(default_factory=time.time)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def by_slug(self, slug: str) -> BuiltDocument | None:
        return next((d for d in self.documents if d.slug == slug), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_reference": self.order_reference,
            "order_fingerprint": self.order_fingerprint,
            "audience": self.audience,
            "session_id": self.session_id,
            "built_at": self.built_at,
            "documents": [d.as_dict() for d in self.documents],
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Pack:
        pack = cls(
            order_reference=raw["order_reference"],
            order_fingerprint=raw["order_fingerprint"],
            audience=raw["audience"],
            session_id=raw["session_id"],
            built_at=raw.get("built_at", 0.0),
            warnings=raw.get("warnings", []),
        )
        pack.documents = [BuiltDocument(**d) for d in raw["documents"]]
        return pack


class Workspace:
    """Where a build keeps its output and its manifest.

    The manifest is what makes the second command work: ``packet change`` needs
    to know which SuperDocs session and document ids belong to which slug, and
    re-deriving that would mean re-uploading.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def dir_for(self, audience: str) -> Path:
        d = self.root / audience
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def save(self, packs: dict[str, Pack], order: Order) -> None:
        self.manifest_path.write_text(
            json.dumps(
                {
                    "order_reference": order.value("order.reference"),
                    "order_fingerprint": order.fingerprint(),
                    "order_source": order.source,
                    "packs": {a: p.as_dict() for a, p in packs.items()},
                },
                indent=2,
            )
        )

    def load(self) -> dict[str, Pack]:
        if not self.manifest_path.exists():
            raise SuperDocsError(
                f"no manifest at {self.manifest_path}",
                fix="run `packet build` first — change and verify work on a built pack",
            )
        raw = json.loads(self.manifest_path.read_text())
        return {a: Pack.from_dict(p) for a, p in raw["packs"].items()}


# ---------------------------------------------------------------------------


def session_id_for(order: Order, audience: str) -> str:
    """Stable and readable. Reusing it means a rebuild continues the same
    conversation rather than orphaning the previous one."""
    ref = re.sub(r"[^A-Za-z0-9]+", "-", str(order.raw("order.reference", "order"))).lower()
    return f"packet-{ref}-{audience}-v3"


def build_pack(
    client: SuperDocs,
    order: Order,
    *,
    audience: str,
    workspace: Workspace,
    only: list[str] | None = None,
) -> Pack:
    """Render, save locally, and upload every document for one audience."""
    session_id = session_id_for(order, audience)
    out_dir = workspace.dir_for(audience)
    pack = Pack(
        order_reference=str(order.raw("order.reference")),
        order_fingerprint=order.fingerprint(),
        audience=audience,
        session_id=session_id,
    )

    specs = [d for d in DOCUMENTS if not only or d.slug in only]
    for spec in specs:
        html = render(spec, order, audience=audience)
        local = out_dir / f"{spec.slug}.html"
        local.write_text(html, encoding="utf-8")

        uploaded = client.upload_document(
            local, session_id=session_id, open_mode="new_focused"
        )
        doc_id, durable_id, chunks = _identify(uploaded)

        pack.documents.append(
            BuiltDocument(
                slug=spec.slug,
                title=spec.title,
                audience=audience,
                session_id=session_id,
                document_id=doc_id,
                durable_id=durable_id,
                local_path=str(local),
                chunk_count=chunks,
                content_sha256=_sha(html),
            )
        )
        log.info("built %s/%s (%s chunks)", audience, spec.slug, chunks)

    if not client.ledger.dry_run:
        _reconcile_ids(client, pack)
    return pack


def _reconcile_ids(client: SuperDocs, pack: Pack) -> None:
    """Read the ids back from the session roster and correct the manifest.

    The roster is the authoritative answer to "what is in this session", and it
    is a free call. Trusting the upload response instead is how this build
    shipped a manifest full of nulls: the base64 upload response carries no
    document id at all, so every later edit had nothing to target and the whole
    propagation silently skipped. Reading back costs nothing and cannot be
    wrong.

    A pack whose roster does not match what it uploaded is a hard failure, not
    a warning — continuing would mean editing the wrong document.
    """
    try:
        roster = client.list_session_documents(pack.session_id)
    except SuperDocsError as exc:
        log.warning("could not read the session roster for %s: %s", pack.session_id, exc)
        return

    by_title = {
        (d.get("title") or "").strip().lower(): d for d in roster.get("documents", [])
    }
    for doc in pack.documents:
        match = by_title.get(doc.slug.lower()) or by_title.get(
            Path(doc.local_path).stem.lower()
        )
        if match:
            doc.document_id = match.get("document_id") or doc.document_id
            doc.durable_id = match.get("durable_document_id") or doc.durable_id
            doc.chunk_count = match.get("chunks_count") or doc.chunk_count

    missing = [d.slug for d in pack.documents if not d.document_id]
    if missing:
        raise SuperDocsError(
            f"session {pack.session_id} has {len(roster.get('documents', []))} document(s) "
            f"but these uploads have no id: {', '.join(missing)}",
            fix="the upload did not open a new document. Check that upload_document is "
            "using the multipart endpoint with open_mode=new_focused — the base64 "
            "endpoint replaces the focused document instead of adding one.",
        )


def _identify(uploaded: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    """Best effort at the ids from an upload response.

    The multipart response carries a top-level ``document_id`` and a roster
    whose entries use ``document_id`` (not ``id``); the base64 response carries
    neither. Whatever this returns is corrected against the session roster in
    ``_reconcile_ids``, which is the actual source of truth.
    """
    roster = uploaded.get("documents") or uploaded.get("session_documents") or []
    focused = next((d for d in roster if d.get("focused")), None) or (
        roster[-1] if roster else {}
    )
    doc_id = (
        focused.get("document_id")
        or focused.get("id")
        or uploaded.get("document_id")
        or uploaded.get("id")
    )
    durable = (
        focused.get("durable_document_id")
        or uploaded.get("durable_document_id")
        or focused.get("durable_id")
    )
    chunks = (
        focused.get("chunk_count")
        or focused.get("chunks_count")
        or uploaded.get("chunks_count")
        or uploaded.get("chunk_count")
    )
    return doc_id, durable, chunks


def build_all(
    client: SuperDocs,
    order: Order,
    *,
    workspace: Workspace,
    audiences: tuple[str, ...] = AUDIENCES,
    only: list[str] | None = None,
) -> dict[str, Pack]:
    packs = {
        audience: build_pack(client, order, audience=audience, workspace=workspace, only=only)
        for audience in audiences
    }
    workspace.save(packs, order)
    return packs


# Documents whose Mermaid diagram is lost on .docx export. See DIAGRAM_NOTE.
DIAGRAM_NOTE = (
    "this document contains a generated diagram, and .docx export drops it — the "
    "Mermaid source lands in the file as literal text, with no export warning. "
    "PDF renders it correctly. Export this one as PDF, or send the whole pack as PDF."
)


def export_pack(
    client: SuperDocs,
    pack: Pack,
    *,
    workspace: Workspace,
    fmt: str = "docx",
    live: bool = True,
) -> list[Path]:
    """Export every document in a pack. Exports never cost an operation.

    Exports the **live** body by default, not the local render. The local file
    is what was uploaded; after any approved change it is stale, and shipping a
    customer the pre-change pack because the exporter read the wrong bytes is
    the exact failure this whole build exists to prevent. Pass ``live=False``
    to export what was originally rendered — useful for a diff, not for sending.

    Exported per document by passing ``html`` rather than ``session_id``,
    because export takes no ``document_id`` and a session export returns only
    the focused document.
    """
    from packet.templates import BY_SLUG
    from packet.verify import live_text

    out_dir = workspace.dir_for(pack.audience) / fmt
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for doc in pack.documents:
        html = (
            live_text(client, pack, doc)
            if live
            else Path(doc.local_path).read_text(encoding="utf-8")
        )
        content, warnings = client.export(
            html=html,
            fmt=fmt,
            filename=f"{doc.slug}-{pack.audience}",
            options={"paper_size": "A4", "margins": "normal"},
        )

        # The service emits no warning when a diagram is dropped from a .docx,
        # so this build emits its own rather than hand over a pack with the
        # network design replaced by unreadable source.
        if fmt == "docx" and BY_SLUG[doc.slug].has_diagram:
            warnings = list(warnings) + [
                {"code": "diagram_lost_in_docx", "message": DIAGRAM_NOTE, "document": doc.slug}
            ]

        if warnings:
            pack.warnings.extend(warnings)
            for w in warnings:
                log.warning("export warning on %s: %s", doc.slug, w.get("message", w))
        if content:
            path = out_dir / f"{doc.slug}-{pack.audience}.{_ext(fmt)}"
            path.write_bytes(content)
            written.append(path)
    return written


def _ext(fmt: str) -> str:
    return {"markdown": "md", "txt": "txt", "html": "html", "pdf": "pdf", "docx": "docx"}[fmt]


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()
