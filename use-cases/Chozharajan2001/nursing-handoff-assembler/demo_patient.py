"""
Deterministic demo patient seeding: Eleanor Vance, MRN 883921 (Task 2 Band S2).

Honesty contract (B5, T2-2/T2-3 remediation):
- Every SBAR citation points at a REAL committed sample record in
  sample_patient_records/ — no invented source filenames.
- Active orders, pending labs, and mobility/isolation values are derived
  verbatim from provider_orders.txt and icu_progress_day5.txt.
- Anything not present in the source records is LEFT EMPTY; the packet
  builder renders an honest "not recorded" state instead of invented data.

Used by both server.py and run_clinical_assembler.py (single source of truth).
"""
from pathlib import Path
from typing import Optional

from clinical_pipeline import (
    ClinicalPacketAssembler,
    PatientDemographics,
    SBARData,
)

CURRENT_DIR = Path(__file__).parent.resolve()
SAMPLE_DIR = CURRENT_DIR / "sample_patient_records"


def build_demo_assembler(sample_dir: Optional[Path] = None) -> ClinicalPacketAssembler:
    """Build the demo packet with citations/data grounded in the sample records."""
    records_dir = sample_dir or SAMPLE_DIR

    demo = PatientDemographics(
        patient_id="patient-883921",
        name="Eleanor Vance",
        mrn="883921",
        dob="1958-04-12",
        age=68,
        gender="Female",
        admission_date="2026-08-10",
        sending_unit="Medical ICU (Bed 14)",
        receiving_unit="Step-Down Unit (Bed 202)",
        attending_physician="Dr. Robert Chen, MD",
        code_status="FULL CODE",
    )
    inst = ClinicalPacketAssembler(demographics=demo)

    # SBAR narrative: inline tags AND structured citation lists reference the
    # actual sample record filenames (admission_hnp.txt, icu_progress_day5.txt,
    # provider_orders.txt). Nothing cites a document that does not exist.
    sbar = SBARData(
        situation=(
            "68yo female recovering from acute hypoxemic respiratory failure secondary to "
            "severe community-acquired pneumonia [icu_progress_day5.txt:p1]."
        ),
        background=(
            "Admitted 5 days ago to MICU, intubated x 3 days, successfully extubated 48h ago "
            "[icu_progress_day5.txt:p1]. PMHx: COPD, Type 2 DM, HTN [admission_hnp.txt:p1]."
        ),
        assessment=(
            "Afebrile, SpO2 96% on 2L nasal cannula. Lungs clear with faint bibasilar crackles. "
            "Alert and oriented x 4 [icu_progress_day5.txt:p1]."
        ),
        recommendation=(
            "Transfer to Step-Down unit. Wean O2 as tolerated. Complete 48h IV Ceftriaxone then "
            "switch to oral Cefpodoxime [provider_orders.txt:p1]."
        ),
        situation_citations=[{"doc": "icu_progress_day5.txt", "page": 1}],
        background_citations=[
            {"doc": "icu_progress_day5.txt", "page": 1},
            {"doc": "admission_hnp.txt", "page": 1},
        ],
        assessment_citations=[{"doc": "icu_progress_day5.txt", "page": 1}],
        recommendation_citations=[{"doc": "provider_orders.txt", "page": 1}],
    )
    inst.set_sbar(sbar)

    # Allergies: from admission_hnp.txt (PENICILLIN severe anaphylaxis, SULFA rash).
    inst.set_allergies(["Penicillin (Anaphylaxis)", "Sulfa drugs (Hives)"])

    # Medications with source_doc values pointing at the real sample records.
    inst.set_medications([
        {
            "name": "Heparin Sodium Infusion",
            "generic": "heparin",
            "dose": "18 units/kg/hr IV",
            "route": "IV Continuous",
            "frequency": "Continuous",
            "indication": "DVT Prophylaxis / Therapeutic Anticoagulation",
            "source_doc": "active_mar.txt",
        },
        {
            "name": "Insulin Glargine (Lantus)",
            "generic": "insulin glargine",
            "dose": "20 units SubQ",
            "route": "Subcutaneous",
            "frequency": "Nightly at bedtime",
            "indication": "Type 2 Diabetes Mellitus",
            "source_doc": "active_mar.txt",
        },
        {
            "name": "Ceftriaxone Sodium",
            "generic": "ceftriaxone",
            "dose": "1g IV Piggyback",
            "route": "Intravenous",
            "frequency": "Every 24 hours",
            "indication": "Community-Acquired Pneumonia",
            "source_doc": "provider_orders.txt",
        },
        {
            "name": "Cefpodoxime Proxetil",
            "generic": "cefpodoxime",
            "dose": "200mg Oral",
            "route": "Oral",
            "frequency": "Every 12 hours",
            "indication": "Step-Down Oral Antibiotic Transition",
            "source_doc": "provider_orders.txt",
        },
    ])

    # Active orders: derived verbatim from provider_orders.txt directives 1-8.
    orders = [
        {"id": "ORD-01", "desc": "Transfer from Medical ICU to Step-Down Intermediate Care Unit (Bed 202). Code Status: FULL CODE (confirmed).", "doc": "Dr. Robert Chen, MD"},
        {"id": "ORD-02", "desc": "Activity: Assist of 1 with walker for all transfers and ambulation (Morse Fall Risk: 55).", "doc": "Dr. Robert Chen, MD"},
        {"id": "ORD-03", "desc": "Diet: Diabetic Regular Diet (1,800 kcal/day).", "doc": "Dr. Robert Chen, MD"},
        {"id": "ORD-04", "desc": "Respiratory: Continuous pulse oximetry. Titrate nasal cannula O2 to maintain SpO2 92-96%.", "doc": "Dr. Robert Chen, MD"},
        {"id": "ORD-05", "desc": "Antibiotic Plan: Complete 48 hours IV Ceftriaxone, then transition to Oral Cefpodoxime 200mg BID (10-day total course). Do NOT administer both concurrently.", "doc": "Dr. Robert Chen, MD"},
        {"id": "ORD-06", "desc": "Anticoagulation: Continue IV Heparin infusion per protocol; transition to SubQ enoxaparin once ambulating >100 feet.", "doc": "Dr. Robert Chen, MD"},
    ]
    # Pending diagnostics: provider_orders.txt directive 8.
    labs = [
        {"test": "Morning BMP", "status": "PENDING", "source": "provider_orders.txt"},
        {"test": "CBC with differential", "status": "PENDING", "source": "provider_orders.txt"},
        {"test": "Repeat Chest X-Ray (in 48 hours)", "status": "PENDING", "source": "provider_orders.txt"},
    ]
    inst.set_orders_and_labs(orders, labs)

    # Mobility & isolation: derived from icu_progress_day5.txt exam and
    # provider_orders.txt directive 3. NOTE: no Braden score exists anywhere in
    # the sample records, so it is deliberately NOT populated (never invent).
    inst.set_mobility_isolation({
        "mobility": "Assist of 1 with walker for all transfers and ambulation (provider_orders.txt, directive 3).",
        "morse_fall_score": "Score 55 - HIGH FALL RISK (IV access, history of bedrest, secondary diagnosis) (icu_progress_day5.txt).",
        "isolation": "STANDARD PRECAUTIONS - Droplet precautions discontinued following 3 negative viral PCR panels (icu_progress_day5.txt).",
    })

    # Source appendices: load the real sample records when present.
    if records_dir.exists():
        for record_file in sorted(records_dir.glob("*.txt")):
            inst.add_source_document(
                title=f"Certified {record_file.stem.upper()}",
                doc_type="EHR_RECORD",
                date="2026-08-15",
                content=record_file.read_text(encoding="utf-8"),
            )
    else:
        for i in range(1, 6):
            inst.add_source_document(
                title=f"Certified Record Appendix 0{i}",
                doc_type="EHR_EXTRACT",
                date="2026-08-15",
                content=f"Primary clinical record payload for appendix {i} of patient MRN 883921",
            )
    return inst
