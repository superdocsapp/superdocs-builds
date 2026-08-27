# ACME AUTOMOTIVE SYSTEMS

## Supplier Quality Report

*Template AASQ-100, Rev. 2 — Supplier to complete all sections below.*

## 1. Failure Mode and Effects Analysis (FMEA)

**Instructions:** List every failure mode for the item/process below. Every row must carry
Severity, Occurrence, and Detection ratings on the 1-10 AIAG-VDA scale, and a computed RPN
(Severity × Occurrence × Detection). Leave nothing blank — write "TBD" if a rating
is not yet available, do not guess.

| ID | Function | Failure Mode | Effect | Severity (S) | Occurrence (O) | Detection (D) | RPN (S×O×D) | Current Controls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FM-01 | Stamp mounting bracket to print dimensions | Hole position out of tolerance | Bracket misaligns with mating part; assembly line stoppage | 7 | 4 | 3 | 84 | 100% CMM check on first article; SPC on hole position, sample n=5/hr |
| FM-02 | Weld bracket to base plate | Incomplete weld penetration | Reduced joint strength; potential field failure under load | 9 | 2 | 4 | 72 | Ultrasonic weld inspection, 100% |
| FM-03 | Weld bracket to base plate | Weld spatter contaminating adjacent surface finish | Cosmetic rejection at customer incoming inspection | 3 | 5 | 6 | 90 | Visual inspection, 100% |

## 2. Recommended Actions

| Action ID | Failure Mode | Recommended Action | Responsible | Target Date | Status |
| --- | --- | --- | --- | --- | --- |
| AC-01 | FM-01 | Add poka-yoke fixture pin to stamping die to prevent mislocation | J. Alvarez (Tooling Eng.) | 2026-09-30 | open |
| AC-02 | FM-02 | Increase weld current setpoint 5%; requalify per WPS-114 | M. Chen (Welding Eng.) | 2026-09-15 | open |

## 3. PPAP Submission

**Supplier:** Sharma Precision Fabrication Ltd.   **Customer:** Acme Automotive Systems   **Submission Level:** 3

### Reason for Submission

Annual revalidation per customer PPAP schedule

### Design Records

Per drawing BA-204-C rev F, dated 2026-01-12

### Process Flow Diagram

Blank -> Stamp -> Deburr -> Weld -> Inspect -> Pack

### Control Plan

See attached Control Plan CP-BA204-C rev 3

### Dimensional Results

All 22 characteristics within tolerance, Cpk >= 1.33 on 4 critical dimensions

### Material / Performance Test Results

Material cert on file (steel grade per print); no performance testing required for this part class

## 4. 8D Corrective Action Report

### D1 — Team

P. Sharma (SQE), J. Alvarez (Tooling), M. Chen (Welding), plant quality manager

### D2 — Problem Description

3 units in customer lot 44821 rejected for hole position out of tolerance (FM-01)

### D3 — Containment Actions

100% sort of remaining lot 44821 and next 3 lots; hold shipment pending fixture fix

### D4 — Root Cause

Stamping die locating pin worn beyond spec, allowing part shift during form operation

### D5 — Permanent Corrective Actions

Replace locating pin; add poka-yoke sensor to detect mislocation before stamp stroke (see AC-01)

### D6 — Implementation & Verification

First-article CMM report post-fix, plus 30-day SPC trend review

### D7 — Prevent Recurrence

Add locating pin wear check to PM schedule (weekly gauge check) across all stamping dies of this family

### D8 — Team Recognition

Team debrief scheduled; lessons folded into new-hire tooling training

---

Acme Automotive Systems — Supplier Quality Engineering. Confidential to supplier and Acme only.
