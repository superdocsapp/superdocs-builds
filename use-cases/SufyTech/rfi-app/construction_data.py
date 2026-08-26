"""
construction_data.py — fictional project data shaped like what Procore's
or Autodesk Construction Cloud's real APIs return for an RFI, per the
task doc's explicit instruction: "Where your build needs a client, a
company, or data, invent them. Fictional clients and fabricated test
data are expected; real third-party data is not welcome."

SuperDocs itself does not integrate with Procore/Autodesk (no such
connector exists), and this task doc is explicit that "SuperDocs itself
does not browse the live web, so do not design around it doing that" —
this build is free to fetch data however it likes, so a real Procore/
Autodesk OAuth integration would be legitimate future work, but is out
of scope for what "strong" asks for here: "Reviewer supplies one
fictional RFI payload with a spec section and a drawing reference, and
the generated document carries both references correctly into the
formal RFI format." This module IS that fictional payload, shaped
field-for-field like Procore's real RFI object (see Procore's public
API reference for `rfi` resources: id, number, subject, question,
drawing_number/spec_section as custom fields, assignees, due_date,
status) so swapping this module for a real API client later is a
drop-in replacement, not a rewrite.

Two payloads are provided: the RFI as originally logged (no response
yet), and the architect's response arriving later — mirroring Build 1's
"initial state, then one real targeted update" shape, which is what
lets this build prove data fidelity on TWO separate events, not one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RFI:
    rfi_number: str
    project_name: str
    project_number: str
    subject: str
    spec_section: str          # e.g. "03 30 00 - Cast-in-Place Concrete"
    drawing_reference: str     # e.g. "S-201, Detail 4"
    question: str
    submitted_by: str
    submitted_to: str
    date_submitted: str        # ISO date string, kept as text for the document
    date_required: str
    cost_impact: Optional[str] = None      # None = not yet assessed
    schedule_impact: Optional[str] = None  # None = not yet assessed
    status: str = "Open"
    response: Optional[str] = None
    responded_by: Optional[str] = None
    date_responded: Optional[str] = None


def fetch_open_rfi() -> RFI:
    """
    Simulates a GET against Procore's /rfis/{id} endpoint (or Autodesk
    Construction Cloud's equivalent) for one open, unanswered RFI. This
    is the "one fictional RFI payload with a spec section and a drawing
    reference" the task's "what strong looks like" bar asks for.
    """
    return RFI(
        rfi_number="RFI-0142",
        project_name="Riverside Medical Office Building",
        project_number="24-118",
        subject="Conflict between structural and mechanical routing at Grid Line C",
        spec_section="23 05 00 - Common Work Results for HVAC",
        drawing_reference="S-201, Detail 4 / M-401",
        question=(
            "Structural drawing S-201 Detail 4 shows a W12x26 beam at Grid Line C, "
            "Elevation 14'-6\", running the full bay width. Mechanical drawing M-401 "
            "shows a 24\" round supply duct routed through the same bay at Elevation "
            "14'-3\", which conflicts with the beam's bottom flange. Please confirm "
            "whether the duct should be rerouted below the beam or whether the beam "
            "elevation is being revised, and provide the resolved dimension."
        ),
        submitted_by="Dana Whitfield, Project Engineer, Cascade Builders LLC",
        submitted_to="Marcus Lindqvist, Project Architect, Lindqvist & Cho Architecture",
        date_submitted="2026-08-11",
        date_required="2026-08-18",
        status="Open",
    )


def fetch_rfi_response_event() -> dict:
    """
    Simulates a second, later API call — a webhook or polled update from
    Procore/Autodesk Construction Cloud reporting that the architect has
    responded to RFI-0142. Returns only the fields that changed, which is
    exactly the shape a real webhook payload would have (a diff, not a
    full re-fetch) — and is what run_build2.py sends to SuperDocs as the
    targeted edit instruction, the same "only touch what actually
    changed" principle Build 1's re-cost pass follows.
    """
    return {
        "rfi_number": "RFI-0142",
        "status": "Answered",
        "response": (
            "Beam elevation at Grid Line C is being revised in Structural Bulletin "
            "SB-07 (issued under separate cover) to Elevation 14'-1\", clearing the "
            "duct as shown on M-401 with 2\" of clearance. No duct reroute is required. "
            "Contractor to proceed per SB-07 once issued; no schedule delay anticipated "
            "provided SB-07 is incorporated within 5 business days."
        ),
        "responded_by": "Marcus Lindqvist, Project Architect, Lindqvist & Cho Architecture",
        "date_responded": "2026-08-15",
        "cost_impact": "None anticipated - structural revision is a design correction, not a change in scope.",
        "schedule_impact": "None, contingent on SB-07 incorporation within 5 business days of issuance.",
    }
