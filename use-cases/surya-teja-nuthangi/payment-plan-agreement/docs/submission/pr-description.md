# PR title

`feat(use-cases): add payment plan agreement builder`

# PR description

**Builder:** Surya Teja Nuthangi

Adds a self-contained payment-plan agreement workflow for small-business and healthcare-style synthetic billing scenarios. It calculates a deterministic schedule, renders one canonical set of facts into table and prose, uses SuperDocs for human-reviewed clarity edits, independently verifies proposed and final documents, and exports DOCX.

SuperDocs integration: async chat editing, durable job polling, item-level approve/reject, and document export. The API key remains server-side. A clearly labeled offline adapter supports evaluation without claiming live behavior.

Evidence: 36 tests pass in the final regression; the offline browser flow passes through DOCX export. A real synthetic SuperDocs job completed with 14 item-level proposals approved, zero rejected, zero repairs, independent final verification passing with zero findings, and a valid 37,329-byte DOCX export.

Limitations: no legal-advice claim, jurisdiction selection, native e-signature, or production persistence for local UI run metadata. Cadence is limited to weekly, biweekly, and monthly in v1.

Screenshot: `artifacts/screenshots/payment-plan-evaluator-final.png`.
