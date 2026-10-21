"""A small fixed catalog of synthetic documents to assign for review.

Fictional content, invented for this demo — per the round's own brief: "Where your build
needs a client, a company, or data, invent them. Fictional clients and fabricated test data
are expected." Nothing here is a real company's real document.
"""

from __future__ import annotations

DOCUMENTS: dict[str, dict[str, str]] = {
    "dpa": {
        "title": "Vendor Data Processing Addendum (draft)",
        "html": """<h1>Data Processing Addendum</h1>
<p>This Addendum forms part of the Master Services Agreement between
<strong>Northwind Analytics, Inc.</strong> ("Processor") and <strong>Acme Retail Group</strong>
("Controller").</p>
<h2>1. Scope of Processing</h2>
<p>Processor shall process Personal Data solely for the purpose of providing the analytics
services described in the Agreement, and for no other purpose.</p>
<h2>2. Data Retention</h2>
<p>Processor shall retain Personal Data for a period of 90 days following termination of the
Agreement, after which it shall be deleted or returned at Controller's election.</p>
<h2>3. Subprocessors</h2>
<p>Processor may engage subprocessors listed in Schedule A. Processor shall provide
Controller with 30 days' written notice before adding a new subprocessor.</p>
<h2>4. Security Measures</h2>
<p>Processor shall maintain administrative, physical, and technical safeguards no less
protective than those described in Schedule B.</p>""",
    },
    "handbook": {
        "title": "Remote Work Policy (draft)",
        "html": """<h1>Remote Work Policy</h1>
<p>This policy applies to all employees of <strong>Fernbridge Logistics</strong> who work
remotely on a full-time or hybrid basis.</p>
<h2>1. Eligibility</h2>
<p>Employees become eligible for remote work after completing 90 days of employment,
subject to manager approval.</p>
<h2>2. Equipment</h2>
<p>The Company will provide a laptop and a one-time stipend of $500 for home office setup.
Employees are responsible for maintaining a secure internet connection.</p>
<h2>3. Core Hours</h2>
<p>Remote employees must be available for meetings between 10:00 AM and 3:00 PM in their
local time zone, Monday through Friday.</p>
<h2>4. Data Security</h2>
<p>Remote employees must use company-managed devices for all work involving customer data
and must not use public Wi-Fi without a VPN connection.</p>""",
    },
    "protocol": {
        "title": "Lab Safety Protocol Amendment (draft)",
        "html": """<h1>Laboratory Safety Protocol Amendment</h1>
<p>Amendment to the standing safety protocol for the <strong>Cell Culture Facility</strong>,
Building 4, <strong>Meridian Biosciences</strong>.</p>
<h2>1. Personal Protective Equipment</h2>
<p>All personnel entering the facility must wear a lab coat, safety glasses, and nitrile
gloves at all times while handling cell cultures.</p>
<h2>2. Biosafety Cabinet Use</h2>
<p>Biosafety cabinets must be certified annually and decontaminated with 70% ethanol before
and after each use.</p>
<h2>3. Waste Disposal</h2>
<p>Biological waste must be autoclaved before disposal in accordance with institutional
policy IBC-2024-07.</p>""",
    },
}


def get_document(doc_id: str) -> dict[str, str] | None:
    return DOCUMENTS.get(doc_id)
