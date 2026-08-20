"""The single-document flow: upload, ask, guard, approve, export.

The linter itself knows no style rules. Every rule it enforces arrives as an
attachment, which is what the card means by "rules live entirely in the attached
style guide". The only thing this module hardcodes is the *shape* of a finding —
a rule id, the exact original text, and a suggested rewrite — because that shape is
what the guard needs in order to decide anything.

Order matters and is the whole design: the model proposes, the guard disposes, and
only what survives the guard is ever approved. Nothing reaches the document that a
deterministic check has not cleared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .client import SuperDocsClient, SuperDocsError
from .guard import Verdict, normalize, screen
from .parsing import ProposedChange, parse_proposed_changes
from .rules import UNATTRIBUTED, attribute, triggers

# The instruction names no rules. It points at the attachment and demands a shape.
INSTRUCTION = """You are linting this document against the attached style guide.

Read the attached style guide. It is the ONLY source of rules — apply nothing from
your own training about good writing, and do not invent rules the guide does not
state.

For every violation you find in the document body, propose one change. Each proposed
change must carry:
  - rule_id: the exact rule identifier from the attached guide
  - original: the exact text to replace, copied character for character from the
    document, long enough to be unique on the page
  - replacement: the corrected text, changing nothing except what the rule requires
  - note: one short sentence naming what the rule requires

Do not propose changes to code samples, table cells, or headings that already comply.
Do not change meaning, terminology, product names, numbers, or quoted material.
If the document already complies with the guide, propose no changes and say so
plainly rather than inventing work."""


@dataclass
class Finding:
    """One proposed change plus the guard's decision about it."""

    change: ProposedChange
    verdict: Verdict

    @property
    def rule_id(self) -> str:
        return self.change.rule_id or "unattributed"

    @property
    def applied(self) -> bool:
        return self.verdict.kept


@dataclass
class LintResult:
    document: str
    guide: str
    session_id: str
    findings: list[Finding] = field(default_factory=list)
    export: dict[str, Any] | None = None
    operations: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def applied(self) -> list[Finding]:
        return [f for f in self.findings if f.applied]

    @property
    def dropped(self) -> list[Finding]:
        return [f for f in self.findings if not f.applied]

    @property
    def clean(self) -> bool:
        """No changes were proposed.

        Deliberately NOT named `compliant`. It means the model returned nothing,
        which is not the same as the document satisfying the guide - the run is not
        repeatable enough to claim that. Distinct from "we could not read the
        response", which raises instead.
        """
        return not self.findings


_HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.I | re.S)
_HEADING_RULES = re.compile(r"heading_rules:\s*(.+)", re.I)


def heading_rules(guide_text: str) -> frozenset[str]:
    """The rule ids the guide permits to rewrite a heading.

    Declared in the guide, not here, so a guide with different heading policy needs
    no code change — which is the card's central requirement.
    """
    found = _HEADING_RULES.search(guide_text)
    if not found:
        return frozenset()
    raw = found.group(1).strip().strip("`").strip()
    return frozenset(r.strip().strip("`") for r in raw.split(",") if r.strip(" `"))


def all_headings(html: str) -> frozenset[str]:
    """Every heading in the document, normalized.

    Headings are protected by default. The card asks that fixes not touch "headings
    that are already compliant", and compliance cannot be decided without knowing the
    rules — which live in the attachment. Refusing every heading except where the
    guide explicitly licenses a heading rule is the conservative reading, and it
    fails in the safe direction.
    """
    return frozenset(normalize(m.group(1)) for m in _HEADING.finditer(html))


