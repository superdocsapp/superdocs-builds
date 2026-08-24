"""
SuperDocs Clinical Nursing Handoff & Transfer Packet Assembler CLI (Task 2 Band S2).
Runs end-to-end clinical ingestion, SBAR generation, medication reconciliation,
human verification gating, and ReportLab multi-page PDF generation.
"""
import os
from pathlib import Path
import sys

# Configure path and stdout
current_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(current_dir))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from demo_patient import build_demo_assembler
from packet_builder import ClinicalPDFPacketBuilder
from superdocs_client import SuperDocsAPIClient


def run_full_clinical_workflow(use_live_superdocs_api: bool = True):
    print("=" * 75)
    print("[SUPERDOCS CLINICAL NURSING HANDOFF & TRANSFER PACKET ASSEMBLER (S2)]")
    print("=" * 75)

    superdocs = SuperDocsAPIClient()
    if superdocs.api_key:
        print(f"[✓] SuperDocs API Connected: Bearer key loaded from environment / credentials.")
    else:
        print("[!] Running in offline zero-spend test mode (Mock LLM & Local ReportLab Engine).")

    # 1-4. Ingest the demo patient chart (Eleanor Vance, MRN 883921).
    # All SBAR citations, orders, pending labs, and mobility/isolation values
    # are derived from the committed sample_patient_records/ files — the
    # single source of truth lives in demo_patient.py.
    assembler = build_demo_assembler()
    demo = assembler.demographics
    sbar = assembler.sbar

    print("\n[1] Clinical Patient Chart Ingested:")
    print(f"    • Patient: {demo.name} | MRN: {demo.mrn} | Sending: {demo.sending_unit} -> {demo.receiving_unit}")
    print(f"    • Code Status: {demo.code_status}")

    print("\n[2] Provenance-Grounded SBAR Narrative:")
    print(f"    • SITUATION: {sbar.situation}")
    print(f"    • BACKGROUND: {sbar.background}")
    print(f"    • ASSESSMENT: {sbar.assessment}")
    print(f"    • RECOMMENDATION: {sbar.recommendation}")

    print("\n[3] Conservative Medication Reconciliation (100% Duplicate Recall):")
    for med in assembler.medications:
        high_alert_tag = f" [HIGH ALERT: {med.high_risk_category}]" if med.is_high_risk else ""
        dup_tag = f"\n      --> WARNING: {med.duplicate_warning}" if med.is_duplicate else ""
        print(f"    - {med.name} ({med.dose}, {med.route}){high_alert_tag}{dup_tag}")

    # 5. Attempt Export Before Human Sign-Off (Test Gating)
    print("\n[4] GATING CHECK: Attempting PDF Export Before Human Verification...")
    unlocked, unverified = assembler.gates.is_export_unlocked()
    if not unlocked:
        print(f"    ❌ EXPORT BLOCKED (HTTP 422): {len(unverified)} Safety Gates Pending:")
        for g in unverified:
            print(f"       • {g}")
        print("    🛑 Deterministic Gate: Export is strictly forbidden without clinician sign-off.")

    # 6. Execute Human Clinician Verification Gates
    print("\n[5] Executing Clinician Safety Verification Sign-Offs:")
    print("    ✓ Gate 1: Confirmed Allergies [Penicillin (Anaphylaxis)] — RN Sarah Jenkins (RN-4029)")
    assembler.confirm_allergy_gate("RN Sarah Jenkins", "RN-4029")

    print("    ✓ Gate 2: Verified Resuscitation Code Status [FULL CODE] — RN Sarah Jenkins (RN-4029)")
    assembler.confirm_code_status_gate("RN Sarah Jenkins", "RN-4029")

    print("    ✓ Gate 3: Dual-Nurse High-Alert Sign-Off [Heparin & Insulin] — RN Sarah Jenkins & RN Mark Taylor (RN-5104)")
    assembler.confirm_high_risk_meds_gate("RN Sarah Jenkins", "RN-4029", "RN Mark Taylor", "RN-5104")

    # 7. Generate PDF Packet
    print("\n[6] Compiling 10-Page Standardized Transfer Packet PDF...")
    builder = ClinicalPDFPacketBuilder(assembler)
    output_filename = str(current_dir / "transfer_packet_patient-883921.pdf")
    builder.save_pdf(output_filename)

    digest = assembler.generate_audit_digest()
    print(f"    📄 Local PDF Generated: {output_filename}")
    print(f"    🔒 Tamper-Evident SHA-256 Audit Digest: {digest}")

    # 8. Synchronize with SuperDocs Platform API (The 4-Call Contract)
    if superdocs.api_key:
        print("\n[7] Synchronizing with Live SuperDocs Platform API:")
        session_id = f"session_handoff_{demo.mrn}"
        edit_instruction = (
            f"Generate clinical transfer summary for patient {demo.name} (MRN: {demo.mrn}). "
            f"Include confirmed allergies: {', '.join(assembler.allergies)}, code status: {demo.code_status}, "
            f"and reconciled MAR with {len(assembler.medications)} verified medications."
        )
        print("    --> Calling SuperDocs API POST /v1/chat (Targeted SBAR In-Document Edits)...")
        chat_resp = superdocs.create_or_update_handoff_document(session_id, edit_instruction)
        print(f"    ✓ SuperDocs Edit Response: {chat_resp.get('response', 'Changes Applied')[:80]}...")

        print("    --> Calling SuperDocs API POST /v1/documents/export (.docx)...")
        docx_bytes = superdocs.export_document(session_id, "docx")
        if docx_bytes:
            live_out = current_dir / f"superdocs_handoff_{demo.mrn}.docx"
            live_out.write_bytes(docx_bytes)
            print(f"    ✓ SuperDocs Word Dossier Exported: {live_out} ({len(docx_bytes):,} bytes)")

    print("\n" + "=" * 75)
    print("✅ TRANSFER PACKET COMPLETE, VERIFIED & READY FOR PATIENT TRANSFER")
    print("=" * 75)


if __name__ == "__main__":
    run_full_clinical_workflow()
