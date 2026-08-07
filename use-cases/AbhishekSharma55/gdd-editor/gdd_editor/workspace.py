"""A multi-document GDD workspace on top of SuperDocs.

THE ARCHITECTURAL DECISION, AND WHY IT IS NOT THE OBVIOUS ONE
-------------------------------------------------------------
SuperDocs has a multi-document session: `/v1/sessions/init` takes a list of
document ids, `/v1/sessions/{id}/documents` returns the roster, and `/v1/chat`
takes a `document_id` to target one of them. That is the surface this build
should have used.

I could not make it hold. Opening three documents into one session returns a
roster containing **one** document, every entry carries the same
`document_id: "doc_primary"`, and four identical GETs against the same session
returned a *different* document each time (bugs.md B10, with a raw-curl repro).
With every document sharing one id there is no way to address a specific one,
so "change the Grapple cooldown in Mechanics and nothing else" has nowhere to
land.

So this workspace gives **each document its own session** and keeps the link
graph itself. That is a smaller claim on the product and a larger one on my
code: cross-document consistency becomes my job, which means it has to be
verified rather than assumed - which is what `scenario.py` does.

What that buys, beyond working:

* every edit is addressed to exactly one document by construction, so a
  cross-document instruction cannot smear across files by accident;
* each document's before/after bytes are held locally, so "only the intended
  section changed" is checked per document, independently;
* the link graph is data (`corpus.LINKS`), so adding an "audio bible"
  sub-document is a dict entry, not a code change.

What it costs, stated plainly: the model never sees two documents at once, so
it cannot reason across them in a single turn. A cross-document request is
decomposed by this class into one targeted edit per document. If the roster bug
were fixed I would use the real multi-document session and let the model see
the whole workspace.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from superdocs_kit import OpsBudget, SuperDocs, sha
from superdocs_kit.docdiff import (
    SurgeryVerdict,
    diff_chunks,
    section_named,
    sections,
    verify_surgical,
)

from .corpus import DOCUMENTS, LINKS


@dataclass
class DocState:
    key: str
    title: str
    session_id: str
    html: str = ""
    version: int = 0
    doc_sha: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("html")           # the bytes live in their own file
        return d


@dataclass
class EditResult:
    """One targeted edit against one document."""

    doc_key: str
    instruction: str
    ops: int
    seconds: float
    changed_sections: list[str]
    unchanged_sections: int
    verdict: SurgeryVerdict | None = None
    response_text: str = ""
    api_summary: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict is None or self.verdict.ok


class Workspace:
    """The GDD and its linked sub-documents, edited by chat."""

    def __init__(
        self,
        *,
        out_dir: Path,
        budget: OpsBudget,
        client: SuperDocs,
        workspace_id: str | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.out = Path(out_dir)
        self.budget = budget
        self.client = client
        self.log = log
        (self.out / "docs").mkdir(parents=True, exist_ok=True)
        (self.out / "snapshots").mkdir(parents=True, exist_ok=True)
        (self.out / "export").mkdir(parents=True, exist_ok=True)
        self.state_path = self.out / "workspace.json"
        prior = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.workspace_id = (
            prior.get("workspace_id") or workspace_id or f"nebula-gdd-{uuid.uuid4().hex[:10]}"
        )
        self.docs: dict[str, DocState] = {}
        for key, meta in prior.get("docs", {}).items():
            state = DocState(**meta)
            state.html = self._read(key)
            self.docs[key] = state
        self.history: list[dict] = prior.get("history", [])

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def _doc_path(self, key: str) -> Path:
        return self.out / "docs" / f"{key}.html"

    def _read(self, key: str) -> str:
        p = self._doc_path(key)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _write(self, key: str, html: str) -> None:
        self._doc_path(key).write_text(html, encoding="utf-8")

    def save(self) -> None:
        payload = {
            "workspace_id": self.workspace_id,
            "docs": {k: v.as_dict() for k, v in self.docs.items()},
            "links": LINKS,
            "history": self.history,
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)          # atomic; a kill cannot half-write it

    def snapshot(self, tag: str) -> dict[str, str]:
        """Freeze every document's bytes under a tag. Free, and it is what
        every 'nothing else changed' claim in this build is checked against."""
        d = self.out / "snapshots" / tag
        d.mkdir(parents=True, exist_ok=True)
        out = {}
        for key, state in self.docs.items():
            (d / f"{key}.html").write_text(state.html, encoding="utf-8")
            out[key] = state.html
        return out

    def load_snapshot(self, tag: str) -> dict[str, str]:
        d = self.out / "snapshots" / tag
        return {
            p.stem: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.html"))
        } if d.exists() else {}

    # ------------------------------------------------------------------
    # seeding
    # ------------------------------------------------------------------
    def seed(self, keys: list[str] | None = None) -> None:
        """Upload each document verbatim into its own session. Free."""
        for key in (keys or list(DOCUMENTS)):
            if key in self.docs and self.docs[key].html:
                self.log(f"  {key:10} already seeded ({len(self.docs[key].html)}B)")
                continue
            title, html = DOCUMENTS[key]
            session_id = f"{self.workspace_id}-{key}"
            up = self.client.upload_document(
                filename=f"{key}.html", content=html,
                session_id=session_id, return_html=True,
            )
            stored = up.get("html") or html
            self.docs[key] = DocState(key, title, session_id, stored, 1, sha(stored))
            self._write(key, stored)
            self.log(f"  {key:10} seeded  {len(stored):>6}B  "
                     f"{len(sections(stored))} sections")
        self.save()

    def add_document(self, key: str, title: str, html: str) -> DocState:
        """Create a new linked sub-document at runtime. Free."""
        session_id = f"{self.workspace_id}-{key}"
        up = self.client.upload_document(
            filename=f"{key}.html", content=html, session_id=session_id, return_html=True,
        )
        stored = up.get("html") or html
        self.docs[key] = DocState(key, title, session_id, stored, 1, sha(stored))
        self._write(key, stored)
        self.save()
        self.log(f"  {key:10} created {len(stored):>6}B")
        return self.docs[key]

    # ------------------------------------------------------------------
    # editing
    # ------------------------------------------------------------------
    def edit(
        self,
        doc_key: str,
        instruction: str,
        *,
        label: str,
        expect_sections: list[str] | None = None,
        expect_new_section: bool = False,
        image_urls: list[str] | None = None,
    ) -> EditResult:
        """One targeted edit against one document, verified from the bytes.

        `expect_sections` names the sections the caller intends to change. If it
        is given, the result carries a verdict that is FALSE when anything else
        moved - including in ways the API's own summary did not mention.
        """
        state = self.docs[doc_key]
        before = state.html
        message = instruction
        if image_urls:
            urls = "\n".join(f"  {u}" for u in image_urls)
            message += (
                f"\n\nUse these already-uploaded image URLs verbatim in <img src=\"...\"> "
                f"tags. Do not invent URLs and do not describe the images instead of "
                f"embedding them:\n{urls}"
            )

        started = time.monotonic()
        res = self.client.chat(
            session_id=state.session_id,
            message=message,
            label=label,
            document_html=before,       # the client owns the document (see bugs.md B8)
            response_mode="full",
            model_tier="pro",
            thinking_depth="deep",
            timeout=900,
        )
        after = res.updated_html or before
        state.html = after
        state.version += 1
        state.doc_sha = sha(after)
        self._write(doc_key, after)

        diff = diff_chunks(before, after)
        verdict = None
        if expect_sections is not None:
            verdict = verify_surgical(
                before, after, expected_sections=expect_sections, allow_new=expect_new_section,
            )
        result = EditResult(
            doc_key=doc_key, instruction=instruction, ops=res.ops_charged,
            seconds=round(time.monotonic() - started, 1),
            changed_sections=sorted(set(diff.modified) | set(diff.added)),
            unchanged_sections=len(diff.unchanged), verdict=verdict,
            response_text=res.response_text, api_summary=res.changes_summary or "",
        )
        self.history.append({
            "doc": doc_key, "label": label, "ops": res.ops_charged,
            "seconds": result.seconds, "changed": len(result.changed_sections),
            "unchanged": result.unchanged_sections,
            "ok": result.ok, "api_summary": result.api_summary,
        })
        self.save()
        self.log(
            f"  edit {doc_key:10} {res.ops_charged} op {result.seconds:5.1f}s  "
            f"changed={len(result.changed_sections):>2} untouched={result.unchanged_sections:>3}"
            + (f"  [{'PASS' if verdict.ok else 'FAIL'}]" if verdict else "")
        )
        return result

    # ------------------------------------------------------------------
    # images
    # ------------------------------------------------------------------
    def upload_image(self, path: Path) -> str:
        url = self.client.upload_image(Path(path))
        self.log(f"  image  {Path(path).name} -> {url[:70]}")
        return url

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    def export_all(self, fmt: str = "docx") -> list[Path]:
        """Exports are free, so the demo exports the whole workspace at the end."""
        written = []
        for key, state in self.docs.items():
            try:
                data = self.client.export(
                    session_id=state.session_id, fmt=fmt, filename=state.title,
                )
                ext = {"markdown": "md", "docx": "docx", "pdf": "pdf",
                       "html": "html", "txt": "txt"}.get(fmt, fmt)
                p = self.out / "export" / f"{key}.{ext}"
                p.write_bytes(data)
                written.append(p)
            except Exception as exc:  # noqa: BLE001 - a lost export is not a lost document
                self.log(f"  export {key}: unavailable ({type(exc).__name__})")
        return written

    # ------------------------------------------------------------------
    # cross-document checks
    # ------------------------------------------------------------------
    def untouched_report(self, snapshot_tag: str, allowed: dict[str, list[str]]) -> dict:
        """Prove that across EVERY document, only the allowed sections moved.

        `allowed` maps doc key -> section names that were meant to change.
        A document absent from `allowed` must be byte-identical, whole.
        """
        before = self.load_snapshot(snapshot_tag)
        report: dict = {"documents": {}, "ok": True}
        for key, state in self.docs.items():
            prev = before.get(key, "")
            if key not in allowed:
                identical = prev == state.html
                report["documents"][key] = {
                    "expected": "byte-identical",
                    "byte_identical": identical,
                    "ok": identical,
                }
                report["ok"] &= identical
                continue
            verdict = verify_surgical(prev, state.html, expected_sections=allowed[key])
            unexpected_docs = sorted(verdict.unintended)
            report["documents"][key] = {
                "expected": allowed[key],
                "sections_changed": sorted(
                    set(verdict.detail["modified"]) | set(verdict.detail["added"])
                ),
                "unintended": unexpected_docs,
                "byte_identical_sections": verdict.unchanged_count,
                "ok": not unexpected_docs,
            }
            report["ok"] &= not unexpected_docs
        return report

    def section_names(self, doc_key: str) -> list[str]:
        return [s.heading for s in sections(self.docs[doc_key].html) if s.level >= 2]

    def has_section(self, doc_key: str, name: str) -> bool:
        return section_named(self.docs[doc_key].html, name) is not None
