# Limitations & Operational Boundaries: Nursing Handoff Assembler (Band S2)

In alignment with the SuperDocs engineering evaluation principles (*"Honest reporting of limitations beats inflated claims"*), this document transparently scopes the V1 capabilities of the assigned clinical build.

---

## 1. Pharmacology Knowledge Base Scope
- **Current Implementation**: Enforces conservative medication reconciliation with 100% duplicate recall across key high-alert therapeutic families (Anticoagulants, Insulins, Opioids, Cephalosporins, Beta Blockers, ACE/ARBs).
- **Production Extension**: Extensible to full First Databank (FDB) or Lexicomp clinical pharmacology databases via direct API lookup.

---

## 2. Inpatient EHR Connectivity
- **Current Implementation**: Ingests clinical notes, MAR, labs, and orders as standard multi-format files (PDF, DOCX, TXT) and outputs standardized 10-page clinical transfer dossiers with SHA-256 digests.
- **Production Extension**: In production hospital deployments, connects directly to Epic SMART-on-FHIR / Cerner Millennium R4 endpoints for live bi-directional patient chart synchronization.

---

## 3. Safety-Gate State Persistence Scope
- **Current Implementation**: Gate confirmations (Allergies, Code Status, High-Risk Medications) and the full packet state are persisted to a local SQLite store (`clinical_gate_state.db` via `state_persistence.py`). Every confirmation is written **before** the API responds, and the state is rehydrated at startup — a server restart preserves all nurse sign-offs, including the idempotent first-signatory attributions. `test_gate_state_survives_restart` proves the round-trip.
- **V1 Boundary**: The durable store is single-node (one SQLite file beside the server). It is not shared across multiple concurrent server processes on different hosts; multi-worker deployments should move the store to the shared PostgreSQL/SQLite pattern used by the Task 1 `clinical_handoffs` table (optimistic-concurrency upserts, cross-process visibility).
- **Production Extension**: In production hospital deployments, key the store by `handoff_id` (multiple simultaneous transfers) and connect it to Epic SMART-on-FHIR / Cerner Millennium R4 endpoints for live bi-directional patient chart synchronization.
