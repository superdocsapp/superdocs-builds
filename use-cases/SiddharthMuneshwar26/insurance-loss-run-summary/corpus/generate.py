"""Synthetic insurance loss-run corpus.

Everything here is fabricated. Meridian Cold Chain Logistics, Kestrel Mutual
and Ardent Risk Partners do not exist, and no figure is drawn from any real
claim, policy or company.

Why loss runs. A loss run is a carrier's claims history for one policy year.
The thing that makes them hard in real life is that they get reissued: the same
claim shows one incurred amount in the run issued in 2024 and a much larger one
in the run issued in 2026, because reserves develop as a claim matures. Neither
document is wrong. They disagree, and somebody has to know which one they are
reading. That gives a document pile with native, non-contrived disagreement.

The conflicts below are planted deliberately and are documented in MANIFEST.md.
That file is ground truth: a system that reads this corpus should find them, and
should find nothing that is not on the list.

Run:  python generate.py
"""

from __future__ import annotations

import csv
import os
import random
import subprocess
from dataclasses import dataclass, field

OUT = "out"
SEED = 20260805

INSURED = "Meridian Cold Chain Logistics, Inc."
INSURED_SHORT = "Meridian Cold Chain"
CARRIER = "Kestrel Mutual Insurance Company"
CARRIER_SHORT = "Kestrel Mutual"
BROKER = "Ardent Risk Partners"
FEIN = "88-0143927"

COVERAGES = {
    "AL": "Auto Liability",
    "APD": "Auto Physical Damage",
    "CARGO": "Motor Truck Cargo",
    "WC": "Workers Compensation",
    "GL": "General Liability",
    "PROP": "Property",
}

POLICIES = {
    2021: ("KM-CA-2021-88417", "2021-04-01", "2022-04-01", 412_000),
    2022: ("KM-CA-2022-88417", "2022-04-01", "2023-04-01", 448_500),
    2023: ("KM-CA-2023-88417", "2023-04-01", "2024-04-01", 501_200),
    2024: ("KM-CA-2024-88417", "2024-04-01", "2025-04-01", 566_900),
}


@dataclass
class Claim:
    claim_no: str
    year: int
    coverage: str
    date_of_loss: str
    date_reported: str
    description: str
    status: str            # Open | Closed | Reopened
    paid: float
    reserve: float
    claimant: str = "Third party"
    note: str = ""
    # Values as they appeared in the ORIGINAL run, when a later reissue differs
    original: dict = field(default_factory=dict)

    @property
    def incurred(self) -> float:
        return round(self.paid + self.reserve, 2)


# ---------------------------------------------------------------------------
# Claims that carry a planted conflict. Explicit, never random.
# ---------------------------------------------------------------------------

ANCHOR_CLAIMS: list[Claim] = [
    # C1 reserve development: modest at first issue, severe two years later
    Claim("KM-2023-0417", 2023, "AL", "2023-11-08", "2023-11-09",
          "Tractor-trailer jackknife on I-80, two vehicles involved, "
          "bodily injury alleged by both occupants of the second vehicle.",
          "Open", 12_400.00, 170_000.00, "Third party",
          note="Severity reassessed after plaintiff filed suit.",
          original={"paid": 8_150.00, "reserve": 36_850.00, "status": "Open"}),

    # C2 status flip: closed on the run, reopened per the adjuster note
    Claim("KM-2022-0311", 2022, "WC", "2022-09-19", "2022-09-19",
          "Warehouse associate lumbar strain, pallet jack incident.",
          "Closed", 41_280.00, 0.00, "Employee",
          note="Claimant returned with recurrence; see adjuster note.",
          original={}),

    # C3 late-reported claim: absent from the original 2023 run entirely
    Claim("KM-2023-0588", 2023, "CARGO", "2024-02-27", "2024-06-14",
          "Refrigeration unit failure in transit, full load of pharmaceuticals "
          "condemned on arrival.",
          "Open", 0.00, 224_500.00, "Shipper",
          note="Reported after the original loss run was issued.",
          original={"absent": True}),

    # C4 date of loss falls outside the policy period it is filed under
    Claim("KM-2022-0402", 2022, "GL", "2023-04-11", "2023-04-19",
          "Slip and fall, visitor at the Fresno cross-dock.",
          "Closed", 18_900.00, 0.00, "Third party",
          note="Date of loss sits after the 2022 policy expiry."),

    # C5 same event carried under two claim numbers
    Claim("KM-2021-0219", 2021, "APD", "2021-08-03", "2021-08-04",
          "Reefer trailer sidewall damage, low bridge strike, Route 6.",
          "Closed", 27_450.00, 0.00, "First party"),
    Claim("KM-2021-0224", 2021, "APD", "2021-08-03", "2021-08-11",
          "Trailer damage from bridge strike on Route 6 - unit 4471.",
          "Closed", 27_450.00, 0.00, "First party",
          note="Appears to duplicate KM-2021-0219."),

    # C6 large claim with no adjuster note on file
    Claim("KM-2024-0106", 2024, "AL", "2024-06-22", "2024-06-23",
          "Rear-end collision, company tractor, claimant hospitalised.",
          "Open", 31_000.00, 118_000.00, "Third party"),

    # C7 long-open claim, zero paid against a standing reserve
    Claim("KM-2021-0333", 2021, "GL", "2021-12-02", "2021-12-15",
          "Alleged product contamination, retailer recall costs claimed.",
          "Open", 0.00, 96_000.00, "Third party",
          note="No payment activity since inception."),
]

