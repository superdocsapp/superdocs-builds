"""Build the sample documents the three parts edit.

Everything here is invented. Northwind Facilities Group, Harbour Lane Analytics
and every number in these documents are fictional, on purpose: a tutorial that
ships a real client's contract is a tutorial nobody can safely run.

    python3 sample/make_samples.py            # the small agreement
    python3 sample/make_samples.py --big 55   # plus a 55 page tender response

The big one exists because part three is about documents at real sizes, and a two
page sample would let the tutorial lie about what happens at fifty.
"""

from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent

SMALL = """<h1>Master Services Agreement</h1>
<p><strong>Between:</strong> Northwind Facilities Group Ltd ("the Supplier") and
Harbour Lane Analytics Ltd ("the Client"). Both parties are fictional and this
document exists only as tutorial material.</p>

<h2>1. Scope of services</h2>
<p>The Supplier will provide planned and reactive maintenance across the Client's
three sites, to the standards set out in Schedule A. Work outside Schedule A is
quoted separately and begins only on written instruction.</p>

<h2>2. Term and termination</h2>
<p>This agreement runs for twenty four months from the commencement date. Either
party may terminate for material breach on thirty days written notice, where the
breach remains unremedied at the end of that period.</p>

<h2>3. Charges and payment</h2>
<p>Charges are invoiced monthly in arrears. Payment falls due thirty days from
the invoice date. The Supplier may suspend non-critical work on any amount that
remains unpaid sixty days after its due date.</p>
<table border="1" cellpadding="6" cellspacing="0">
  <tr><th>Service line</th><th>Basis</th><th>Monthly charge</th></tr>
  <tr><td>Planned maintenance</td><td>Fixed</td><td>4,200</td></tr>
  <tr><td>Reactive callout, business hours</td><td>Per visit</td><td>180</td></tr>
  <tr><td>Reactive callout, out of hours</td><td>Per visit</td><td>320</td></tr>
  <tr><td>Consumables</td><td>At cost plus 8 percent</td><td>Variable</td></tr>
</table>

<h2>4. Service levels</h2>
<p>Response times are measured from the time a ticket is raised in the Client's
portal to the time an engineer is on site. Priority one tickets carry a four hour
response target, measured during business hours.</p>

<h2>5. Governing law</h2>
<p>This agreement is governed by the laws of England and Wales, and both parties
submit to the exclusive jurisdiction of its courts.</p>
"""

SECTION_TITLES = [
    "Executive summary",
    "Understanding of requirement",
    "Technical approach",
    "Mobilisation and transition",
    "Programme and milestones",
    "Resourcing and key personnel",
    "Quality management",
    "Health, safety and environment",
    "Social value",
    "Risk management",
    "Contract management",
    "Pricing and commercial model",
    "Performance measurement",
    "Continuous improvement",
    "Compliance matrix",
    "Business continuity",
    "Data protection",
    "Subcontracting and supply chain",
    "Community engagement",
    "Exit management",
]

BODY = (
    "The approach set out in this section follows the specification issued with the "
    "invitation to tender and is written against the evaluation criteria published "
    "alongside it. Every commitment below is deliverable with the resources named in "
    "the resourcing section and carries a named owner. Where the specification allows "
    "an alternative method, the alternative and the reason for choosing it are stated "
    "so the evaluator does not have to infer either. Evidence for each claim sits in "
    "the appendix under the reference given at the end of the paragraph."
)


def big_document(pages: int) -> str:
    """Roughly `pages` printed pages of tender response, with a compliance table.

    About six paragraphs of this body text fill a page, which is close enough for
    a tutorial that only needs the document to behave like a long one.
    """
    parts = [
        "<h1>Response to Invitation to Tender ITT-2026-0148</h1>",
        "<p>Submitted by Northwind Facilities Group Ltd. Fictional bid, tutorial "
        "material only. Reference numbers, personnel and figures are invented.</p>",
    ]
    paragraphs_needed = max(pages, 1) * 6
    written = 0
    section = 0
    while written < paragraphs_needed:
        title = SECTION_TITLES[section % len(SECTION_TITLES)]
        number = section + 1
        parts.append(f"<h2>{number}. {title}</h2>")
        for para in range(4):
            parts.append(f"<p>{number}.{para + 1} {BODY}</p>")
            written += 1
        if section % 5 == 4:
            parts.append(
                "<table border='1' cellpadding='6' cellspacing='0'>"
                "<tr><th>Requirement</th><th>Met</th><th>Evidence reference</th></tr>"
                + "".join(
                    f"<tr><td>Requirement {number}.{row}</td><td>Yes</td>"
                    f"<td>Appendix {number}, item {row}</td></tr>"
                    for row in range(1, 6)
                )
                + "</table>"
            )
            written += 1
        section += 1
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--big", type=int, default=0, help="pages of tender response to generate")
    args = ap.parse_args()

    small = HERE / "service-agreement.html"
    small.write_text(SMALL, encoding="utf-8")
    print(f"wrote {small.relative_to(HERE.parent)} ({len(SMALL) / 1024:.1f} KB)")

    if args.big:
        html = big_document(args.big)
        big = HERE / "tender-response.html"
        big.write_text(html, encoding="utf-8")
        print(f"wrote {big.relative_to(HERE.parent)} ({len(html) / 1024:.1f} KB, ~{args.big} pages)")


if __name__ == "__main__":
    main()
