"""An offline stand-in for SuperDocs.

Everything except the four API calls runs against this: parsing, facts, the curve, the
gate, the traceability pass and the carry-forward. That is what lets a stranger clone
the repository and run the whole pipeline, tests included, with no key and no network —
and it is what kept the operation budget for work rather than for debugging.

The mock is deliberately *not* a rubber stamp. It drafts prose the way a well-behaved
model would — stitching the supplied statements together and preserving their citations
— and it can be told to misbehave in the specific ways that matter:

    MockSuperDocs(misbehave="phantom")   invents a citation to an entry that does not exist
    MockSuperDocs(misbehave="foreign")   cites a real entry this section was never given
    MockSuperDocs(misbehave="unsourced") drops citations entirely

Those modes exist so the traceability pass can be proven to catch each failure, rather
than being tested only against a mock that always behaves. A test that only proves the
mock works is worth nothing.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Callable

from .client import Approver, ProposedChange, Usage, approve_all

BULLET = re.compile(r"^-\s+(.*)$")
SECTION_NAME = re.compile(r"section\s+[“\"]([^”\"]+)[”\"]")
IMG_TAG = re.compile(r"<img[^>]+>")
# Typographic quotes only. A straight quote also closes an HTML attribute, so accepting
# both let this match the `"` ending alt="..." and swallow the instruction prose after
# it straight into the document.
CAPTION = re.compile(r"“([^”]*\[EL-\d{4}\][^”]*)”")


class MockSuperDocs:
    """Same surface as SuperDocsClient, no network."""

    def __init__(
        self,
        misbehave: str | None = None,
        reject_first: bool = False,
        sleep: Callable[[float], None] = lambda _: None,
    ) -> None:
        self.documents: dict[str, str] = {}
        self.images: list[str] = []
        self.instructions: list[str] = []
        self.misbehave = misbehave
        self.reject_first = reject_first
        self.rejections: list[str] = []
        self.usage = Usage(operations_before=0, operations_after=0)
        self._sleep = sleep
        self._rejected_once = False

    # ------------------------------------------------------------------ contract

    def close(self) -> None:  # parity with the real client
        pass

    def __enter__(self) -> MockSuperDocs:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def whoami(self) -> dict[str, Any]:
        return {"tier": "mock", "quota": {"used": self.usage.operations_after, "monthly_limit": 0}}

    def operations_used(self) -> int:
        return self.usage.operations_after or 0

    def upload_document(self, session_id: str, filename: str, content: str) -> dict[str, Any]:
        self.documents[session_id] = content
        self.usage.calls += 1
        return {"filename": filename, "chunks_count": content.count("<"), "session_id": session_id}

    def upload_image(self, session_id: str, filename: str, image: Path | bytes) -> str:
        """Return a data URI carrying the real image bytes.

        The live endpoint returns a hosted URL. A mock that invented a fake one would
        put an `<img>` in the document pointing at nothing, so the offline export would
        show an empty box — and "the diagram is inside the document" is precisely what
        this build has to demonstrate. Embedding the actual bytes makes the offline
        document show the real curve.
        """
        self.usage.calls += 1
        raw = image.read_bytes() if isinstance(image, Path) else image
        url = f"data:image/png;base64,{base64.b64encode(raw).decode('ascii')}"
        self.images.append(url)
        return url

    def chat(
        self,
        session_id: str,
        message: str,
        approver: Approver = approve_all,
        model_tier: str = "core",
        on_event: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        note = on_event or (lambda stage, detail: None)
        self.instructions.append(message)
        self.usage.calls += 1
        self.usage.operations_after = (self.usage.operations_after or 0) + 1

        changes = self._propose(message)
        approved: list[ProposedChange] = []
        for change in changes:
            ok, why = approver(change)
            if not ok and why:
                self.rejections.append(why)
            if ok:
                approved.append(change)
        note("gate", f"{len(approved)} approved, {len(changes) - len(approved)} rejected")

        html = self.documents.get(session_id, "")
        for change in approved:
            if change.old_html and change.old_html in html:
                html = html.replace(change.old_html, change.new_html or "", 1)
        self.documents[session_id] = html

        return {
            "response": f"Updated {len(approved)} of {len(changes)} proposed changes.",
            "document_changes": {"updated_html": html},
        }

    def export(self, session_id: str, out_path: Path, fmt: str = "docx") -> Path:
        """Write the document out.

        The live service renders real Open XML. This mock cannot, and writing HTML into
        a file named `.docx` would be a small lie that Word would expose the moment
        anyone opened it — so the offline export is named `.html` and is genuinely
        viewable, curve included.
        """
        html = self.documents.get(session_id, "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if fmt in ("markdown", "md", "txt"):
            out_path.write_text(html_to_markdown(html), encoding="utf-8")
            return out_path
        page = out_path.with_suffix(".html")
        page.write_text(_standalone(html), encoding="utf-8")
        return page

    # -------------------------------------------------------------------- drafting

    def _propose(self, message: str) -> list[ProposedChange]:
        """Turn one instruction into the changes a cooperative model would propose."""
        image = IMG_TAG.search(message)
        if image:
            # look for the caption only after the tag, never inside its attributes
            caption = CAPTION.search(message, image.end())
            body = image.group(0) + (f"<p><em>{caption.group(1)}</em></p>" if caption else "")
            return [
                ProposedChange(
                    change_id="mock-curve",
                    operation="edit",
                    chunk_id="curve",
                    old_html="<p>Placeholder for the restoration curve.</p>",
                    new_html=body,
                    explanation="Inserted the restoration curve and its caption.",
                )
            ]

        buckets = _buckets(message)
        placeholders = {
            "observed": "<p>Placeholder for observed statements.</p>",
            "assessed": "<p>Placeholder for assessed statements.</p>",
            "gaps": "<p>Placeholder for gaps.</p>",
            "raised": "<p>Placeholder for items raised by this event.</p>",
        }

        changes: list[ProposedChange] = []
        for n, (bucket, statements) in enumerate(buckets.items(), start=1):
            if not statements:
                continue
            prose = " ".join(self._sentence(s, bucket) for s in statements)
            changes.append(
                ProposedChange(
                    change_id=f"mock-{bucket}-{n}",
                    operation="edit",
                    chunk_id=f"{bucket}-{n}",
                    old_html=placeholders[bucket],
                    new_html=f"<p>{prose}</p>",
                    explanation=f"Drafted {len(statements)} {bucket} statement(s).",
                )
            )
        return changes

    def _sentence(self, statement: str, bucket: str) -> str:
        """One drafted sentence, with the citation kept where the instruction put it."""
        text = statement.strip()
        if bucket == "observed" and self.misbehave:
            if self.misbehave == "phantom":
                text = re.sub(r"\[EL-\d{4}[^\]]*\]", "[EL-9999]", text, count=1)
            elif self.misbehave == "foreign":
                text = re.sub(r"\[EL-\d{4}[^\]]*\]", "[EL-0019]", text, count=1)
            elif self.misbehave == "unsourced":
                text = re.sub(r"\s*\[EL-\d{4}[^\]]*\]", "", text)
        if not text.endswith((".", "!", "?")):
            text += "."
        return text[0].upper() + text[1:]


def _buckets(message: str) -> dict[str, list[str]]:
    """Split an instruction's bullets by the heading they were listed under."""
    buckets: dict[str, list[str]] = {"observed": [], "assessed": [], "gaps": [], "raised": []}
    current = "observed"
    for line in message.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("OBSERVED STATEMENTS"):
            current = "observed"
        elif upper.startswith("ASSESSED STATEMENTS"):
            current = "assessed"
        elif upper.startswith("WHAT THE RECORDS DO NOT SHOW"):
            current = "gaps"
        elif stripped.startswith("Items raised by"):
            current = "raised"
        elif match := BULLET.match(stripped):
            value = match.group(1).strip()
            if value and value != "(none)":
                buckets[current].append(value)
    return buckets


