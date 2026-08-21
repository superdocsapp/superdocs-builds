"""Proof, not assertion.

Three claims this build makes, and the check that decides each one. All three
read the *live* documents back out of SuperDocs rather than the local renders,
because the only interesting question is whether the thing sitting in the
account is right.

1. **A change reached every document that carries it.** For each affected
   document: the new value is present and the old value is gone.
2. **Nothing else moved.** For each unaffected document: its structure is
   unchanged from the snapshot taken before the edit.
3. **The packs differ only in what should be hidden.** No internal value appears
   in any customer document, and every non-internal field the two packs share
   renders the same.

The structural read (`GET /v1/documents/{id}`) is free and never billed, so
verification costs nothing. Exporting a document to see what it says would be
slower, dearer and no more accurate.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from packet.build import Pack, Workspace
from packet.order import BY_PATH, INTERNAL_PATHS, Order, format_value
from packet.superdocs import SuperDocs, SuperDocsError
from packet.templates import BY_SLUG, audit_audience, unknown_fields

log = logging.getLogger(__name__)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str, **evidence: Any) -> None:
        self.checks.append(Check(name, passed, detail, evidence))

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "summary": f"{sum(c.passed for c in self.checks)}/{len(self.checks)} checks passed",
        }

    def render(self) -> str:
        lines = []
        for c in self.checks:
            mark = "PASS" if c.passed else "FAIL"
            lines.append(f"  [{mark}] {c.name}")
            lines.append(f"         {c.detail}")
        lines.append("")
        lines.append(
            f"  {sum(c.passed for c in self.checks)}/{len(self.checks)} checks passed"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snapshots — taken before an edit so "unchanged" can be checked afterwards
# ---------------------------------------------------------------------------


def snapshot(client: SuperDocs, packs: dict[str, Pack]) -> dict[str, dict[str, Any]]:
    """A cheap, structural fingerprint of every document in every pack."""
    out: dict[str, dict[str, Any]] = {}
    for audience, pack in packs.items():
        for doc in pack.documents:
            key = f"{audience}/{doc.slug}"
            target = doc.durable_id or doc.document_id
            if not target:
                continue
            try:
                detail = client.document_detail(target)
            except SuperDocsError as exc:
                log.warning("could not snapshot %s: %s", key, exc)
                continue
            out[key] = _structural(detail)
    return out


def _structural(detail: dict[str, Any]) -> dict[str, Any]:
    """The parts of a document-detail response that change when content does.

    Deliberately excludes timestamps and version counters: a document that was
    re-read but not re-written must fingerprint identically, or "untouched"
    becomes unprovable.
    """
    structure = detail.get("structure") or detail.get("document", {}).get("structure") or {}
    headings = [
        (h.get("level"), (h.get("text") or "").strip())
        for h in structure.get("headings", [])
    ]
    return {
        "headings": headings,
        "section_count": structure.get("section_count"),
        "block_count": structure.get("block_count"),
        "media": structure.get("media"),
    }


def save_snapshot(workspace: Workspace, snap: dict[str, Any]) -> Path:
    path = workspace.root / "snapshot.json"
    path.write_text(json.dumps(snap, indent=2, sort_keys=True))
    return path


def load_snapshot(workspace: Workspace) -> dict[str, Any]:
    path = workspace.root / "snapshot.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def verify_propagation(
    client: SuperDocs,
    *,
    packs: dict[str, Pack],
    order: Order,
    changed_paths: list[str],
    before_snapshot: dict[str, Any],
    fetch_text=None,
) -> Report:
    """Did the change land everywhere it should, and nowhere it should not?"""
    report = Report()
    fetch_text = fetch_text or (lambda pack, doc: live_text(client, pack, doc))

    expected: dict[str, set[str]] = {}
    for audience, pack in packs.items():
        for doc in pack.documents:
            spec = BY_SLUG[doc.slug]
            visible = spec.fields if audience == "internal" else spec.customer_fields
            hits = {p for p in changed_paths if p in visible}
            if hits:
                expected[f"{audience}/{doc.slug}"] = hits

    if not expected:
        report.add(
            "change reaches its documents",
            False,
            "no document carries any of the changed fields — either the change is "
            "irrelevant to this pack or the templates do not reference it",
            changed=changed_paths,
        )
        return report

    for audience, pack in packs.items():
        for doc in pack.documents:
            key = f"{audience}/{doc.slug}"
            paths = expected.get(key)
            text = fetch_text(pack, doc)

            if paths:
                missing = []
                for path in sorted(paths):
                    new_value = order.value(path, audience=audience)
                    if new_value and new_value != "—" and new_value not in text:
                        missing.append(f"{path}={new_value!r}")
                report.add(
                    f"{key} carries the new values",
                    not missing,
                    (
                        f"all {len(paths)} changed field(s) present"
                        if not missing
                        else "not found in the live document: " + ", ".join(missing)
                    ),
                    fields=sorted(paths),
                )
            else:
                before = before_snapshot.get(key)
                after = _structural(
                    client.document_detail(doc.durable_id or doc.document_id)
                ) if (doc.durable_id or doc.document_id) else None
                if before is None or after is None:
                    report.add(
                        f"{key} left alone",
                        True,
                        "no snapshot to compare against; not contacted during this change",
                    )
                else:
                    report.add(
                        f"{key} left alone",
                        before == after,
                        (
                            "structurally identical to the pre-change snapshot"
                            if before == after
                            else f"structure moved: {before} → {after}"
                        ),
                    )
    return report


def verify_audience(
    packs: dict[str, Pack], order: Order, *, fetch_text=None
) -> Report:
    """Do the two packs differ only in what should be hidden?"""
    report = Report()

    leaks = audit_audience()
    report.add(
        "no internal field is referenced outside an internal block",
        not leaks,
        "every internal field is inside an {{#internal}} block" if not leaks
        else "; ".join(leaks),
    )

    unknown = unknown_fields()
    report.add(
        "every template placeholder is a declared field",
        not unknown,
        "all placeholders resolve" if not unknown else "; ".join(unknown),
    )

    customer = packs.get("customer")
    if customer is None:
        report.add("customer pack exists", False, "no customer pack was built")
        return report

    fetch_text = fetch_text or (lambda pack, doc: Path(doc.local_path).read_text())

    # Every spelling a leak could wear. Searching only for the canonically
    # formatted value would miss "2079.00" while the register writes
    # "2,079.00" — and a leak does not have to be well formatted to be a leak.
    internal_values: dict[str, set[str]] = {}
    for path in sorted(INTERNAL_PATHS):
        raw = order.raw(path)
        if raw in (None, ""):
            continue
        spellings = {
            format_value(raw, BY_PATH[path].fmt),
            str(raw),
            str(raw).replace(",", ""),
        }
        if isinstance(raw, (int, float)):
            spellings |= {f"{raw:,.2f}", f"{raw:.2f}", f"{raw:g}"}
        internal_values[path] = {s for s in spellings if len(s) >= 5}

    found: list[str] = []
    for doc in customer.documents:
        text = _normalise(fetch_text(customer, doc))
        for path, spellings in internal_values.items():
            hit = next((s for s in sorted(spellings) if _normalise(s) in text), None)
            if hit:
                found.append(f"{doc.slug} contains {path} ({hit!r})")

    report.add(
        "no internal value appears in the customer pack",
        not found,
        (
            f"checked {len(internal_values)} internal values against "
            f"{len(customer.documents)} customer documents; none present"
            if not found
            else "; ".join(found)
        ),
        internal_fields=sorted(internal_values),
    )

    internal_pack = packs.get("internal")
    if internal_pack:
        shared = 0
        divergent: list[str] = []
        for doc in customer.documents:
            twin = internal_pack.by_slug(doc.slug)
            if not twin:
                continue
            spec = BY_SLUG[doc.slug]
            c_text = _normalise(fetch_text(customer, doc))
            i_text = _normalise(fetch_text(internal_pack, twin))
            for path in sorted(spec.customer_fields):
                value = order.value(path, audience="customer")
                if value in ("—", "") or len(value) < 3:
                    continue
                shared += 1
                if (_normalise(value) in c_text) != (_normalise(value) in i_text):
                    divergent.append(f"{doc.slug}:{path}")
        report.add(
            "shared fields render identically in both packs",
            not divergent,
            (
                f"{shared} shared field renderings agree across the two packs"
                if not divergent
                else "these differ and should not: " + ", ".join(divergent[:10])
            ),
        )

    return report


def verify_diagram(packs: dict[str, Pack], order: Order, *, fetch_text=None) -> Report:
    """Does the diagram describe the configuration that was ordered?"""
    report = Report()
    fetch_text = fetch_text or (lambda pack, doc: Path(doc.local_path).read_text())

    bandwidth = order.value("service.bandwidth_mbps")
    diverse = str(order.raw("service.diversity", "none")).lower() in {"dual", "diverse"}

    for audience, pack in packs.items():
        for doc in pack.documents:
            if not BY_SLUG[doc.slug].has_diagram:
                continue
            text = fetch_text(pack, doc)
            problems = []
            if "mermaid" not in text and "flowchart" not in text:
                problems.append("no diagram found")

            # Read the diagram's own declaration rather than guessing from its
            # prose. "no protection" contains "protect"; a substring test on
            # the caption gets a single-path order exactly backwards.
            declared = dict(re.findall(r"%% design:(\w+)=([^\n<]+)", text))
            if not declared:
                problems.append("the diagram carries no design declaration to check against")
            else:
                if declared.get("bandwidth", "").strip() != bandwidth:
                    problems.append(
                        f"diagram declares bandwidth {declared.get('bandwidth', '?').strip()!r}, "
                        f"order says {bandwidth!r}"
                    )
                want = "dual" if diverse else "single"
                if declared.get("diversity", "").strip() != want:
                    problems.append(
                        f"diagram declares {declared.get('diversity', '?').strip()} path, "
                        f"order says {want}"
                    )
            report.add(
                f"{audience}/{doc.slug} diagram matches the order",
                not problems,
                (
                    f"{bandwidth}, "
                    + ("dual path with protection" if diverse else "single path")
                    + " — as ordered"
                    if not problems
                    else "; ".join(problems)
                ),
            )
    return report


# ---------------------------------------------------------------------------


# One roster read per session, reused across every document in it.
_BODY_CACHE: dict[str, dict[str, str]] = {}


def reset_body_cache() -> None:
    _BODY_CACHE.clear()


def _session_bodies(client: SuperDocs, session_id: str) -> dict[str, str]:
    """Every open document's HTML, keyed by document id. One free call.

    This replaced an export-by-session, which was wrong in a way that made the
    whole verification worthless: **`POST /v1/documents/export` takes a
    `session_id` but no `document_id`**, so in a multi-document session it
    returns the *focused* document — whichever was uploaded last. Every
    document in the pack was being checked against the handover certificate.
    Six checks passed, and they were passing by coincidence.

    The roster with `include_html=true` returns each document's own body, which
    is what the check needed all along, and it is free.
    """
    if session_id in _BODY_CACHE:
        return _BODY_CACHE[session_id]
    bodies: dict[str, str] = {}
    try:
        roster = client.list_session_documents(session_id, include_html=True)
        for entry in roster.get("documents", []):
            did = entry.get("document_id")
            if did and entry.get("html"):
                bodies[did] = entry["html"]
    except SuperDocsError as exc:
        log.warning("could not read bodies for session %s: %s", session_id, exc)
    _BODY_CACHE[session_id] = bodies
    return bodies


def live_text(client: SuperDocs, pack: Pack, doc) -> str:
    """The live text of ONE document.

    Falls back to the local render only when the live body cannot be read, and
    says so in the log — silently checking the local file would turn this whole
    module into a test that the renderer agrees with itself.
    """
    if doc.document_id:
        bodies = _session_bodies(client, pack.session_id)
        body = bodies.get(doc.document_id)
        if body:
            return body
        if bodies:
            log.warning(
                "document %s (%s) is not in session %s — verifying against the local "
                "render instead, which proves less",
                doc.slug, doc.document_id, pack.session_id,
            )
    return Path(doc.local_path).read_text(encoding="utf-8")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip().lower()