def lint_document(
    client: SuperDocsClient,
    document: str | Path,
    guide: str | Path,
    session_id: str,
    apply: bool = True,
    export_format: str | None = "docx",
    export_to: str | Path | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> LintResult:
    """Lint one document against one guide. Four calls, in the documented order."""
    say = on_event or (lambda stage, msg: None)
    doc_path, guide_path = Path(document), Path(guide)
    result = LintResult(doc_path.name, guide_path.name, session_id)

    client.init_session(session_id)
    uploaded = client.upload_document(doc_path, session_id)
    html = uploaded.get("html") or uploaded.get("document_html") or ""
    if not html:
        result.notes.append(
            "upload returned no HTML; the guard cannot verify protected regions, "
            "so every proposed change will be refused"
        )
    say("upload", f"{doc_path.name}: {len(html)} chars of HTML")

    client.upload_attachment(guide_path, session_id)
    client.attachment_ready(session_id)
    say("attach", f"{guide_path.name} is the ruleset, and it is loaded")

    # chat_async, not chat: the async job parks at awaiting_approval holding the
    # proposed changes, which is the only surface with a gate before anything applies.
    response = client.chat_async(session_id, INSTRUCTION)
    changes = parse_proposed_changes(response)
    say("propose", f"{len(changes)} proposed change(s)")

    guide_text = guide_path.read_text(encoding="utf-8")
    permitted = heading_rules(guide_text)
    declared = triggers(guide_text)
    case_rule = next(iter(permitted), None)
    headings = all_headings(html)
    if not declared:
        result.notes.append(
            "this guide declares no `## Rule triggers`, so findings cannot be "
            "attributed and the batch profile will group everything as unattributed")
    job_id = _job_id(response)
    chunks = _chunk_html(uploaded, html)

    for change in changes:
        # The API carries no rule id, so attribute the edit ourselves from the
        # triggers the guide declares. See rules.py for why.
        if not change.rule_id:
            change = replace(change, rule_id=attribute(
                change.original, change.replacement, declared, case_rule))
        # Scope the search to the chunk the change claims, when the upload gave us
        # one. Without it, any phrase appearing twice on a page is refused as
        # ambiguous - which would drop most word-level fixes on a real document.
        scope = chunks.get(change.chunk_id) if change.chunk_id else None
        # Headings stay protected unless the guide licenses this rule to touch one.
        protected = frozenset() if change.rule_id in permitted else headings
        if not str(change.original).strip():
            verdict = Verdict(False, "change carries no original text to match on; "
                                     "applying it blind is what the guard prevents")
        else:
            verdict = screen(html, change.original, protected, scope)
        if verdict.kept and change.is_noop:
            verdict = Verdict(False, "no-op: replacement identical to original")
        result.findings.append(Finding(change, verdict))
        if not apply or not job_id:
            continue
        # Deliberately no feedback on a denial. Observed 2026-08-19 (bug log): a
        # denial carrying feedback sends the job back round the revision loop and
        # the same change is re-proposed under a new id, so an unattended linter
        # cycles and pays for each round. The reason is kept locally instead, where
        # it belongs - it is the guard's verdict, not a request for a better idea.
        client.approve(session_id, job_id, verdict.kept, change.change_id)
        say("guard", f"{'apply ' if verdict.kept else 'refuse'} {change.change_id}: {verdict.reason}")

    if apply and job_id and result.findings:
        # Approval resumes the job; the document is not final until it completes.
        # Exporting straight after approving ships the unfixed document.
        try:
            client.wait_for_job(session_id, job_id, require_completed=True,
                                deadline_seconds=180.0)
            say("apply", f"{len(result.applied)} fix(es) applied and settled")
        except SuperDocsError as exc:
            # The job can re-enter awaiting_approval with a fresh batch rather than
            # completing. Say so and export what exists; do not block for half an
            # hour, and do not pretend the fixes settled.
            result.notes.append(
                f"job did not reach completed within 180s ({exc}); the export below "
                f"may not include every approved fix")
            say("apply", "job did not settle; exporting current state")

    if apply and export_format:
        if export_to:
            written = client.export_to_file(session_id, export_to, export_format)
            result.export = {"format": export_format, "path": str(written),
                             "bytes": written.stat().st_size}
        else:
            result.export = client.export(session_id, export_format)
        say("export", f"{export_format} ({len(result.applied)} fix(es) applied)")

    result.operations = client.usage.operations
    result.seconds = client.usage.seconds
    return result


def _chunk_html(uploaded: dict, html: str) -> dict[str, str]:
    """Map chunk id to its HTML.

    SuperDocs marks chunks with `data-chunk-id` attributes on the elements of the
    returned HTML rather than returning a separate list, so that is where these are
    read from. A `chunks` list is still honoured if one is present.
    """
    out: dict[str, str] = {}
    listed = uploaded.get("chunks") or uploaded.get("sections") or []
    if isinstance(listed, list):
        for c in listed:
            if isinstance(c, dict):
                cid, body = c.get("chunk_id") or c.get("id"), c.get("html") or c.get("content")
                if cid and body:
                    out[str(cid)] = body
    out.update(_chunks_from_attributes(html))
    return out


class _ChunkFinder(HTMLParser):
    """Extracts the outer HTML of every element carrying a data-chunk-id."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found: dict[str, str] = {}
        self._open: list[tuple[str, int, str | None]] = []

    def _pos(self) -> int:
        line, col = self.getpos()
        return self._starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        cid = dict(attrs).get("data-chunk-id")
        self._open.append((tag, self._pos(), cid))

    def handle_endtag(self, tag):
        close = self.rawdata.find(">", self._pos())
        end = (close + 1) if close != -1 else self._pos()
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                _, start, cid = self._open[i]
                del self._open[i:]
                if cid:
                    self.found[cid] = self._source[start:end]
                break

    def parse(self, source: str) -> dict[str, str]:
        starts, pos = [0], 0
        for piece in source.split("\n")[:-1]:
            pos += len(piece) + 1
            starts.append(pos)
        self._starts, self._source = starts, source
        self.feed(source)
        self.close()
        return self.found


def _chunks_from_attributes(html: str) -> dict[str, str]:
    return _ChunkFinder().parse(html) if html else {}


def _job_id(response: dict) -> str | None:
    for key in ("job_id", "id"):
        if response.get(key):
            return str(response[key])
    job = response.get("job")
    if isinstance(job, dict):
        return job.get("job_id") or job.get("id")
    return None
