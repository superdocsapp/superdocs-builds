#!/usr/bin/env python3
"""Generate the synthetic Northstar (A) vs Helios (B) HR policy estates."""

from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "sample_data"


def _style_doc(doc):
    section = doc.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)


def _add_title(doc, title, company):
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    meta = doc.add_paragraph()
    run = meta.add_run(f"{company}  ·  Employee Handbook  ·  Effective 1 January 2026")
    run.italic = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)


def _h(doc, text):
    doc.add_heading(text, level=1)


def _p(doc, text):
    doc.add_paragraph(text)


def _bullets(doc, items):
    for item in items:
        doc.add_paragraph(item, style="List Number")


def write_docx(path, title, company, sections):
    doc = Document()
    _style_doc(doc)
    _add_title(doc, title, company)
    for heading, body in sections:
        _h(doc, heading)
        if isinstance(body, list):
            _bullets(doc, body)
        else:
            _p(doc, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    print(f"  wrote {path.relative_to(ROOT)}")


def build_company_a():
    company = "Northstar Analytics"
    out = SAMPLE / "company_a"

    write_docx(
        out / "remote_work_policy.docx",
        "Remote Work Policy",
        company,
        [
            (
                "Purpose",
                "This policy describes how Northstar employees may work away from a company office. "
                "It applies to all full-time and part-time employees in the United States.",
            ),
            (
                "Where employees may work",
                [
                    "Employees may work fully remotely from any location in the United States.",
                    "There are no required in-office days.",
                    "Employees must be reachable on Slack during core hours of 10:00 a.m. to 3:00 p.m. in their local time zone.",
                ],
            ),
            (
                "Equipment",
                "Northstar provides an annual home-office stipend of $500. Employees purchase their own peripherals; "
                "laptops remain company property.",
            ),
            (
                "All-hands meetings",
                "Occasional all-hands gatherings may be held in person. Northstar will give at least 30 days' notice. "
                "In-person attendance is optional; a video link will always be provided.",
            ),
        ],
    )

    write_docx(
        out / "pto_policy.docx",
        "Paid Time Off Policy",
        company,
        [
            (
                "Accrual",
                [
                    "Full-time employees accrue 15 days of paid time off per calendar year.",
                    "Unused PTO expires on December 31 and is not paid out except as required by law.",
                    "PTO does not accrue during unpaid leave.",
                ],
            ),
            (
                "Notice",
                "Employees must provide 3 business days' notice for PTO requests. Requests submitted with less notice "
                "may be denied except for illness or emergency.",
            ),
            (
                "New hires",
                "PTO in the first 90 days of employment requires VP approval.",
            ),
            (
                "Sick leave",
                "Sick leave is a separate bank of 5 days per year. No advance notice is required for illness. "
                "Unused sick leave does not carry over.",
            ),
        ],
    )

    write_docx(
        out / "expense_policy.docx",
        "Expense Policy",
        company,
        [
            (
                "Eligible costs",
                "Employees may expense reasonable, necessary business costs incurred while performing their role, "
                "including travel, client meals, and shipping.",
            ),
            (
                "Receipts and approval",
                [
                    "Receipts are required for any expense over $50.",
                    "Manager approval is required for expenses over $200.",
                    "Expenses must be submitted within 30 days of the transaction date.",
                ],
            ),
            (
                "Meals and alcohol",
                "Alcohol is reimbursable up to $40 per client meal. Internal team meals without a client present "
                "are not reimbursable.",
            ),
            (
                "How to submit",
                "Submit claims through the finance portal with the merchant, date, amount, business purpose, "
                "and receipt image attached.",
            ),
        ],
    )

    write_docx(
        out / "code_of_conduct.docx",
        "Code of Conduct",
        company,
        [
            (
                "Respectful workplace",
                "Harassment, discrimination, and retaliation are prohibited. Employees who experience or witness "
                "prohibited conduct must report it to HR or to the anonymous hotline.",
            ),
            (
                "Gifts and vendors",
                "Gifts from vendors may not exceed $25 in fair market value in any calendar year. Cash and cash "
                "equivalents are never permitted.",
            ),
            (
                "Social media",
                [
                    "Employees must not post confidential company information on social media.",
                    "Personal social media that identifies the employee as a Northstar worker must include a disclaimer "
                    "that views are their own.",
                ],
            ),
            (
                "Reporting-line relationships",
                "Romantic relationships in a reporting line must be disclosed to HR immediately. Failure to disclose "
                "is grounds for corrective action.",
            ),
        ],
    )

    write_docx(
        out / "termination_policy.docx",
        "Termination Policy",
        company,
        [
            (
                "Resignation notice",
                "Employees who resign must give at least 2 weeks' written notice to their manager and to HR.",
            ),
            (
                "Garden leave",
                "Senior employees (Director and above) serve a 4-week garden leave after notice. During garden leave "
                "the employee remains employed, must not work for another employer, and must remain available for "
                "knowledge transfer.",
            ),
            (
                "Severance",
                "Northstar does not publish a standard severance formula. Any severance is at company discretion "
                "and requires a signed release.",
            ),
            (
                "Final pay and property",
                [
                    "Final pay includes accrued unused PTO, paid on the next regular payroll.",
                    "Company property must be returned on the last day on site.",
                ],
            ),
        ],
    )


def build_company_b():
    company = "Helios Robotics"
    out = SAMPLE / "company_b"

    write_docx(
        out / "flexible_working.docx",
        "Flexible Working Guidelines",
        company,
        [
            (
                "Purpose",
                "These guidelines explain how Helios balances office collaboration with remote focus time. "
                "They apply to all employees assigned to a Helios office.",
            ),
            (
                "Office attendance",
                [
                    "Employees must work from a company office on Tuesday, Wednesday, and Thursday.",
                    "Monday and Friday may be remote.",
                    "Core hours are 9:00 a.m. to 5:00 p.m. in the office time zone.",
                ],
            ),
            (
                "Equipment",
                "Helios does not pay a home-office stipend. Desks, monitors, and peripherals are provided on site. "
                "Laptops remain company property.",
            ),
            (
                "All-hands meetings",
                "Quarterly all-hands attendance is mandatory and in-person. Exceptions require VP approval at least "
                "14 days in advance.",
            ),
        ],
    )

    write_docx(
        out / "time_off_policy.docx",
        "Time Off Policy",
        company,
        [
            (
                "Unlimited time off",
                [
                    "Helios offers unlimited paid time off. There is no accrual and no year-end expiration.",
                    "Sick time is included in unlimited PTO; there is no separate sick bank.",
                    "Managers may deny time off that would drop team coverage below 50%.",
                ],
            ),
            (
                "Notice",
                "Employees must provide 30 days' notice for absences exceeding 5 consecutive days. Shorter absences "
                "require notice as soon as practicable and at least 1 business day where possible.",
            ),
            (
                "New hires",
                "Time off during the first 90 days is not permitted except for illness or legally protected leave.",
            ),
        ],
    )

    write_docx(
        out / "reimbursement_guidelines.docx",
        "Reimbursement Guidelines",
        company,
        [
            (
                "Eligible costs",
                "Team members may claim reasonable out-of-pocket business costs, including travel, client meals, "
                "and shipping incurred while performing their role.",
            ),
            (
                "Receipts and approval",
                [
                    "Itemized receipts are required for expenses over $75.",
                    "Pre-approval from a director is required above $250.",
                    "Claims must be filed within 45 days of the spend date.",
                ],
            ),
            (
                "Meals and alcohol",
                "Alcohol is reimbursable up to $40 per client meal. Internal team meals without a client present "
                "are not reimbursable.",
            ),
            (
                "How to submit",
                "File claims in the Helios expense tool with merchant, date, amount, business purpose, and a "
                "receipt image.",
            ),
        ],
    )

    write_docx(
        out / "workplace_conduct.docx",
        "Workplace Conduct",
        company,
        [
            (
                "Respectful workplace",
                "Harassment, discrimination, and retaliation are prohibited. Employees who experience or witness "
                "prohibited conduct must report it to People Operations or to the anonymous hotline.",
            ),
            (
                "Gifts and vendors",
                "Gifts from vendors may not exceed $75 in fair market value in any calendar year. Cash and cash "
                "equivalents are never permitted.",
            ),
            (
                "Reporting-line relationships",
                "Romantic relationships in a reporting line must be disclosed to People Operations immediately. "
                "Failure to disclose is grounds for corrective action.",
            ),
        ],
    )

    write_docx(
        out / "separation_policy.docx",
        "Separation Policy",
        company,
        [
            (
                "At-will employment",
                "Helios is an at-will employer. Employees are not required to give notice before leaving. "
                "Helios may end employment at any time, with or without cause, subject to applicable law.",
            ),
            (
                "Garden leave",
                "There is no garden leave period at Helios. Access to systems is revoked on the separation date.",
            ),
            (
                "Severance",
                "Severance is 1 week of base pay per completed year of service, capped at 12 weeks, for involuntary "
                "termination without cause. Severance requires a signed release.",
            ),
            (
                "Final pay and property",
                [
                    "Unused PTO is not paid out on separation except as required by law.",
                    "Company property must be returned within 5 business days of separation.",
                ],
            ),
        ],
    )


def main():
    print("Generating sample HR estates...")
    build_company_a()
    build_company_b()
    print("Done.")


if __name__ == "__main__":
    main()
