#!/usr/bin/env python3
"""DocTask Demo Seeder Script.

Seeds the development database with realistic synthetic construction datasets:
1. Scenario A: Section 09 65 00 Resilient Flooring (SUB-001) with comparison findings (Thickness deviation, Fire match, Warranty match).
2. Scenario B: Section 08 11 13 Hollow Metal Doors and Frames (SUB-002) with fire door findings.
3. Overdue Example: Section 05 12 00 Structural Steel (SUB-003) past due date.
"""

from datetime import date, timedelta
import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.finding import Finding
from app.models.submittal import Submittal
from app.services.register import generate_register
from app.services.comparison import compare_flooring, compare_fire_doors


def seed_demo():
    print("Initializing DocTask database...")
    init_db()
    db = SessionLocal()

    project_id = "BROD-2026"
    print(f"Seeding project '{project_id}'...")

    requirements = [
        {
            "title": "Flooring Product Data",
            "description": "Manufacturer technical sheet for resilient vinyl flooring",
            "specification_section": "09 65 00",
            "required_by": "Flooring Subcontractor Ltd",
            "required_form": "Product data / technical sheet",
            "source_evidence": "Section 09 65 00 §2.01: Minimum thickness 3.0mm, Class A flame spread, 10yr warranty.",
            "specification_revision": "Rev 02",
            "due_date": date.today() + timedelta(days=14),
        },
        {
            "title": "Fire-Rated Stairwell Doors & Frames",
            "description": "UL 10C fire door submittal packet and shop drawings",
            "specification_section": "08 11 13",
            "required_by": "Apex Door & Hardware Specialists",
            "required_form": "Product data, shop drawings, UL certs",
            "source_evidence": "Section 08 11 13 §2.02.A: Stair enclosure assemblies minimum 90-min fire resistance.",
            "specification_revision": "Rev 01",
            "due_date": date.today() + timedelta(days=7),
        },
        {
            "title": "Structural Steel Mill Certificates",
            "description": "Mill test certificates for structural wide-flange beams",
            "specification_section": "05 12 00",
            "required_by": "Severfield Structural Steel",
            "required_form": "Certified Mill Test Reports (MTRs)",
            "source_evidence": "Section 05 12 00 §1.04.A: Submit certified mill test reports prior to steel erection.",
            "specification_revision": "Rev 01",
            "due_date": date.today() - timedelta(days=5),  # Overdue
        },
    ]

    items = generate_register(db, project_id, requirements)
    print(f"Generated {len(items)} register items.")

    # 1. Populate Findings for SUB-001 (Flooring)
    sub1 = next((i for i in items if i.number == "SUB-001"), None)
    if sub1:
        sub1.register_status = "UNDER_REVIEW"
        existing_f1 = db.query(Finding).filter(Finding.submittal_id == sub1.id).all()
        if not existing_f1:
            findings1 = compare_flooring(
                {"minimum_thickness": 3.0, "fire_performance": "Class A", "warranty_years": 10},
                {"thickness": 2.5, "fire_performance": "Class A", "warranty_years": 10},
            )
            for f in findings1:
                db.add(
                    Finding(
                        submittal_id=sub1.id,
                        attribute=f.attribute,
                        requirement=f.requirement,
                        submitted_value=f.submitted_value,
                        result=f.result,
                        specification_evidence=f.specification_evidence,
                        submission_evidence=f.submission_evidence,
                        status="PENDING_REVIEW",
                    )
                )

    # 2. Populate Findings for SUB-002 (Fire Doors)
    sub2 = next((i for i in items if i.number == "SUB-002"), None)
    if sub2:
        sub2.register_status = "UNDER_REVIEW"
        existing_f2 = db.query(Finding).filter(Finding.submittal_id == sub2.id).all()
        if not existing_f2:
            findings2 = compare_fire_doors(
                {"fire_rating": "90 Minutes (1.5 Hours)", "steel_gauge": "16 Gauge (0.053 in / 1.3 mm)", "stc_rating": 38},
                {"fire_rating": "60 Minutes (1.0 Hour)", "steel_gauge": "16 Gauge (1.3 mm) Cold-Rolled Steel", "stc_rating": None},
            )
            for f in findings2:
                db.add(
                    Finding(
                        submittal_id=sub2.id,
                        attribute=f.attribute,
                        requirement=f.requirement,
                        submitted_value=f.submitted_value,
                        result=f.result,
                        specification_evidence=f.specification_evidence,
                        submission_evidence=f.submission_evidence,
                        status="PENDING_REVIEW",
                    )
                )

    db.commit()
    db.close()
    print("Demo dataset seeded successfully!")
    print("- SUB-001 (Flooring): Under Review, 3 findings (1 deviation: thickness)")
    print("- SUB-002 (Fire Doors): Under Review, 3 findings (1 deviation: fire rating, 1 missing: STC)")
    print("- SUB-003 (Structural Steel): Overdue by 5 days")


if __name__ == "__main__":
    seed_demo()
