"""Build the three documents' content, and the instruction that lays them into a
customer's template.

The governing principle here is the same one the sibling supplier-quality build
applies to arithmetic, moved to a domain where the risk is wording rather than
numbers:

    Statutory text is reproduced, never generated.

Where a statute prescribes exact words — California's Megan's Law notice,
Florida's radon paragraph, the federal Lead Warning Statement — that text lives
in the jurisdiction YAML and is emitted here verbatim inside a marked block. The
instruction sent to SuperDocs explicitly tells the model it may restyle and
reflow the surrounding document but must not alter a single word inside those
blocks. A paraphrased statutory notice is a non-compliant notice, and it is the
kind of defect that reads perfectly well.

Every citation, verification date and review date is likewise rendered from the
rule data rather than described to the model.
"""
from __future__ import annotations

import html
from datetime import date
from typing import Optional

from .entries import PackEntry, disclosures, lease_clauses
from .facts import FactView
from .models import UNSET, LeasePackRequest
from .rules import Jurisdiction

#: Wraps text the model must not touch. Referenced by name in the instruction so
#: the rule and the marker cannot drift apart.
VERBATIM_CLASS = "statutory-verbatim"


def esc(value: object) -> str:
    """Escape anything user-supplied before it enters the HTML we send.

    Party names, addresses and free-text answers come from a coordinator's YAML
    file, but they still get escaped: an ampersand in a landlord's trading name
    must not become malformed markup, and a stray angle bracket must never be
    readable as an instruction once this block is embedded in a prompt."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _answer_text(value: object) -> str:
    """Render a recorded answer as words rather than as a Python repr.

    "False" in a legal disclosure reads as a rendering artefact; "No" reads as an
    answer. An unset value should be unreachable here — the validator blocks
    first — so it is labelled explicitly rather than rendered as an empty cell
    that could be mistaken for "no"."""
    if value is UNSET:
        return "NOT ANSWERED"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return str(value)


def _money(value: Optional[float]) -> str:
    if value is None:
        return "TBD"
    return f"${float(value):,.2f}"


def _body_html(text: str, verbatim: bool) -> str:
    """Render a rule body, preserving its line structure.

    Statutory notices carry meaningful layout — checkbox lines, blank fields to
    complete, indented definitions — so paragraphs are emitted as separate
    blocks and single newlines become <br>, rather than collapsing the whole
    thing into one run of prose."""
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    rendered = "".join(f"<p>{esc(b.strip()).replace(chr(10), '<br />')}</p>" for b in blocks)
    if verbatim:
        return (
            f'<div class="{VERBATIM_CLASS}" data-verbatim="true">'
            f"<p><em>The following text is prescribed by statute and is reproduced verbatim. "
            f"Do not reword it.</em></p>{rendered}</div>"
        )
    return rendered


def _party_rows(req: LeasePackRequest) -> str:
    rows = [f"<tr><th>Landlord</th><td>{esc(req.landlord.name)}</td></tr>"]
    for i, tenant in enumerate(req.tenants, start=1):
        label = "Tenant" if len(req.tenants) == 1 else f"Tenant {i}"
        rows.append(f"<tr><th>{esc(label)}</th><td>{esc(tenant.name)}</td></tr>")
    if req.agent and req.agent.name.strip():
        rows.append(f"<tr><th>Managing Agent</th><td>{esc(req.agent.name)}</td></tr>")
    return "".join(rows)


def shared_header(req: LeasePackRequest, jurisdiction: Jurisdiction, doc_title: str) -> str:
    """The identity block every document in the pack carries.

    Rendered once, from one record, into all three documents. This is what makes
    cross-document consistency structural: there is no second place where the
    address or the pack id could be typed differently."""
    return (
        f"<h1>{esc(doc_title)}</h1>"
        f'<table class="pack-identity">'
        f"<tr><th>Pack reference</th><td>{esc(req.pack_id)}</td></tr>"
        f"<tr><th>Property</th><td>{esc(req.property.full_address())}</td></tr>"
        f"<tr><th>Jurisdiction</th><td>{esc(jurisdiction.name)} ({esc(jurisdiction.code)})</td></tr>"
        f"{_party_rows(req)}"
        f"<tr><th>Term</th><td>{esc(req.tenancy.start_date)} to {esc(req.tenancy.end_date)}</td></tr>"
        f"<tr><th>Monthly rent</th><td>{esc(_money(req.tenancy.monthly_rent))}</td></tr>"
        f"<tr><th>Security deposit</th><td>{esc(_money(req.tenancy.security_deposit))}</td></tr>"
        f"</table>"
    )


def render_lease(req: LeasePackRequest, jurisdiction: Jurisdiction, entries: list[PackEntry]) -> str:
    """Document 1 — the lease, carrying this jurisdiction's required clauses and
    an attachment schedule naming every disclosure in the packet."""
    parts = [shared_header(req, jurisdiction, "Residential Lease Agreement")]

    parts.append(
        "<h2>1. Parties and Premises</h2>"
        f"<p>This Lease is made between {esc(req.landlord.name)} (\"Landlord\") and "
        f"{esc(req.all_tenant_names())} (\"Tenant\") for the premises at "
        f"{esc(req.property.full_address())} (the \"Premises\").</p>"
    )

    term_words = "a fixed term" if req.tenancy.term_type == "fixed" else "a month-to-month tenancy"
    parts.append(
        "<h2>2. Term and Rent</h2>"
        f"<p>The tenancy is {esc(term_words)} beginning {esc(req.tenancy.start_date)} and ending "
        f"{esc(req.tenancy.end_date)}. Rent of {esc(_money(req.tenancy.monthly_rent))} is due on day "
        f"{esc(req.tenancy.rent_due_day)} of each month. Landlord holds a security deposit of "
        f"{esc(_money(req.tenancy.security_deposit))}.</p>"
        f"<p>The Premises is let {'furnished' if req.tenancy.furnished else 'unfurnished'}. "
        f"Pets are {'permitted subject to any separate pet agreement' if req.tenancy.pets_permitted else 'not permitted'}.</p>"
    )

    clauses = lease_clauses(entries)
    if clauses:
        parts.append(f"<h2>3. {esc(jurisdiction.name)} Required Terms</h2>")
        for entry in clauses:
            stale_flag = (
                ' <span class="unverified">[UNVERIFIED — past review date]</span>' if entry.stale else ""
            )
            parts.append(
                f'<div class="pack-clause" id="{esc(entry.entry_id)}">'
                f"<h3>{esc(entry.entry_id)}. {esc(entry.title)}{stale_flag}</h3>"
                f"{_body_html(entry.rule.preamble, False) if entry.rule.preamble else ''}"
                f"{_body_html(entry.rule.body, entry.rule.verbatim_statutory)}"
                f'<p class="citation"><small>Authority: {esc(entry.citation_line())}</small></p>'
                f"</div>"
            )

    packet_disclosures = disclosures(entries)
    parts.append("<h2>4. Attachment Schedule</h2>")
    if packet_disclosures:
        parts.append(
            f"<p>The following disclosures form part of this Lease and are delivered with it in the "
            f"disclosure packet for pack reference {esc(req.pack_id)}:</p><ul>"
            + "".join(
                f'<li><strong>{esc(e.entry_id)}</strong> — {esc(e.title)}</li>' for e in packet_disclosures
            )
            + "</ul>"
        )
    else:
        parts.append(
            "<p>No jurisdiction-specific disclosure was triggered for this Premises. The compliance "
            "index records which rules were evaluated and why each did not apply.</p>"
        )

    parts.append(
        "<h2>5. Signatures</h2>"
        f"<p>Landlord: ____________________________ Date: ____________</p>"
        + "".join(
            f"<p>Tenant ({esc(t.name)}): ____________________________ Date: ____________</p>"
            for t in req.tenants
        )
    )
    return "".join(parts)


def render_disclosure_packet(req: LeasePackRequest, jurisdiction: Jurisdiction, entries: list[PackEntry]) -> str:
    """Document 2 — the disclosures themselves, in the order the index lists them."""
    parts = [shared_header(req, jurisdiction, "Required Disclosure Packet")]
    packet = disclosures(entries)

    if not packet:
        parts.append(
            "<p>No disclosure rule in this jurisdiction was triggered by the facts supplied for this "
            "Premises. This is a positive finding, not an empty document: the compliance index lists "
            "every rule that was evaluated.</p>"
        )
        return "".join(parts)

    parts.append(
        f"<p>This packet contains {len(packet)} disclosure(s) required for a residential tenancy at the "
        f"Premises under {esc(jurisdiction.name)} and federal law. Each is identified by the reference "
        f"used in the Lease's attachment schedule and in the compliance index.</p>"
    )

    view = FactView(req)

    for entry in packet:
        rule = entry.rule
        stale_flag = ' <span class="unverified">[UNVERIFIED — past review date]</span>' if entry.stale else ""
        # Where a notice must be answered in both directions, record the answer
        # in the document rather than leaving only an empty checkbox. The
        # validator has already refused to get here with any of them unanswered.
        answers = ""
        if rule.requires_facts:
            rows = "".join(
                f"<tr><th>{esc(name)}</th><td>{esc(_answer_text(view.lookup_fact(name)))}</td></tr>"
                for name in rule.requires_facts
            )
            answers = (
                f'<table class="recorded-answers"><caption>Landlord\'s recorded answers</caption>'
                f"{rows}</table>"
            )
        ack = (
            "<p>Tenant acknowledges receipt of this disclosure.<br />"
            + "".join(
                f"{esc(t.name)}: ____________________________ Date: ____________<br />" for t in req.tenants
            )
            + "</p>"
            if rule.tenant_acknowledgement
            else ""
        )
        parts.append(
            f'<div class="disclosure" id="{esc(entry.entry_id)}">'
            f"<h2>{esc(entry.entry_id)}. {esc(rule.title)}{stale_flag}</h2>"
            f'<p class="delivery"><small>Delivery: {esc(rule.delivery)}.</small></p>'
            f"{_body_html(rule.preamble, False) if rule.preamble else ''}"
            f"{_body_html(rule.body, rule.verbatim_statutory)}"
            f"{answers}"
            f"{ack}"
            f'<p class="citation"><small>Authority: {esc(entry.citation_line())}<br />'
            f"Source: {esc(rule.citation.source_url)}</small></p>"
            f"</div>"
        )
    return "".join(parts)


def render_compliance_index(
    req: LeasePackRequest,
    jurisdiction: Jurisdiction,
    entries: list[PackEntry],
    decisions,
    today: date,
) -> str:
    """Document 3 — the audit trail.

    This is the document that answers "was this pack complete, and how would
    anyone know". It lists every rule the engine evaluated, not only the ones
    that fired, because a reviewer's question is usually "why is there no flood
    disclosure here" and the honest answer is a row saying the rule was
    evaluated and did not apply.
    """
    parts = [shared_header(req, jurisdiction, "Disclosure Compliance Index")]
    parts.append(
        f"<p>Generated {esc(today.isoformat())} for pack reference {esc(req.pack_id)}. Every rule in the "
        f"{esc(jurisdiction.name)} ruleset and the federal layer was evaluated against this Premises. "
        f"Rules that did not apply are listed with that outcome rather than omitted.</p>"
    )

    by_rule_id = {e.rule.id: e for e in entries}

    parts.append(
        "<table class=\"compliance-index\"><thead><tr>"
        "<th>Ref</th><th>Requirement</th><th>Status</th><th>Authority</th>"
        "<th>Verified</th><th>Review by</th></tr></thead><tbody>"
    )
    # Staleness is read from the DECISION, not from the entry. A `limit` rule
    # produces no entry — a deposit cap is a check, not a document — so keying
    # off entries would leave a stale cap silently unmarked here. That is the
    # single most dangerous omission the index could make: a cap that is out of
    # date may approve a deposit that is no longer lawful.
    for decision in decisions:
        rule = decision.rule
        entry = by_rule_id.get(rule.id)
        ref = entry.entry_id if entry else ("cap" if rule.kind == "limit" else "—")
        flagged = decision.applies and decision.stale
        if not decision.applies:
            status = "Evaluated — does not apply"
        elif flagged:
            status = "UNVERIFIED — past review date"
        elif rule.kind == "limit":
            status = "Checked — within limit"
        else:
            status = "Included"
        row_class = ' class="unverified"' if flagged else ""
        parts.append(
            f"<tr{row_class}>"
            f"<td>{esc(ref)}</td>"
            f"<td>{esc(rule.title)}</td>"
            f"<td>{esc(status)}</td>"
            f"<td>{esc(rule.citation.authority)}</td>"
            f"<td>{esc(rule.citation.verified_on.isoformat())}</td>"
            f"<td>{esc(rule.citation.review_by.isoformat())}</td>"
            f"</tr>"
        )
    parts.append("</tbody></table>")

    stale_decisions = [d for d in decisions if d.applies and d.stale]
    if stale_decisions:
        parts.append(
            "<h2>UNVERIFIED items requiring re-check before use</h2>"
            "<p>The following requirements were applied past their review date because the pack was "
            "generated with the stale-content override. Each must be re-verified against its source "
            "before this pack is relied on.</p><ul>"
            + "".join(
                f"<li><strong>{esc(by_rule_id[d.rule.id].entry_id if d.rule.id in by_rule_id else 'cap')}"
                f"</strong> — {esc(d.rule.title)} "
                f"(review was due {esc(d.rule.citation.review_by.isoformat())}): "
                f"{esc(d.rule.citation.source_url)}</li>"
                for d in stale_decisions
            )
            + "</ul>"
        )

    parts.append(
        "<h2>Scope of this index</h2>"
        "<p>This index records which rules from this pack's ruleset were applied. It is a completeness "
        "record for that ruleset, not an opinion that the tenancy complies with all applicable law. "
        "Municipal and county requirements are outside this pack's scope.</p>"
    )
    return "".join(parts)


def build_instruction(document_title: str, content_html: str, req: LeasePackRequest, jurisdiction: Jurisdiction) -> str:
    """The single instruction sent to SuperDocs for one document.

    The content is already finished. The model's job is presentation only, and
    the instruction says so in the terms that matter for this domain: the
    statutory blocks are untouchable, the citations and dates must survive, and
    nothing may be added.
    """
    return (
        f"Lay the following finished content into the open template as a {document_title} for "
        f"{req.property.full_address()} ({jurisdiction.name}, pack reference {req.pack_id}).\n\n"
        f"Rules for this edit, in order of importance:\n"
        f"1. Any block marked class=\"{VERBATIM_CLASS}\" reproduces text prescribed word-for-word by "
        f"statute. Reproduce it EXACTLY. Do not reword, summarise, modernise, correct, or re-punctuate "
        f"it. Paraphrasing a prescribed notice makes it legally non-compliant.\n"
        f"2. Do not add any disclosure, clause, statute reference, or legal statement that is not in the "
        f"content below. If something appears to be missing, say so in your response rather than "
        f"supplying it.\n"
        f"3. Every citation, verification date and review date must survive verbatim.\n"
        f"4. Keep the reference codes (D-1, D-2, L-1, ...) exactly as written — the three documents in "
        f"this pack cross-reference each other by those codes.\n"
        f"5. PRESERVE THE TEMPLATE. Do not delete or replace the document's existing letterhead, "
        f"masthead, firm or company name, strapline, footer, colophon or execution block. Those belong "
        f"to the customer and must still be there afterwards. Replace only the bracketed placeholders "
        f"(for example [document title], [pack reference], [date]) and insert the content below into "
        f"the main body region, leaving every other existing element exactly where it is.\n"
        f"6. Apply the template's own fonts, spacing and heading styles to the content you insert. "
        f"Presentation is yours; wording is not.\n\n"
        f"CONTENT:\n{content_html}"
    )
