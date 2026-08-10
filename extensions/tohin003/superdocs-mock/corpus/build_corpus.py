#!/usr/bin/env python3
"""Generate the synthetic corpus this project records against.

Everything here is fabricated. The companies, people, figures, addresses and dates are
invented for this repository and correspond to nothing real. That is not a disclaimer
bolted on afterwards -- it is the reason the generator exists. Recording fixtures off a
live service means whatever you send comes back in the cassette, so the only safe input
is input that was never anyone's.

Deterministic by construction: no clock, no randomness, no environment. Running this on
any machine produces byte-identical files, so the committed corpus can be verified
against its own generator.

    python corpus/build_corpus.py

Requires python-docx (dev-time only -- it is deliberately not a runtime dependency of the
mock, whose startup time is a graded property).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent

# --- The fictional parties -------------------------------------------------------------
# Invented names. Any resemblance to a real company is coincidence, not sourcing.
SUPPLIER = "Quillon Freight Systems Ltd"
CUSTOMER = "Bexmoor Terminals plc"
AGREEMENT_DATE = "14 March 2026"
FOOTER_MARK = "Synthetic sample document — fictional parties, not a real agreement."

INK = RGBColor(0x1A, 0x1A, 0x1A)
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)
BAND = "EAEEF3"       # alternating row shading
HEAD_BAND = "1F3A5F"  # table header fill


def shade(cell, hex_fill: str) -> None:
    """Table cells carry shading as a w:shd element; python-docx has no helper for it."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def build_master_agreement() -> Path:
    """A heavily styled, ~30-section contract: the 'styled document with sections'.

    Exercises the parse paths that matter for fidelity -- numbered clauses, two tables
    with merged header cells and alternating shading, a running page header and footer
    with a page-number field, and page geometry the upload should detect.
    """
    doc = Document()

    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)  # A4
    for side in ("top", "bottom", "left", "right"):
        setattr(section, f"{side}_margin", Inches(1.0))

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK

    # Running header
    header_p = section.header.paragraphs[0]
    header_p.text = f"{SUPPLIER} — Master Services Agreement"
    header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_p.runs[0].font.size = Pt(8)
    header_p.runs[0].font.color.rgb = ACCENT

    # Running footer, with a real PAGE field so export fidelity is testable
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer_p.add_run(f"{FOOTER_MARK}    Page ")
    run.font.size = Pt(8)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    footer_p._p.append(fld)

    title = doc.add_heading("Master Services Agreement", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    intro = doc.add_paragraph()
    intro.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = intro.add_run(f"between {SUPPLIER} and {CUSTOMER}\nDated {AGREEMENT_DATE}")
    r.italic = True
    r.font.size = Pt(10)

    doc.add_heading("Parties", level=1)
    doc.add_paragraph(
        f"(1) {SUPPLIER}, a company incorporated in England and Wales under company "
        "number 09122447, whose registered office is at 14 Cranmoor Wharf, Bristol "
        "BS1 4QT (the \"Supplier\"); and"
    )
    doc.add_paragraph(
        f"(2) {CUSTOMER}, a company incorporated in England and Wales under company "
        "number 07741930, whose registered office is at Bexmoor Dock, Unit 3, Hull "
        "HU9 1PL (the \"Customer\")."
    )

    doc.add_heading("Background", level=1)
    doc.add_paragraph(
        "(A) The Customer operates bulk terminal facilities and requires inland "
        "haulage, container drayage and customs brokerage services."
    )
    doc.add_paragraph(
        "(B) The Supplier has agreed to provide those services on the terms of this "
        "Agreement."
    )

    clauses: list[tuple[str, str]] = [
        ("Definitions and Interpretation",
         "In this Agreement the following expressions have the meanings set out below. "
         "\"Business Day\" means a day other than a Saturday, Sunday or public holiday "
         "in England. \"Charges\" means the amounts payable under clause 6. \"Services\" "
         "means the services described in Schedule 1. Headings do not affect "
         "interpretation, and a reference to a clause is a reference to a clause of "
         "this Agreement."),
        ("Commencement and Term",
         "This Agreement takes effect on 1 April 2026 and continues for an initial "
         "term of twenty-four (24) months, after which it renews automatically for "
         "successive twelve (12) month periods unless either party gives not less "
         "than ninety (90) days' written notice."),
        ("Supply of Services",
         "The Supplier shall provide the Services with reasonable skill and care, in "
         "accordance with the service levels in Schedule 2, and shall allocate "
         "sufficient competent personnel and equipment to do so."),
        ("Customer Obligations",
         "The Customer shall provide accurate consignment data not less than four (4) "
         "hours before each collection window, ensure safe site access, and hold all "
         "permits required for the goods presented."),
        ("Personnel and Subcontracting",
         "The Supplier may subcontract any part of the Services to a subcontractor on "
         "its approved list, and remains liable for the acts and omissions of each "
         "subcontractor as if they were its own."),
        ("Charges and Payment",
         "The Customer shall pay the Charges in Schedule 1 within thirty (30) days of "
         "the date of a valid invoice. Charges are exclusive of VAT. Rates are fixed "
         "for the first twelve (12) months and may then be adjusted once annually by "
         "no more than the change in the Consumer Prices Index."),
        ("Fuel and Surcharges",
         "A fuel surcharge applies where the published weekly diesel index moves more "
         "than four per cent (4%) from the baseline of 148.20 pence per litre recorded "
         "on 1 March 2026. The surcharge is calculated monthly in arrears."),
        ("Late Payment",
         "Interest accrues on overdue sums at four per cent (4%) above the Bank of "
         "England base rate, accruing daily from the due date until payment."),
        ("Service Levels and Service Credits",
         "Where the Supplier fails to meet a service level in Schedule 2 in any "
         "measurement period, the Customer's sole financial remedy is the "
         "corresponding service credit, save in the case of persistent failure as "
         "defined in clause 10."),
        ("Persistent Failure",
         "Three (3) or more service level failures of the same measure in any rolling "
         "six (6) month period constitute persistent failure, entitling the Customer "
         "to terminate the affected service line on thirty (30) days' notice."),
        ("Insurance",
         "The Supplier shall maintain goods-in-transit insurance of not less than "
         "£2,000,000 per consignment and public liability insurance of not less than "
         "£10,000,000 in the aggregate, and shall produce certificates on request."),
        ("Liability",
         "Neither party excludes liability for death or personal injury caused by "
         "negligence or for fraud. Subject to that, the Supplier's total aggregate "
         "liability in any contract year is limited to one hundred and twenty-five "
         "per cent (125%) of the Charges paid in that year."),
        ("Indemnity",
         "The Customer shall indemnify the Supplier against all claims arising from "
         "inaccurate consignment data, misdeclared goods, or the presentation of "
         "goods requiring a permit the Customer does not hold."),
        ("Confidentiality",
         "Each party shall keep confidential all Confidential Information of the "
         "other, use it only for the purposes of this Agreement, and return or destroy "
         "it on termination. This obligation survives for five (5) years."),
        ("Data Protection",
         "Each party shall comply with applicable data protection law. The parties "
         "acknowledge that the Supplier acts as processor in respect of driver and "
         "consignee contact data, and Schedule 3 sets out the processing particulars."),
        ("Intellectual Property",
         "All intellectual property rights in the Supplier's routing and telematics "
         "systems remain the Supplier's property. The Customer is granted a "
         "non-exclusive, non-transferable licence to use the tracking portal during "
         "the term."),
        ("Audit",
         "The Customer may, on not less than fifteen (15) Business Days' notice and no "
         "more than once in any twelve (12) month period, audit the Supplier's records "
         "relating to the Charges."),
        ("Force Majeure",
         "Neither party is liable for a failure to perform caused by an event beyond "
         "its reasonable control, provided it notifies the other promptly and uses "
         "reasonable endeavours to mitigate. Industrial action confined to the "
         "affected party's own workforce is excluded."),
        ("Suspension",
         "The Supplier may suspend the Services where an invoice remains unpaid for "
         "more than forty-five (45) days, having given fourteen (14) days' written "
         "warning."),
        ("Termination",
         "Either party may terminate immediately on written notice if the other "
         "commits a material breach that is not remedied within thirty (30) days of "
         "notice, or becomes subject to an insolvency event."),
        ("Consequences of Termination",
         "On termination the Supplier shall complete consignments already in transit, "
         "return Customer property within ten (10) Business Days, and invoice for "
         "Services performed up to the termination date."),
        ("Assignment",
         "Neither party may assign or transfer this Agreement without the other's "
         "prior written consent, such consent not to be unreasonably withheld, save "
         "to a member of its own group."),
        ("Notices",
         "Notices must be in writing and delivered by hand or by recorded post to the "
         "registered office of the recipient, or by email to the address notified for "
         "that purpose. Email notice is not valid for termination."),
        ("Anti-Bribery and Modern Slavery",
         "Each party shall comply with the Bribery Act 2010 and the Modern Slavery Act "
         "2015, maintain appropriate policies, and notify the other of any breach "
         "affecting this Agreement."),
        ("Dispute Resolution",
         "The parties shall first refer any dispute to their respective operations "
         "directors, and if unresolved after twenty (20) Business Days, to mediation "
         "under the CEDR Model Mediation Procedure before commencing proceedings."),
        ("Variation",
         "No variation of this Agreement is effective unless in writing and signed by "
         "an authorised signatory of each party."),
        ("Waiver",
         "A failure or delay in exercising a right under this Agreement does not "
         "operate as a waiver of that right."),
        ("Severance",
         "If any provision is held invalid, it shall be modified to the minimum extent "
         "necessary, and the remainder of the Agreement continues in force."),
        ("Third Party Rights",
         "A person who is not a party has no right under the Contracts (Rights of "
         "Third Parties) Act 1999 to enforce any term of this Agreement."),
        ("Entire Agreement",
         "This Agreement constitutes the entire agreement between the parties and "
         "supersedes all prior arrangements, save that nothing limits liability for "
         "fraudulent misrepresentation."),
        ("Counterparts",
         "This Agreement may be executed in counterparts, each of which is an "
         "original and which together constitute one instrument."),
        ("Governing Law and Jurisdiction",
         "This Agreement and any dispute arising out of it are governed by the law of "
         "England and Wales, and the parties submit to the exclusive jurisdiction of "
         "the courts of England and Wales."),
    ]

    for index, (heading, body) in enumerate(clauses, start=1):
        doc.add_heading(f"{index}. {heading}", level=1)
        doc.add_paragraph(body)

    # --- Schedule 1: charges, with merged header cells and alternating shading ---------
    doc.add_page_break()
    doc.add_heading("Schedule 1 — Charges", level=1)

    charges = [
        ("Inland haulage", "Per container, ≤ 120 km", "£184.00", "Monthly in arrears"),
        ("Inland haulage", "Per container, 121–260 km", "£241.50", "Monthly in arrears"),
        ("Container drayage", "Per lift", "£62.00", "Monthly in arrears"),
        ("Customs brokerage", "Per declaration", "£38.50", "Per declaration"),
        ("Bonded storage", "Per TEU per day", "£11.25", "Weekly"),
        ("Out-of-hours collection", "Per booking", "£95.00", "Monthly in arrears"),
        ("Demurrage recharge", "At cost plus 8%", "At cost", "As incurred"),
    ]

    table = doc.add_table(rows=2 + len(charges), cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Merged banner row across all four columns
    banner = table.rows[0].cells
    merged = banner[0].merge(banner[3])
    merged.text = "Schedule of Charges — effective 1 April 2026"
    shade(merged, HEAD_BAND)
    run = merged.paragraphs[0].runs[0]
    run.bold = True
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    merged.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    for cell, label in zip(table.rows[1].cells, ("Service", "Basis", "Rate", "Billing")):
        cell.text = label
        shade(cell, BAND)
        cell.paragraphs[0].runs[0].bold = True

    for row_index, row_values in enumerate(charges):
        cells = table.rows[row_index + 2].cells
        for cell, value in zip(cells, row_values):
            cell.text = value
            if row_index % 2 == 1:          # alternating row shading
                shade(cell, "F5F7FA")

    # --- Schedule 2: service levels ---------------------------------------------------
    doc.add_heading("Schedule 2 — Service Levels", level=1)
    levels = [
        ("On-time collection", "≥ 97.0%", "Calendar month", "2% of monthly Charges"),
        ("On-time delivery", "≥ 95.5%", "Calendar month", "3% of monthly Charges"),
        ("Declaration accuracy", "≥ 99.2%", "Calendar month", "1% of monthly Charges"),
        ("Portal availability", "≥ 99.5%", "Calendar month", "1% of monthly Charges"),
    ]
    sl = doc.add_table(rows=1 + len(levels), cols=4)
    sl.style = "Table Grid"
    for cell, label in zip(
        sl.rows[0].cells, ("Measure", "Target", "Measurement period", "Service credit")
    ):
        cell.text = label
        shade(cell, HEAD_BAND)
        run = cell.paragraphs[0].runs[0]
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for row_index, row_values in enumerate(levels):
        for cell, value in zip(sl.rows[row_index + 1].cells, row_values):
            cell.text = value
            if row_index % 2 == 1:
                shade(cell, BAND)

    doc.add_heading("Schedule 3 — Processing Particulars", level=1)
    doc.add_paragraph(
        "Subject matter: provision of inland haulage and customs brokerage. Duration: "
        "the term of this Agreement. Categories of data subject: drivers, consignees "
        "and site contacts. Categories of personal data: name, work telephone number, "
        "work email address, vehicle registration."
    )

    doc.add_heading("Execution", level=1)
    doc.add_paragraph(f"Signed for and on behalf of {SUPPLIER}: ____________________")
    doc.add_paragraph(f"Signed for and on behalf of {CUSTOMER}: ____________________")

    out = HERE / "master-services-agreement.docx"
    doc.save(out)
    return out


def build_status_report() -> Path:
    """A plain Markdown source -- the second format in the declared accepted set."""
    text = """# Q1 2026 Terminal Operations Review

**Prepared for:** Bexmoor Terminals plc
**Prepared by:** Quillon Freight Systems Ltd
**Period:** 1 January – 31 March 2026

## Summary

Volumes recovered through February after the January weather disruption. On-time
collection finished the quarter at 96.4%, below the 97.0% contractual target, and a
service credit of 2% of monthly Charges applies for January only.

## Volumes

| Month | Containers moved | Declarations filed | On-time collection |
|---|---|---|---|
| January | 4,118 | 2,904 | 91.8% |
| February | 5,260 | 3,517 | 97.9% |
| March | 5,644 | 3,802 | 98.1% |

## Issues carried into Q2

1. Bonded storage utilisation reached 88% in March; overflow arrangements are needed
   before the summer peak.
2. Two subcontractors remain outside the approved list pending insurance certificates.
3. The tracking portal recorded 99.31% availability, marginally under the 99.5% target.

## Recommendations

- Bring forward the Q3 capacity review to May.
- Renegotiate the out-of-hours collection rate, which is now materially above market.
- Close the two outstanding subcontractor approvals before the April renewal date.

---

*Synthetic sample document — fictional parties, not a real report.*
"""
    out = HERE / "q1-operations-review.md"
    out.write_text(text, encoding="utf-8")
    return out


def build_oversize_html(sections: int = 25_600) -> Path:
    """A document past the documented 25,000-sections-per-document scale limit.

    Used once, to record the DOCUMENT_TOO_COMPLEX capacity refusal. Kept as small as it
    can be while still crossing the limit -- the point is the section count, not the byte
    count, and there is no reason to push more data at a live service than the behaviour
    requires.
    """
    parts = [
        "<h1>Consolidated Consignment Register 2026</h1>",
        "<p>Synthetic sample document — fictional consignments, generated to exercise "
        "the documented per-document section limit.</p>",
    ]
    for n in range(1, sections + 1):
        parts.append(
            f"<p>Line {n:05d}: consignment QF-{n:06d}, 1 TEU, Bristol to Hull, "
            f"cleared, £{184 + (n % 60):,}.00</p>"
        )
    out = HERE / "oversize-consignment-register.html"
    out.write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Consolidated Consignment Register 2026</title></head><body>"
        + "".join(parts)
        + "</body></html>",
        encoding="utf-8",
    )
    return out


def build_large_register(sections: int = 400) -> Path:
    """A document large enough that a whole-document edit may not fit in one turn.

    Sized to provoke the documented continue_prompt pause without provoking the capacity
    refusal: comfortably under the 25,000-section limit, comfortably over what one turn
    is likely to finish. Every line is fabricated.
    """
    rows = "".join(
        f"<h2>Consignment QF-{n:04d}</h2>"
        f"<p>Origin Bristol, destination Hull. One TEU, cleared {8 + (n % 20)} "
        f"March 2026. Haulage charged at £{184 + (n % 40)}.00 with a storage "
        f"recharge of £{11 + (n % 9)}.25. Status: delivered, POD on file.</p>"
        for n in range(1, sections + 1)
    )
    out = HERE / "large-consignment-register.html"
    out.write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Consignment Register — Q1 2026</title></head><body>"
        "<h1>Consignment Register — Q1 2026</h1>"
        "<p>Synthetic sample document — fictional consignments.</p>"
        + rows
        + "</body></html>",
        encoding="utf-8",
    )
    return out