FILLER_DESCRIPTIONS = {
    "AL": ["Minor collision in yard, no injuries",
           "Sideswipe during lane change, property damage only",
           "Backing incident at customer dock"],
    "APD": ["Windshield replacement, road debris",
            "Tractor door damage, parking lot",
            "Tyre blowout, wheel arch damage"],
    "CARGO": ["Partial load spoilage, temperature excursion",
              "Carton crush damage in transit",
              "Short delivery, three pallets unaccounted"],
    "WC": ["Hand laceration, box cutter",
           "Slip on wet dock plate, contusion",
           "Repetitive strain, order picking"],
    "GL": ["Damage to customer dock leveller",
           "Minor property damage at delivery site"],
    "PROP": ["Roof leak, Bakersfield warehouse",
             "Freezer motor burnout, electrical surge"],
}


def build_filler(rng: random.Random) -> list[Claim]:
    claims: list[Claim] = []
    per_year = {2021: 9, 2022: 10, 2023: 8, 2024: 6}
    for year, n in per_year.items():
        _, start, _, _ = POLICIES[year]
        for i in range(n):
            cov = rng.choice(list(FILLER_DESCRIPTIONS))
            month = rng.randint(4, 12) if rng.random() < 0.7 else rng.randint(1, 3)
            y = year if month >= 4 else year + 1
            dol = f"{y}-{month:02d}-{rng.randint(1, 28):02d}"
            lag = rng.randint(0, 9)
            rep_day = min(28, int(dol[-2:]) + lag)
            drep = f"{dol[:-2]}{rep_day:02d}"
            closed = rng.random() < (0.9 if year <= 2022 else 0.55)
            size = rng.choice([1, 1, 1, 2, 2, 3])
            base = {1: (400, 4_000), 2: (4_000, 22_000), 3: (22_000, 65_000)}[size]
            total = round(rng.uniform(*base), 2)
            paid = total if closed else round(total * rng.uniform(0.05, 0.45), 2)
            reserve = 0.0 if closed else round(total - paid, 2)
            claims.append(Claim(
                claim_no=f"KM-{year}-{200 + i * 7 + rng.randint(0, 4):04d}",
                year=year, coverage=cov, date_of_loss=dol, date_reported=drep,
                description=rng.choice(FILLER_DESCRIPTIONS[cov]),
                status="Closed" if closed else "Open",
                paid=paid, reserve=reserve,
                claimant="Employee" if cov == "WC" else
                        ("First party" if cov in ("APD", "PROP") else "Third party"),
            ))
    return claims


# ---------------------------------------------------------------------------
# Loss run writers
# ---------------------------------------------------------------------------

HEADER = ["Claim Number", "Policy Number", "Policy Year", "Coverage",
          "Date of Loss", "Date Reported", "Status", "Claimant",
          "Paid", "Reserve", "Incurred", "Description"]


