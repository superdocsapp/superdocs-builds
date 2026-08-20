from pathlib import Path

from docx import Document


OUTPUT_DIR = Path(__file__).parent
OUTPUT_PATH = OUTPUT_DIR / "sample_resume.docx"


def build_resume() -> None:
    document = Document()

    document.add_heading("Alex Morgan", level=0)
    document.add_paragraph(
        "Data Analyst | Python | SQL | Power BI"
    )

    document.add_heading("Experience", level=1)

    document.add_heading(
        "Operations Data Analyst — Example Industries",
        level=2,
    )
    document.add_paragraph(
        "January 2024 — Present"
    )

    bullets = [
        "Automated invoice processing using Python.",
        "Processed 500 invoices per month using Python.",
        "Built Power BI dashboards for operational reporting.",
        "Was responsible for processing 1,200 records per week.",
        "Reduced report preparation time from 3 hours to 45 minutes.",
    ]

    for bullet in bullets:
        paragraph = document.add_paragraph(
            style="List Bullet"
        )
        paragraph.add_run(bullet)

    document.add_heading("Skills", level=1)
    document.add_paragraph(
        "Python, SQL, Power BI, Excel"
    )

    document.save(OUTPUT_PATH)
    print(f"Created: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_resume()