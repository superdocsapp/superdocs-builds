"""Assembling an inspection into report HTML.

This module owns report structure, and it is deliberately the only thing that does. Which
system a finding appears under, the order the systems come in, and the order of findings
within a system are all decided here, from the catalogue and the severity ranks — never by a
model, and never by whatever order the inspector happened to walk the property in.

That is not a matter of taste. It was tested: asked to assemble a whole report from the same
findings, SuperDocs' AI applied nothing and asked for data it had been given, while the same
service applied a single narrow edit flawlessly. Structure here, prose there, and the export
verifier reads the finished file back and holds it to exactly the structure this module
produced.

The *presentation* is the format's, not this module's. How a finding looks — what is bold,
what order the label and location come in, whether there is a photograph at all — is read
from the worked example inside the firm's Word document. This module decides what goes where.
"""

from __future__ import annotations

import html as html_escape

from inspection_report.domain import catalogue
from inspection_report.domain.models import Finding, Inspection
from inspection_report.templates import binding

# Kept here as the canonical wording used by tests and by the empty-section case. The shipped
# formats carry their own copies in the Word documents themselves — see
# `inspection_report.templates.authoring`.
NOTHING_OBSERVED = "No deficiencies were observed in the areas inspected."


def escape(value: str) -> str:
    """Everything a person typed is escaped before it becomes markup.

    An inspector's note is text. If it contains angle brackets, they are angle brackets in
    the report, not tags in the document.
    """
    return html_escape.escape(value, quote=True)


def _finding_title(finding: Finding) -> str:
    if finding.location.strip():
        return escape(finding.location.strip())
    return escape(catalogue.system(finding.system_key).name)


def _sorted_findings(inspection: Inspection, system_key: str) -> list[Finding]:
    """Most urgent first, then stable by the order they were recorded."""
    ranks = {s.key: s.rank for s in catalogue.severities()}
    findings = inspection.findings_for(system_key)
    order = {f.id: i for i, f in enumerate(inspection.findings)}
    return sorted(findings, key=lambda f: (ranks.get(f.severity_key, 999), order[f.id]))


def _photo_rows(finding: Finding) -> list[dict[str, str]]:
    rows = []
    for photo in finding.photos:
        if not photo.uploaded:
            # A photo that never reached the service is left out rather than rendered as a
            # broken image in a document someone is going to print.
            continue
        caption = (
            photo.caption.strip()
            or f"{catalogue.system(finding.system_key).name} — {finding.location or 'photograph'}"
        )
        rows.append(
            {
                "photograph": f'<img src="{photo.remote_url}" alt="{escape(caption)}">',
                "caption": escape(caption),
            }
        )
    return rows


def _system_summary(count: int, name: str) -> str:
    if count == 0:
        return NOTHING_OBSERVED
    if count == 1:
        return f"One item is recorded under {name}."
    return f"{count} items are recorded under {name}, most urgent first."


def render(inspection: Inspection, template_html: str, *, include_photos: bool = True) -> str:
    """Bind an inspection into a report format. Deterministic: same input, same bytes.

    ``include_photos=False`` renders the same report with the photograph blocks left out.
    That is not a display option: the rewrite pass is prepared against the photograph-free
    render because that is what made the pass reliable.

    Measured on the live service, 27 Aug 2026. On this report — the real,
    template-derived one, eight marked notes — the review pass with photographs present
    failed three runs out of three (0, 0 and 1 of 8 notes rewritten, the rest of the
    proposals landing on unmarked boilerplate, the "not a certification" notice among it),
    while the same report without them rewrote all eight. What I could *not* do is isolate
    the cause: a minimal synthetic document with the same eight marked notes and the same
    eight images reproduces the failure only about one run in four. So photographs are not
    established as the trigger — the honest claim is that targeting is unreliable on a
    document of this shape, and that taking the photographs out of the review pass made it
    reliable here.

    The photographs go back in for the export, which is what `finalise_document` is for.
    """
    systems = list(catalogue.systems())
    fmt = binding.read_format(template_html, [s.name for s in systems])

    system_findings: dict[str, str] = {}
    system_nothing: dict[str, str] = {}
    system_summaries: dict[str, str] = {}

    for system in systems:
        findings = _sorted_findings(inspection, system.key)
        rendered: list[str] = []
        for finding in findings:
            severity = catalogue.severity(finding.severity_key)
            photos = (
                _photo_rows(finding) if include_photos and fmt.finding_shape.carries_photos else []
            )
            rendered.append(
                binding.render_finding(
                    fmt.finding_shape,
                    {
                        "severity label": escape(severity.label),
                        "location": _finding_title(finding),
                        "observation": escape(finding.prose()),
                        "recommendation": escape(
                            finding.recommendation.strip() or severity.description.strip()
                        ),
                    },
                    photos,
                )
            )
        system_findings[system.name] = "\n".join(rendered)
        system_nothing[system.name] = NOTHING_OBSERVED
        system_summaries[system.name] = _system_summary(len(findings), system.name)

    licence = inspection.inspector.licence_number.strip()
    inspector = escape(inspection.inspector.name)
    if licence:
        inspector = f"{inspector} (licence {escape(licence)})"

    return binding.assemble(
        fmt,
        document={
            "firm name": escape(inspection.inspector.firm_name or "Independent inspection"),
            "property address": escape(inspection.property.one_line()),
            "inspector": inspector,
            "date of inspection": inspection.inspected_on.strftime("%d %B %Y"),
            "systems inspected": ", ".join(s.name for s in systems) + ".",
        },
        system_findings=system_findings,
        system_nothing=system_nothing,
        system_summaries=system_summaries,
    )