def rows_for(claims: list[Claim], year: int, reissue: bool) -> list[list]:
    pol = POLICIES[year][0]
    out = []
    for c in sorted((c for c in claims if c.year == year),
                    key=lambda c: c.date_of_loss):
        if not reissue and c.original.get("absent"):
            continue
        paid = c.paid
        reserve = c.reserve
        status = c.status
        if not reissue and c.original:
            paid = c.original.get("paid", paid)
            reserve = c.original.get("reserve", reserve)
            status = c.original.get("status", status)
        out.append([
            c.claim_no, pol, year, COVERAGES[c.coverage], c.date_of_loss,
            c.date_reported, status, c.claimant,
            f"{paid:,.2f}", f"{reserve:,.2f}", f"{paid + reserve:,.2f}",
            c.description,
        ])
    return out


def write_loss_run(path: str, year: int, claims: list[Claim], issued: str,
                   reissue: bool, footer_error: float = 0.0) -> None:
    _, start, end, premium = POLICIES[year]
    rows = rows_for(claims, year, reissue)
    total = sum(float(r[10].replace(",", "")) for r in rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"{CARRIER} - Loss Run Report"])
        w.writerow([f"Insured: {INSURED}"])
        w.writerow([f"FEIN: {FEIN}"])
        w.writerow([f"Policy Period: {start} to {end}"])
        w.writerow([f"Valuation Date: {issued}"])
        w.writerow([f"Report Type: {'REISSUE - supersedes prior' if reissue else 'Original'}"])
        w.writerow([])
        w.writerow(HEADER)
        w.writerows(rows)
        w.writerow([])
        # Real loss runs frequently carry a footer total that does not equal
        # the sum of the rows above it. One year here reproduces that.
        w.writerow(["", "", "", "", "", "", "", "TOTAL INCURRED",
                    "", "", f"{total + footer_error:,.2f}", ""])
        w.writerow(["", "", "", "", "", "", "", "CLAIM COUNT",
                    "", "", len(rows), ""])
        w.writerow(["", "", "", "", "", "", "", "EARNED PREMIUM",
                    "", "", f"{premium:,.2f}", ""])


# ---------------------------------------------------------------------------
# DOCX writers
# ---------------------------------------------------------------------------

