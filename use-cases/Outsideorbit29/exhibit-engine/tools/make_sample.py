"""Regenerate the sample brief + evidence pile (all synthetic, public-safe).

The sample is a made-up spousal-visa support filing for "Reyansh Sharma" and
"Meera Sharma". Every name, date, address and number here is fictitious; this is
demonstration data for the exhibit indexer, not real confidential material.

Run:  python tools/make_sample.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(out: Path) -> None:
    brief_dir = out / "brief"
    evidence_dir = out / "evidence"
    brief_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    (brief_dir / "supporting_brief.md").write_text(BRIEF, encoding="utf-8")

    _write(evidence_dir / "passport.pdf", _passport_pdf())
    _write_docx(evidence_dir / "marriage_certificate.docx", MARRIAGE_CERT)
    _write(evidence_dir / "joint_lease.txt", JOINT_LEASE)
    _write(evidence_dir / "joint_bank_statements.txt", BANK_STATEMENTS)
    _write(evidence_dir / "travel_itinerary.md", TRAVEL_ITINERARY)
    _write(evidence_dir / "wedding_photos.md", WEDDING_PHOTOS)
    _write(evidence_dir / "support_letters.md", SUPPORT_LETTERS)
    _write(evidence_dir / "joint_tax_return.txt", JOINT_TAX_RETURN)

    print(f"sample generated under {out}")


def _write(path: Path, content: bytes | str) -> None:
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def _write_docx(path: Path, text: str) -> None:
    import docx

    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    d.save(str(path))


def _passport_pdf() -> bytes:
    """A one-page synthetic passport summary, produced with fpdf2."""
    from fpdf import FPDF

    pdf = FPDF(format="letter")
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    lines = [
        "REPUBLIC OF INDIA  PASSPORT (SAMPLE - NOT A REAL PASSPORT)",
        "Type: P",
        "Country: IND",
        "Passport No.: S4827371",
        "Surname: SHARMA",
        "Given Names: REYANSH KUMAR",
        "Nationality: INDIAN",
        "Date of Birth: 14 MAR 1994",
        "Place of Birth: JAIPUR, INDIA",
        "Date of Issue: 02 JAN 2023",
        "Date of Expiry: 01 JAN 2033",
    ]
    for line in lines:
        pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
    path = Path("_tmp_passport.pdf")
    pdf.output(str(path))
    data = path.read_bytes()
    path.unlink()
    return data


BRIEF = """# Supporting Brief for Spousal Visa Application

## I. Introduction

This brief supports the spousal visa application of Reyansh Sharma, an Indian
national, whose wife Meera Sharma resides in the United States. The applicant
and his spouse request that the petition be granted on the evidence of a bona
fide marriage and a shared, continuing life together.

## II. Identity and nationality

The applicant's identity and Indian nationality are established by his
passport, which is submitted as the first exhibit.

## III. Genuine marriage

The couple married on 12 December 2022 in Jaipur, India, in a ceremony attended
by both families. The marriage is genuine and was not entered into for the
purpose of evading immigration law. The marriage certificate records the
marriage and both names.

## IV. Cohabitation and shared finances

The couple has lived together under one roof since the marriage. They maintain a
joint lease on their residence, and their finances are intermingled through joint
bank accounts and a joint tax return filed for the most recent tax year. These
records show a pattern of shared responsibility.

## V. Continued relationship

Since the marriage, the couple has travelled together on several occasions, and
kept extensive records of their shared life, including photographs from their
wedding and subsequent family gatherings. Letters from family and friends attest
to the ongoing, genuine nature of the relationship.

## VI. Conclusion

For the foregoing reasons, the applicant respectfully requests that the petition
be approved so that the couple may continue their life together in the United
States.
"""

MARRIAGE_CERT = """MARRIAGE CERTIFICATE (SAMPLE — NOT A REAL DOCUMENT)

This is to certify that REYANSH KUMAR SHARMA, son of Mr. Vikram Sharma,
and MEERA AGGARWAL SHARMA, daughter of Mr. Devendra Aggarwal, were married
on the twelfth day of December, two thousand twenty-two, at Jaipur, India.