def build_legacy_doc_stub() -> Path:
    """A file with a .doc extension, carrying the OLE2 compound-file magic bytes.

    Honest about what it is: this probes extension handling, which is what the
    documented 415 keys on ("Unsupported file type: .doc"). It is not a faithful
    Word 97-2003 binary and is not claimed to be one.
    """
    ole2_magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
    out = HERE / "legacy-format-probe.doc"
    out.write_bytes(ole2_magic + b"\x00" * 504 + b"SYNTHETIC PROBE FILE" + b"\x00" * 24)
    return out


def build_odt_probe() -> Path:
    """A minimal but structurally valid ODT, to settle F-003.

    /concepts/documents lists ODT as supported; /errors/error-codes omits it from the
    415 message's supported-type list. One live upload decides which page is right.
    """
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.2"><office:body><office:text>'
        "<text:h text:outline-level=\"1\">Haulage Rate Card 2026</text:h>"
        "<text:p>Synthetic sample document — fictional rates.</text:p>"
        "<text:p>Inland haulage, per container, up to 120 km: 184.00</text:p>"
        "<text:p>Container drayage, per lift: 62.00</text:p>"
        "</office:text></office:body></office:document-content>"
    )
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest '
        'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">'
        '<manifest:file-entry manifest:full-path="/" '
        'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
        '<manifest:file-entry manifest:full-path="content.xml" '
        'manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    out = HERE / "rate-card.odt"
    # Fixed timestamp on every entry keeps the archive byte-identical between runs.
    when = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(out, "w") as z:
        mime = zipfile.ZipInfo("mimetype", date_time=when)
        mime.compress_type = zipfile.ZIP_STORED
        z.writestr(mime, "application/vnd.oasis.opendocument.text")
        for name, payload in (
            ("META-INF/manifest.xml", manifest),
            ("content.xml", content),
        ):
            info = zipfile.ZipInfo(name, date_time=when)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, payload)
    return out


def main() -> None:
    builders = (
        build_master_agreement,
        build_status_report,
        build_oversize_html,
        build_large_register,
        build_legacy_doc_stub,
        build_odt_probe,
    )
    for build in builders:
        path = build()
        print(f"  {path.name:42s} {path.stat().st_size:>10,d} bytes")


if __name__ == "__main__":
    main()
