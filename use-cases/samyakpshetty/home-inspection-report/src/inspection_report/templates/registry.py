"""Report formats live in SuperDocs, and the report is built from what SuperDocs returns.

There is no endpoint that applies a template to a document, and `GET /v1/templates` returns
metadata without content, so a template cannot simply be fetched. What *does* work — verified
against the live API — is that the AI finds a registered template by name when asked in chat
and loads it into the session. Asked to load a `.docx` format, it returns that document
**exactly as saved**: headings, bold and italic runs, the severity legend, the standing text,
the bracketed tokens, all intact. That was measured, not assumed.

So the chain is: **register the format → ask SuperDocs to load it → bind the inspection into
what comes back.** The skeleton every report is built on is the document SuperDocs hands us.
Delete the template from the account and the report cannot be produced, which is the only
honest test of whether a surface is really being used or merely being called once to say it
was.

Three things make that affordable and safe:

* **It costs one operation per format version, not per report.** The materialised skeleton is
  cached against the template's content hash, because a template changes when a firm changes
  its format — roughly never — while reports are produced daily.
* **Structure is still ours.** SuperDocs supplies the document; the binding engine fills it
  deterministically. The AI never decides which system a finding belongs under. It was asked
  to, in a measured experiment, and could not — see PROGRESS.md.
* **What comes back is checked before a report is built on it.** Not by looking for a magic
  string, but by reading it as a format: a heading per catalogue system with somewhere to put
  findings, and a worked example showing how a finding is recorded.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from inspection_report.logging import get_logger
from inspection_report.superdocs.base import SuperDocsClient, SuperDocsError
from inspection_report.superdocs.models import JobStatus
from inspection_report.templates import docx_html

_log = get_logger("inspection_report.templates.registry")

# The name is the contract with the AI: it is what the chat message asks for, so it has to be
# unique, stable, and obviously a report format. The content hash rides in it so a changed
# format is a different template rather than a silent redefinition of the old one.
NAME_PREFIX = "Home inspection format"


class TemplateUnavailable(SuperDocsError):
    """The format could not be obtained from SuperDocs."""


@dataclass(frozen=True)
class RegisteredFormat:
    key: str
    name: str
    template_id: str
    content_sha: str
    local_html: str


def content_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def template_name(key: str, sha: str) -> str:
    return f"{NAME_PREFIX} — {key} [{sha[:8]}]"


def ensure_registered(client: SuperDocsClient, template_dir: Path) -> dict[str, RegisteredFormat]:
    """Register every shipped format with SuperDocs, exactly once each.

    Idempotent by name, and the name carries the content hash, so re-running registers
    nothing and an edited format registers as a new version rather than overwriting one that
    existing reports were produced from.
    """
    try:
        existing = {t.name: t for t in client.list_templates()}
    except SuperDocsError as exc:
        raise TemplateUnavailable(f"could not list templates: {exc}") from exc

    out: dict[str, RegisteredFormat] = {}
    for path in sorted(template_dir.glob("*.docx")):
        raw = path.read_bytes()
        sha = content_sha(raw)
        name = template_name(path.stem, sha)
        ref = existing.get(name)
        if ref is None:
            ref = client.upload_template(data=raw, filename=f"{name}.docx")
            _log.info("template_registered", extra={"format": path.stem, "sha": sha[:8]})
        out[path.stem] = RegisteredFormat(
            key=path.stem,
            name=name,
            template_id=ref.id,
            content_sha=sha,
            # The same document, converted locally. Only ever used when SuperDocs cannot be
            # reached — and the caller is told which path produced the report.
            local_html=docx_html.from_bytes(raw),
        )
    return out


def materialise(
    client: SuperDocsClient,
    fmt: RegisteredFormat,
    *,
    session_id: str,
    cache: dict[str, str] | None = None,
) -> tuple[str, bool]:
    """Get the report skeleton **from SuperDocs**, by asking it to load the registered format.

    Returns the skeleton and whether it came from SuperDocs on this call (False means the
    cache answered, or the fallback did).

    The fallback matters and is not a cheat: if SuperDocs is unreachable, an inspector who has
    walked a property still gets their report out of the local copy of the same bytes that
    were registered. What is not acceptable is pretending the round trip happened, so the
    caller is told which path produced the document and the README says so.
    """
    if cache is not None and fmt.content_sha in cache:
        return cache[fmt.content_sha], False

    try:
        job_id = client.chat_async(
            session_id=session_id,
            # Named exactly as registered. This is the documented way a template is used:
            # "Draft a document using my <name> template".
            message=(
                f"Load my '{fmt.name}' template into this session as the active document. "
                f"Reproduce it exactly as saved. Do not fill in, summarise, remove or "
                f"rewrite any part of it, and do not add commentary."
            ),
            approval_mode="approve_all",
        )
        job = _await(client, job_id)
        html = job.document_html or ""
        if not _looks_like_the_format(html, fmt):
            raise TemplateUnavailable(
                f"SuperDocs returned a document that is not the {fmt.key!r} format. "
                f"The report was not built from an unrecognised skeleton."
            )
    except SuperDocsError as exc:
        _log.warning(
            "template_materialise_failed",
            extra={"format": fmt.key, "error": type(exc).__name__},
        )
        return fmt.local_html, False

    if cache is not None:
        cache[fmt.content_sha] = html
    return html, True


def _await(client: SuperDocsClient, job_id: str, *, attempts: int = 90, wait_s: float = 2.0):  # type: ignore[no-untyped-def]
    import time

    for _ in range(attempts):
        job = client.get_job(job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.AWAITING_APPROVAL):
            return job
        if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise TemplateUnavailable(f"loading the format failed: {job.error or job.status}")
        time.sleep(wait_s)
    raise TemplateUnavailable("loading the format timed out")


def _looks_like_the_format(html: str, fmt: RegisteredFormat) -> bool:
    """Confirm what came back really is the format, before a report is built on it.

    Checked by reading it as a format rather than by hunting for a marker string: a heading
    for every catalogue system with somewhere under it to put findings, and one worked
    example showing how a finding is recorded. A document without those cannot produce a
    grouped report, and accepting one would mean silently building on a different structure
    than the firm chose.
    """
    from inspection_report.domain import catalogue
    from inspection_report.templates import binding

    if not html.strip():
        return False
    try:
        binding.read_format(html, [s.name for s in catalogue.systems()])
    except binding.TemplateError as exc:
        _log.warning("template_not_recognised", extra={"format": fmt.key, "reason": str(exc)[:200]})
        return False
    return True
