from __future__ import annotations

import html
import re
import uuid
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol, cast

from .models import DealTerms, GeneratedAgreement


class LiveClient(Protocol):
    def upload_document(self, path: str | Path, **kwargs: Any) -> Any: ...

    def chat_async(self, **kwargs: Any) -> Any: ...

    def wait(self, job_id: str, **kwargs: Any) -> Any: ...

    def approve_change(self, **kwargs: Any) -> Any: ...

    def get_session_history(self, session_id: str, **kwargs: Any) -> Any: ...

    def export_document(self, **kwargs: Any) -> Any: ...


def load_terms(path: str | Path) -> DealTerms:
    return DealTerms.model_validate_json(Path(path).read_text(encoding="utf-8"))


def draft_offline(terms: DealTerms, template: str) -> GeneratedAgreement:
    replacements = {
        "{{PROJECT_NAME}}": terms.project_name,
        "{{PRODUCER}}": terms.producer,
        "{{TALENT}}": terms.talent,
        "{{TERM}}": terms.term,
        "{{TERRITORY}}": terms.territory,
        "{{MEDIA}}": ", ".join(terms.media),
        "{{COMPENSATION}}": terms.compensation,
        "{{DELIVERABLES}}": "; ".join(terms.deliverables),
        "{{EXCLUSIVITY}}": terms.exclusivity,
        "{{APPROVAL_RIGHTS}}": terms.approval_rights,
        "{{CREDIT}}": terms.credit,
        "{{TERMINATION}}": terms.termination,
    }
    markdown = template
    for token, value in replacements.items():
        markdown = markdown.replace(token, value)
    return GeneratedAgreement(markdown=markdown, clause_checks=check_clauses(markdown, terms))


def drafting_prompt(terms: DealTerms) -> str:
    return (
        "Replace every {{PLACEHOLDER}} in the uploaded rights and talent agreement. Preserve all "
        "headings and clause order, add no invented terms, and reflect these deal terms verbatim: "
        f"project={terms.project_name}; producer={terms.producer}; talent={terms.talent}; "
        f"term={terms.term}; territory={terms.territory}; media={', '.join(terms.media)}; "
        f"compensation={terms.compensation}; deliverables={'; '.join(terms.deliverables)}; "
        f"exclusivity={terms.exclusivity}; approvals={terms.approval_rights}; "
        f"credit={terms.credit}; termination={terms.termination}."
    )


def draft_with_superdocs(
    terms: DealTerms,
    template_path: str | Path,
    *,
    approve: Callable[[dict[str, Any]], bool],
    client: LiveClient | None = None,
) -> GeneratedAgreement:
    owned_client: Any | None = None
    active_client: LiveClient
    if client is None:
        try:
            from superdocs_sdk import SuperDocsClient
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("Install the SuperDocs SDK or run without --live-superdocs.") from exc
        owned_client = SuperDocsClient.from_env()
        active_client = cast(LiveClient, owned_client)
    else:
        active_client = client

    session_id = (
        "rights-generator-"
        + re.sub(r"[^a-z0-9]+", "-", terms.project_name.lower()).strip("-")
        + f"-{uuid.uuid4().hex[:8]}"
    )
    reviewed = 0
    try:
        active_client.upload_document(template_path, session_id=session_id, return_html=True)
        job = active_client.chat_async(
            session_id=session_id,
            message=drafting_prompt(terms),
            approval_mode="ask_every_time",
            response_mode="compact",
        )
        while True:
            job = active_client.wait(job.job_id, timeout_s=300)
            if job.status == "failed":
                raise RuntimeError(f"SuperDocs drafting failed: {job.error}")
            if job.status == "completed":
                break
            if job.status != "awaiting_approval":
                raise RuntimeError(f"Unexpected SuperDocs job status: {job.status}")
            if job.metadata.get("awaiting_kind") == "continue_prompt":
                raise RuntimeError(
                    "The edit requested continuation; split the template or resume with the continue API."
                )
            pending = job.metadata.get("pending_changes") or []
            if not pending:
                raise RuntimeError("SuperDocs paused for approval without metadata.pending_changes.")
            from superdocs_sdk import ApprovalDecision

            decisions = [
                ApprovalDecision(change_id=str(change["change_id"]), approved=approve(change))
                for change in pending
            ]
            reviewed += len(decisions)
            active_client.approve_change(
                session_id=session_id,
                job_id=job.job_id,
                approved=all(decision.approved for decision in decisions),
                changes=decisions,
            )

        updated_html = None
        if job.result and job.result.document_changes:
            updated_html = job.result.document_changes.updated_html
        if not updated_html:
            updated_html = active_client.get_session_history(
                session_id, include_document_html=True
            ).document_html
        if not updated_html:
            raise RuntimeError("SuperDocs completed without returning the final document HTML.")
        exported = active_client.export_document(
            session_id=session_id,
            format="docx",
            filename=f"{terms.project_name}-rights-talent-agreement.docx",
        )
    finally:
        if owned_client is not None:
            owned_client.close()

    markdown = html_to_markdown(updated_html)
    return GeneratedAgreement(
        markdown=markdown,
        clause_checks=check_clauses(markdown, terms),
        exported_docx=exported.content,
        session_id=session_id,
        reviewed_changes=reviewed,
    )


def check_clauses(markdown: str, terms: DealTerms) -> dict[str, bool]:
    lowered = " ".join(markdown.lower().split())
    return {
        "term": terms.term.lower() in lowered,
        "scope_of_rights": all(media.lower() in lowered for media in terms.media),
        "territory": terms.territory.lower() in lowered,
        "compensation": terms.compensation.lower() in lowered,
        "deliverables": all(item.lower() in lowered for item in terms.deliverables),
        "approval": terms.approval_rights.lower() in lowered,
        "credit": terms.credit.lower() in lowered,
        "termination": terms.termination.lower() in lowered,
    }


def markdown_to_html(markdown: str) -> str:
    blocks: list[str] = []
    for index, line in enumerate(markdown.splitlines()):
        if not line.strip():
            continue
        escaped = html.escape(line.removeprefix("# ").removeprefix("## "))
        if line.startswith("# "):
            blocks.append(f'<h1 data-chunk-id="tpl-{index}">{escaped}</h1>')
        elif line.startswith("## "):
            blocks.append(f'<h2 data-chunk-id="tpl-{index}">{escaped}</h2>')
        else:
            blocks.append(f'<p data-chunk-id="tpl-{index}">{escaped}</p>')
    return "\n".join(blocks)


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.current: list[str] = []
        self.prefix = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "p", "li"}:
            self._flush()
            self.prefix = {"h1": "# ", "h2": "## ", "h3": "### ", "li": "- "}.get(tag, "")
        elif tag == "br":
            self.current.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "p", "li"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        self.current.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join("".join(self.current).split())
        if text:
            self.lines.append(self.prefix + text)
        self.current = []
        self.prefix = ""


def html_to_markdown(document_html: str) -> str:
    parser = _MarkdownParser()
    parser.feed(document_html)
    parser.close()
    return "\n\n".join(parser.lines) + "\n"
