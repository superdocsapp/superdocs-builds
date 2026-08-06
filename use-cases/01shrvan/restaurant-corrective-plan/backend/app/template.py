from __future__ import annotations

from datetime import date
from html import escape

from .models import Violation


def build_plan_template_html(
    *,
    restaurant: str,
    inspection_date: date,
    health_department: str,
    violations: tuple[Violation, ...] | list[Violation],
) -> str:
    sections = "\n".join(_violation_section(violation) for violation in violations)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Corrective Action Plan - {escape(restaurant)}</title>
  </head>
  <body>
    <h1>Corrective Action Plan</h1>
    <p><strong>Restaurant:</strong> {escape(restaurant)}</p>
    <p><strong>Inspection date:</strong> {inspection_date.isoformat()}</p>
    <p><strong>Health department:</strong> {escape(health_department)}</p>
    <h2>Cited Violations</h2>
{sections}
  </body>
</html>
"""


def _violation_section(violation: Violation) -> str:
    location = violation.location or "Not specified"
    return f"""    <section data-violation-code="{escape(violation.code)}">
      <h3>Violation {escape(violation.code)}</h3>
      <p><strong>Finding:</strong> {escape(violation.description)}</p>
      <p><strong>Location:</strong> {escape(location)}</p>
      <p><strong>Corrective action:</strong> <span data-slot="corrective-action">[pending]</span></p>
      <p><strong>Responsible party:</strong> <span data-slot="responsible-party">[pending]</span></p>
      <p><strong>Evidence:</strong> <span data-slot="evidence">[pending]</span></p>
    </section>"""