def _standalone(body: str) -> str:
    """Wrap the document body so it reads like a filed report in a browser."""
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Storm Restoration After-Action Report</title><style>"
        "body{font:16px/1.6 Georgia,serif;max-width:52rem;margin:3rem auto;padding:0 1.5rem;color:#14181e}"
        "h1{font-size:1.9rem;margin-bottom:.2rem}h2{font-size:1.3rem;margin-top:2.2rem;"
        "border-bottom:1px solid #d5dce4;padding-bottom:.3rem}"
        "h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:#5b6672;margin-top:1.5rem}"
        "img{max-width:100%;height:auto;border:1px solid #d5dce4;border-radius:3px}"
        "table{border-collapse:collapse;width:100%;font-size:.9rem;margin-top:.5rem}"
        "th,td{border:1px solid #d5dce4;padding:.5rem .7rem;text-align:left;vertical-align:top}"
        "th{background:#eef1f5;font-size:.75rem;text-transform:uppercase;letter-spacing:.06em}"
        "em{color:#5b6672}</style>\n" + body
    )


def html_to_markdown(html: str) -> str:
    """Flatten the mock's HTML to the shape the real export produces.

    Only the constructs the skeleton actually uses, so the traceability pass reads the
    same document text on both paths.
    """
    text = html
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.S)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.S)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.S)
    text = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*>", r"\n![\1]\n", text)
    text = re.sub(r"</(p|tr|table|tbody|thead)>", "\n", text)
    text = re.sub(r"</t[dh]>", " | ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.rstrip(" |").strip() for line in text.splitlines()).strip() + "\n"
