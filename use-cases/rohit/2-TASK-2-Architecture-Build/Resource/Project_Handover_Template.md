# The AEC Construction Handover & Material Sync Pack
*A Pre-Flight Audit Framework for Principal Architects & Technical PMs*

> **Author / Affiliation Disclosure**: *Created by Rohit as a free open resource for the architecture community. Built using SuperDocs (a document-native AI editing environment). You are free to copy, modify, and distribute this checklist without attribution.*

---

## Document Overview & Pre-Flight Metadata

| Metadata Field | Specification / Value |
|---|---|
| **Project Name / ID** | `[Insert Project Name]` |
| **Principal Architect** | `[Lead Architect Name]` |
| **Target General Contractor** | `[GC Firm Name]` |
| **Submission Deadline** | `[Date & Timezone]` |
| **Primary CAD / BIM Repository** | `[Procore / Autodesk Link]` |

---

## 1. Material Consistency & Budget Matrix

*Goal: Ensure that every core material specified in the Design Narrative matches the Structural Calculations and the Final Budget Sheet. "Document drift" in materials is the #1 cause of contractor disputes.*

| Material Component | Design Narrative (Sec 2) | Structural Specs (Sec 5) | Budget Sheet (Sec 8) | Status |
|---|---|---|---|---|
| **Exterior Cladding** |  |  |  | `[ ]` |
| **Load-Bearing Columns** |  |  |  | `[ ]` |
| **HVAC Routing** |  |  |  | `[ ]` |
| **Flooring System** |  |  |  | `[ ]` |

---

## 2. Safety & Liability Compliance Checklist

*Goal: Ensure all local building codes and safety regulations are explicitly cited alongside structural dimensions.*

- [ ] **Fire Safety (IBC 2024)**: Exit corridor widths verified and cited in Section 4.
- [ ] **ADA Compliance**: Ramp gradients and restroom clearances explicitly noted.
- [ ] **Environmental (LEED)**: Material sourcing certifications attached in Appendix B.
- [ ] **Wind/Seismic Load**: Load tolerances cross-referenced with local municipal codes.

---

## 3. SuperDocs Automated Sync Prompt

*To instantly audit your handover pack, copy and paste this command into SuperDocs:*

<!-- SUPERDOCS MULTI-SECTION RECONCILIATION PROMPT -->
@document-target: [Section 2 Design, Section 5 Structural, Section 8 Budget]
Instruction:
Act as a strict compliance officer. Trace the four core materials (Cladding, Columns, HVAC, Flooring) across the Design, Structural, and Budget sections. 
If a material was changed in the Design section (e.g. Brick to Concrete) but not updated in the Budget section, flag the discrepancy with an urgent inline comment. 
Verify that all structural load claims cite the correct IBC 2024 safety code.