Registration No.: 2022/BR/4412
Date of Registration: 15 December 2022
Officiating Registrar: A. K. Verma
"""

JOINT_LEASE = """JOINT LEASE AGREEMENT (SAMPLE)

This lease is entered into between Green Oak Properties, LLC and the tenants
Meera Sharma and Reyansh Sharma for the residence at 214 Birchwood Lane,
Austin, Texas 78745.

Term: 1 March 2025 to 28 February 2026
Monthly Rent: $1,750
Both tenants are jointly and severally liable for the full rent.
Signed by both tenants on 20 February 2025.
"""

BANK_STATEMENTS = """JOINT BANK STATEMENT (SAMPLE)
Account: Sharma-SHARMA, Joint Checking, XXXXXX4821
Bank: First National Bank of Austin
Period: January 2026 - June 2026

1 Jan 2026  Opening balance                $4,120.00
15 Jan 2026 Direct deposit (Meera)          $3,400.00
20 Jan 2026 Rent transfer                   -$1,750.00
14 Feb 2026 Direct deposit (Meera)          $3,400.00
20 Feb 2026 Rent transfer                   -$1,750.00
5 Mar 2026  Transfer (Reyansh)              $1,900.00
20 Mar 2026 Rent transfer                   -$1,750.00
10 Apr 2026 Direct deposit (Meera)          $3,400.00
20 Apr 2026 Rent transfer                   -$1,750.00
2 May 2026  Transfer (Reyansh)              $1,900.00
20 May 2026 Rent transfer                   -$1,750.00
15 Jun 2026 Direct deposit (Meera)          $3,400.00
20 Jun 2026 Rent transfer                   -$1,750.00
30 Jun 2026 Closing balance                 $6,520.00
"""

TRAVEL_ITINERARY = """# Travel Itinerary (SAMPLE)

1. 18 December 2022 — Jaipur to Austin. Bridal party travel: Meera Sharma
   returns to the United States after the wedding. Reyansh Sharma remains in
   India pending visa processing.
2. 09 August 2024 — Austin to Jaipur. Reyansh Sharma visits Meera's family.
3. 16 August 2024 — Jaipur to Delhi. Couple travels together before Meera's
   departure.
4. 05 January 2026 — Austin to New Delhi. Meera Sharma travels to India to
   visit Reyansh Sharma.
5. 25 January 2026 — New Delhi to Austin. The couple returns to the United
   States together.
"""

WEDDING_PHOTOS = """# Wedding and Family Photographs (SAMPLE — DESCRIPTIONS ONLY)

photo-01.jpg  — Exchange of rings at the wedding ceremony, Jaipur, 12 Dec 2022.
photo-02.jpg  — The couple with both families at the reception.
photo-03.jpg  — Bride and groom signing the marriage register.
photo-04.jpg  — Family dinner at the Sharma residence, August 2024.
photo-05.jpg  — The couple at the airport, January 2026, returning together.
"""

SUPPORT_LETTERS = """# Letters of Support (SAMPLE)

Letter from Vikram Sharma (father of the applicant):
"Reyansh and Meera have been married since December 2022. Their wedding was a
joyous occasion attended by both families. They are devoted to each other."

Letter from Devendra Aggarwal (father of the spouse):
"My daughter Meera married Reyansh in a ceremony we fully supported. I have
seen them build a home together and they are genuinely happy."

Letter from Kavita Nair (family friend):
"I have known the couple since their wedding. They travel together, celebrate
holidays with family, and clearly love one another."
"""

JOINT_TAX_RETURN = """JOINT FEDERAL TAX RETURN (SAMPLE)
Filing Status: Married Filing Jointly
Taxpayers: Meera Sharma and Reyansh Sharma
Tax Year: 2025
Wages (Meera):  $61,400.00
Wages (Reyansh): $38,900.00
Total Income:   $100,300.00
Filing jointly, both spouses signed the return on 12 April 2026.
"""


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "sample"
    main(out)