def docx(path: str, blocks: list[tuple[str, str]]) -> None:
    from docx import Document
    from docx.shared import Pt

    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(10.5)
    for kind, text in blocks:
        if kind == "h1":
            d.add_heading(text, level=1)
        elif kind == "h2":
            d.add_heading(text, level=2)
        elif kind == "b":
            p = d.add_paragraph()
            p.add_run(text).bold = True
        else:
            d.add_paragraph(text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d.save(path)


def write_adjuster_notes() -> None:
    docx(f"{OUT}/adjuster-notes/KM-2023-0417-adjuster-note.docx", [
        ("h1", "Claim file note"),
        ("b", f"Claim: KM-2023-0417   Insured: {INSURED_SHORT}   Coverage: Auto Liability"),
        ("p", "Date of note: 2025-09-30. Adjuster: R. Okonjo, Kestrel Mutual."),
        ("h2", "Position"),
        ("p", "Reserve increased to $170,000 following receipt of the plaintiff's "
              "demand and the treating physician's report. The earlier reserve of "
              "$36,850 was set before suit was filed and reflected an assumption "
              "of soft-tissue injury only. That assumption no longer holds."),
        ("p", "Liability is not seriously in dispute. The insured unit crossed the "
              "centre line. Exposure is a question of damages, not fault."),
        ("h2", "Reserve history"),
        ("p", "2023-11-15: $36,850 initial. 2024-08-02: $58,000. "
              "2025-09-30: $170,000 current."),
        ("h2", "Next steps"),
        ("p", "Mediation scheduled Q2 2026. Recommend authority to $200,000."),
    ])

    docx(f"{OUT}/adjuster-notes/KM-2022-0311-adjuster-note.docx", [
        ("h1", "Claim file note"),
        ("b", f"Claim: KM-2022-0311   Insured: {INSURED_SHORT}   Coverage: Workers Compensation"),
        ("p", "Date of note: 2024-03-12. Adjuster: L. Haddad, Kestrel Mutual."),
        ("h2", "Position"),
        ("p", "This file was closed on 2023-06-30 after the claimant returned to "
              "full duty. The claimant has since reported a recurrence of the same "
              "lumbar symptoms and has been placed on modified duty as of "
              "2024-02-19. The file is reopened."),
        ("p", "Note that the loss run issued in January 2024 shows this claim as "
              "closed. That was correct at its valuation date and is no longer "
              "correct."),
        ("h2", "Revised position"),
        ("p", "Reserve re-established at $34,000 for continued indemnity and "
              "medical. Paid to date remains $41,280."),
    ])

    docx(f"{OUT}/adjuster-notes/KM-2023-0588-adjuster-note.docx", [
        ("h1", "Claim file note"),
        ("b", f"Claim: KM-2023-0588   Insured: {INSURED_SHORT}   Coverage: Motor Truck Cargo"),
        ("p", "Date of note: 2024-07-01. Adjuster: R. Okonjo, Kestrel Mutual."),
        ("h2", "Position"),
        ("p", "Temperature excursion on a pharmaceutical load. The consignee "
              "condemned the entire shipment on arrival. Salvage value is nil "
              "because the product cannot re-enter the cold chain once excursion "
              "is documented."),
        ("p", "Date of loss 2024-02-27 falls within the 2023 policy period. The "
              "claim was reported on 2024-06-14, after the original loss run for "
              "that year had been issued, and therefore does not appear on it."),
        ("h2", "Reserve"),
        ("p", "$224,500, being the invoiced value of the load. Subrogation against "
              "the reefer unit manufacturer is under review."),
    ])


def write_application() -> None:
    docx(f"{OUT}/application/meridian-renewal-application-2026.docx", [
        ("h1", "Commercial insurance renewal application"),
        ("b", f"Applicant: {INSURED}"),
        ("p", f"FEIN: {FEIN}. Broker of record: {BROKER}. "
              "Proposed effective date: 2026-04-01."),
        ("h2", "Operations"),
        ("p", "Refrigerated truckload and less-than-truckload carriage, with three "
              "cross-dock facilities in California and one in Nevada. Power units: "
              "64. Refrigerated trailers: 91. Employees: 212."),
        ("h2", "Loss history - applicant statement"),
        ("p", "The applicant reports 3 claims exceeding $50,000 in the last five "
              "policy years, and confirms that no claim currently open exceeds "
              "$100,000 in incurred value."),
        ("p", "The applicant further reports that all claims from policy years "
              "2021 and 2022 are closed."),
        ("h2", "Prior carrier"),
        ("p", f"{CARRIER}, continuously since 2021-04-01. No lapse in coverage. "
              "No policy has been cancelled or non-renewed."),
        ("h2", "Declaration"),
        ("p", "The undersigned declares the statements above to be true to the "
              "best of their knowledge. Signed: J. Ferreira, Chief Financial "
              "Officer. Date: 2026-01-22."),
    ])


def write_broker_email() -> None:
    docx(f"{OUT}/correspondence/ardent-cover-note-2026-01-28.docx", [
        ("h1", "Submission cover note"),
        ("b", f"From: {BROKER}   To: Underwriting   Date: 2026-01-28"),
        ("p", f"Please find attached the renewal submission for {INSURED_SHORT}, "
              "effective 2026-04-01."),
        ("p", "Enclosed: loss runs for policy years 2021 through 2024 valued "
              "January 2026, a reissued 2023 loss run, three adjuster notes, and "
              "the signed application."),
        ("p", "Two points the underwriter should have in front of them. First, the "
              "2023 loss run has been reissued and the incurred figures differ "
              "materially from the version circulated in 2024; the reissue is the "
              "one to work from. Second, the client's application was prepared in "
              "December before the reissued runs arrived, so the loss summary in "
              "it reflects the earlier figures."),
        ("p", "The client is seeking terms at or below expiring. Happy to discuss."),
        ("p", "Regards, D. Whitfield, Account Executive, " + BROKER),
    ])


def write_checklist() -> None:
    docx(f"{OUT}/rules/underwriting-checklist.docx", [
        ("h1", "Casualty underwriting checklist - motor carrier accounts"),
        ("p", "Applied to every submission before a coverage decision. Each rule "
              "produces a finding or an explicit pass."),
        ("h2", "R1 - Adjuster note required on severity claims"),
        ("p", "Any claim with incurred value of $100,000 or more must have an "
              "adjuster note in the file. A severity claim without a note cannot "
              "be evaluated and must be referred."),
        ("h2", "R2 - Stale open claims"),
        ("p", "Any claim open more than 36 months from date of loss is flagged for "
              "reserve adequacy review."),
        ("h2", "R3 - Loss ratio referral"),
        ("p", "Any policy year with incurred losses exceeding 60% of earned "
              "premium is referred to a senior underwriter."),
        ("h2", "R4 - Policy period integrity"),
        ("p", "A claim whose date of loss falls outside the policy period it is "
              "reported under must be queried with the carrier before the figures "
              "are relied on."),
        ("h2", "R5 - Application consistency"),
        ("p", "The claim counts and severity thresholds stated on the application "
              "must agree with the loss runs. Any disagreement is recorded and put "
              "to the broker."),
        ("h2", "R6 - Dormant reserves"),
        ("p", "A claim with zero paid and a non-zero reserve, open more than 24 "
              "months, is flagged for reserve review."),
        ("h2", "R7 - Duplicate claims"),
        ("p", "The same loss event must not be carried under two claim numbers. "
              "Suspected duplicates are queried before totals are relied on."),
        ("h2", "R8 - Loss run internal consistency"),
        ("p", "The total incurred stated on a loss run must equal the sum of its "
              "claim rows. A discrepancy is recorded against the document."),
    ])


def write_pdf_loss_run(year: int, claims: list[Claim], issued: str,
                       out_dir: str) -> None:
    """The same policy year as a formatted PDF report.

    Carriers issue loss runs both ways. Converting the wide CSV directly gives
    a truncated three-column page, which is not what a carrier PDF looks like;
    this builds a proper landscape table with the columns an underwriter reads,
    then renders it.
    """
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Pt, Inches

    _, start, end, premium = POLICIES[year]
    rows = rows_for(claims, year, reissue=False)

    d = Document()
    sec = d.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    sec.left_margin = sec.right_margin = Inches(0.5)
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(8)

    d.add_paragraph(f"{CARRIER} - Loss Run Report").runs[0].bold = True
    for line in (f"Insured: {INSURED}", f"FEIN: {FEIN}",
                 f"Policy Period: {start} to {end}",
                 f"Valuation Date: {issued}", "Report Type: Original"):
        d.add_paragraph(line)

    cols = ["Claim Number", "Coverage", "Date of Loss", "Date Reported",
            "Status", "Paid", "Reserve", "Incurred"]
    idx = [0, 3, 4, 5, 6, 8, 9, 10]
    t = d.add_table(rows=1, cols=len(cols))
    t.style = "Table Grid"
    for i, c in enumerate(cols):
        cell = t.rows[0].cells[i]
        cell.text = c
        cell.paragraphs[0].runs[0].bold = True
    for r in rows:
        cells = t.add_row().cells
        for i, j in enumerate(idx):
            cells[i].text = str(r[j])

    total = sum(float(r[10].replace(",", "")) for r in rows)
    d.add_paragraph("")
    d.add_paragraph(f"TOTAL INCURRED: {total:,.2f}")
    d.add_paragraph(f"CLAIM COUNT: {len(rows)}")
    d.add_paragraph(f"EARNED PREMIUM: {premium:,.2f}")

    os.makedirs(out_dir, exist_ok=True)
    docx_path = os.path.join(out_dir, f"loss-run-{year}-valued-{issued[:7]}.docx")
    d.save(docx_path)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir,
         docx_path],
        check=False, capture_output=True, timeout=180,
    )
    os.remove(docx_path)


