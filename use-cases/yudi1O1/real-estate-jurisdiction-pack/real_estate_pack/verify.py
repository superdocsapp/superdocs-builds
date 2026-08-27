"""Post-export verification: prove the content landed, don't assume it.

The sibling `supplier-quality-drafter` build learned this the expensive way on a
live run: SuperDocs returned a job with `status: "completed"` whose response
read "0 of 4 asked could be completed", the document was never touched, and the
tool reported success and cached it. That lesson transfers unchanged. "Completed"
is a statement about a job, not about a document.

What is different here is *what* must be proved. For an FMEA the facts were
numbers. For a disclosure pack they are:

* every reference code the three documents cross-reference each other by,
* the statutory text that must survive verbatim,
* the citation authority and the dates that make the pack auditable.

The hard-won rule from that build applies with full force: **`expected_facts`
must mirror exactly what `render.py` emits for this document kind.** A verifier
that demands a disclosure the renderer never emits will reject correct work, and
a verifier that wrongly refuses valid work is worse than no verifier at all. The
parametrised test `test_verifier_accepts_whatever_renderer_emits` locks the two
together for every document kind and every jurisdiction shipped.
"""
from __future__ import annotations

import html
import os
import re
import zipfile
from dataclasses import dataclass, field

from .assemble import INDEX, LEASE, PACKET, DocumentSet
from .entries import disclosures, lease_clauses

#: How much of a statutory passage to use as an anchor. Long enough to be
#: distinctive, short enough to tolerate harmless reflow by the editor.
_ANCHOR_LEN = 80


@dataclass
class VerificationResult:
    checked: int
    missing: list[str] = field(default_factory=list)
    readable: bool = True
    note: str = ""

    @property
    def ok(self) -> bool:
        # An unreadable format cannot be verified either way. Reported honestly
        # rather than counted as a pass or forced into a failure.
        return self.readable and not self.missing


def _norm(text: str) -> str:
    """Collapse whitespace and resolve entities, for human-readable output."""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _compact(text: str) -> str:
    """Normalise for COMPARISON: resolve entities, then remove all whitespace.

    Removing whitespace entirely rather than collapsing it is deliberate, and it
    is what makes the check robust across the three ways this content legitimately
    gets re-laid-out on its way to a file:

    * HTML rendering splits a notice into `</p><p>` and `<br />`, so a passage
      that was one string in the rule is several nodes in the export;
    * a customer template reflows text to its own measure;
    * Word splits a single word across runs (`<w:t>Hous</w:t><w:t>ing</w:t>`),
      so the same word must compare equal whether or not a space appears.

    The trade is that this cannot detect a fault whose ONLY effect is a changed
    space. That is an acceptable blind spot: the failures actually seen in
    practice are whole sections silently dropped and passages reworded, both of
    which change characters, not just spacing. Being insensitive to layout and
    sensitive to wording is exactly the property wanted here — and the
    alternative, a whitespace-sensitive check, produced false failures on
    correct output, which is the worse error because it teaches people to
    ignore the verifier.
    """
    return re.sub(r"\s+", "", html.unescape(text))


def expected_facts(doc_set: DocumentSet, kind: str) -> list[str]:
    """Facts that must appear in the exported file for one document of the pack.

    Drawn from the pack data, never from the output text, and deliberately kept
    in step with `render.py` — see the module docstring.
    """
    req = doc_set.request
    facts: list[str] = [req.pack_id, req.property.full_address()]

    if kind == LEASE:
        facts.append(req.landlord.name)
        facts.extend(t.name for t in req.tenants)
        facts.append(req.tenancy.start_date)
        facts.append(req.tenancy.end_date)
        # The attachment schedule and the required-terms section.
        facts.extend(e.entry_id for e in disclosures(doc_set.entries))
        facts.extend(e.entry_id for e in lease_clauses(doc_set.entries))

    elif kind == PACKET:
        for entry in disclosures(doc_set.entries):
            facts.append(entry.entry_id)
            facts.append(entry.rule.citation.authority)
            if entry.rule.verbatim_statutory:
                # Statutory wording is the thing most worth proving survived.
                anchor = _norm(entry.rule.body)[:_ANCHOR_LEN]
                if anchor:
                    facts.append(anchor)

    elif kind == INDEX:
        # The index enumerates every rule evaluated, so its dates are the proof
        # that the pack is "dated" in the sense the task card asks for.
        for entry in doc_set.entries:
            facts.append(entry.entry_id)
            facts.append(entry.rule.citation.verified_on.isoformat())
            facts.append(entry.rule.citation.review_by.isoformat())

    else:
        raise ValueError(f"Unknown document kind '{kind}'. Expected one of {LEASE}, {PACKET}, {INDEX}.")

    # De-duplicate while preserving order — the same date legitimately appears
    # on many rules, and reporting it missing five times helps nobody.
    return [f for f in dict.fromkeys(facts) if str(f).strip()]


def _extract_text(path: str) -> tuple[str, bool, str]:
    """Return (text, readable, note). Dependency-free: a .docx is a zip, so its
    body XML can be read without pulling in python-docx just to verify."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            # Strip tags so text split across runs still matches as one string.
            return re.sub(r"<[^>]+>", "", xml), True, ""
        except (zipfile.BadZipFile, KeyError, OSError) as e:
            return "", False, f"could not read .docx body ({e})"
    if ext in (".md", ".markdown", ".txt", ".html", ".htm"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            return "", False, f"could not read file ({e})"
        if ext in (".html", ".htm"):
            # Strip markup, or `</p><p>` sits in the middle of every passage that
            # the renderer split into paragraphs and no statutory anchor matches.
            text = re.sub(r"<[^>]+>", " ", text)
        return text, True, ""
    return "", False, f"no text extractor for '{ext}' — verification skipped, not passed"


def verify_export(export_path: str, doc_set: DocumentSet, kind: str) -> VerificationResult:
    facts = expected_facts(doc_set, kind)
    text, readable, note = _extract_text(export_path)
    if not readable:
        return VerificationResult(checked=len(facts), missing=[], readable=False, note=note)
    compacted = _compact(text)
    missing = [f for f in facts if _compact(str(f)) not in compacted]
    return VerificationResult(checked=len(facts), missing=missing, readable=True)


def document_was_modified(job_result: dict, original_html: str) -> bool:
    """Did the turn actually change the document?

    SuperDocs can return a *completed* job whose every operation failed — the
    honest signal is whether updated_html exists and differs from what we sent,
    not whether the status string says 'completed'.
    """
    changes = job_result.get("document_changes")
    if not isinstance(changes, dict):
        return False
    updated = changes.get("updated_html")
    if not updated:
        return False
    return updated.strip() != (original_html or "").strip()
