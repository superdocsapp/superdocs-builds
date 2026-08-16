import json
import re

from app.models.field_report import FieldReportData
from app.services.superdocs_service import SuperDocsClient


EXTRACTION_INSTRUCTION = """
Extract factual construction-site information from the field notes.

Return ONLY valid JSON matching this structure:

{
  "project": null,
  "report_date": null,
  "total_headcount": null,
  "manpower": [],
  "equipment": [],
  "work_by_area": [],
  "weather": null,
  "delays": [],
  "safety_observations": [],
  "source_notes": ""
}

Rules:

1. Use ONLY facts explicitly supported by the source notes.
2. Never invent missing information.
3. Unknown scalar values must be null.
4. Unknown lists must remain empty.
5. Preserve the wording of factual observations where useful.
6. For manpower entries:
   {
     "trade": "...",
     "headcount": number or null,
     "notes": "..." or null
   }
7. For equipment entries:
   {
     "equipment": "...",
     "status": "..." or null,
     "notes": "..." or null
   }
8. For work areas:
   {
     "area": "...",
     "work_performed": "...",
     "status": "..." or null
   }
9. For delays:
   {
     "description": "...",
     "duration_hours": number or null,
     "cause_category": "..." or null
   }
   cause_category MUST be one of exactly these values (or null if no
   cause is stated): weather, equipment_failure, material_delay,
   labor_shortage, permitting_inspection, design_coordination,
   site_conditions, other.
   Map the source wording onto the closest category above. Use "other"
   only when none of the specific categories fit - and when you do,
   keep the original wording in "description" so nothing is lost.
10. Do not infer a safety observation just because one is normally
    expected in a construction report. safety_observations must be a
    list of plain strings, e.g. ["All workers wore PPE."] - not a list
    of objects.
11. Keep source_notes equal to the original field notes.
12. For total_headcount, use an explicitly stated total if present.
    Do not calculate a total from trade entries unless the source explicitly
    states that total.

Return JSON only.
"""


class ReportExtractionError(Exception):
    """Raised when field report extraction fails."""


def _parse_json_response(response_text: str) -> dict:
    """
    Parse JSON returned by SuperDocs.

    Handles:
    - raw JSON
    - JSON inside ```json ... ``` fences
    - JSON surrounded by explanatory text
    """

    text = response_text.strip()

    # ---------------------------------------------------------
    # Case 1: Raw JSON
    # ---------------------------------------------------------

    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # ---------------------------------------------------------
    # Case 2: Markdown JSON code block
    # ---------------------------------------------------------

    fenced_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if fenced_match:
        candidate = fenced_match.group(1).strip()

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    # ---------------------------------------------------------
    # Case 3: JSON object embedded in surrounding text
    # ---------------------------------------------------------

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    raise ReportExtractionError(
        "SuperDocs did not return valid JSON."
    )


async def extract_field_report(
    *,
    report_id: str,
    notes: str,
) -> FieldReportData:
    client = SuperDocsClient()

    result = await client.chat(
        session_id=(
            f"field-report-extraction-{report_id}"
        ),
        message=(
            EXTRACTION_INSTRUCTION
            + "\n\nSOURCE FIELD NOTES:\n"
            + notes
        ),
    )

    response_text = result.get("response")

    if not response_text:
        raise ReportExtractionError(
            "SuperDocs returned an empty extraction response."
        )

    extracted = _parse_json_response(
        str(response_text)
    )

    try:
        return FieldReportData.model_validate(
            extracted
        )

    except Exception as exc:
        raise ReportExtractionError(
            "Extracted field report failed validation."
        ) from exc