def main() -> None:
    rng = random.Random(SEED)
    claims = ANCHOR_CLAIMS + build_filler(rng)

    write_loss_run(f"{OUT}/loss-runs/loss-run-2021-valued-2024-01.csv",
                   2021, claims, "2024-01-15", reissue=False)
    write_loss_run(f"{OUT}/loss-runs/loss-run-2022-valued-2024-01.csv",
                   2022, claims, "2024-01-15", reissue=False)
    write_loss_run(f"{OUT}/loss-runs/loss-run-2023-valued-2024-01-ORIGINAL.csv",
                   2023, claims, "2024-01-15", reissue=False,
                   footer_error=1_500.00)
    write_loss_run(f"{OUT}/loss-runs/loss-run-2023-valued-2026-01-REISSUE.csv",
                   2023, claims, "2026-01-09", reissue=True)
    write_loss_run(f"{OUT}/loss-runs/loss-run-2024-valued-2026-01.csv",
                   2024, claims, "2026-01-09", reissue=True)

    write_adjuster_notes()
    write_application()
    write_broker_email()
    write_checklist()
    write_pdf_loss_run(2022, claims, "2024-01-15", f"{OUT}/loss-runs")

    print(f"corpus written to {OUT}/  ({len(claims)} claims across 4 policy years)")


if __name__ == "__main__":
    main()
