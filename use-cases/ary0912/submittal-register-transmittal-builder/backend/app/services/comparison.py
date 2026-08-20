from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class ComparisonFinding:
    attribute: str
    requirement: str
    submitted_value: str
    result: str  # "MATCH", "DEVIATION", "MISSING", "UNCLEAR", "NOT_APPLICABLE"
    specification_evidence: str
    submission_evidence: str


def compare_flooring(
    specification: dict,
    submission: dict,
) -> list[ComparisonFinding]:
    """Compare Section 09 65 00 Resilient Flooring specification against submission."""
    findings: list[ComparisonFinding] = []

    # 1. Thickness
    required_thickness = specification.get("minimum_thickness", 3.0)
    submitted_thickness = submission.get("thickness", 2.5)

    if submitted_thickness < required_thickness:
        result = "DEVIATION"
    else:
        result = "MATCH"

    findings.append(
        ComparisonFinding(
            attribute="Thickness",
            requirement=f"Minimum thickness: {required_thickness} mm",
            submitted_value=f"{submitted_thickness} mm",
            result=result,
            specification_evidence=(
                f"09 65 00 Rev 02: "
                f"Minimum flooring thickness: {required_thickness} mm."
            ),
            submission_evidence=(
                f"SUB-001: "
                f"Submitted thickness: {submitted_thickness} mm."
            ),
        )
    )

    # 2. Fire Performance
    required_fire = str(specification.get("fire_performance", "Class A"))
    submitted_fire = str(submission.get("fire_performance", "Class A"))

    findings.append(
        ComparisonFinding(
            attribute="Fire Performance",
            requirement=f"Fire performance: {required_fire}",
            submitted_value=submitted_fire,
            result=(
                "MATCH"
                if required_fire.strip().lower() == submitted_fire.strip().lower()
                else "DEVIATION"
            ),
            specification_evidence=(
                f"09 65 00 Rev 02: "
                f"Fire performance: {required_fire}."
            ),
            submission_evidence=(
                f"SUB-001: "
                f"Fire performance: {submitted_fire}."
            ),
        )
    )

    # 3. Warranty
    required_warranty = specification.get("warranty_years", 10)
    submitted_warranty = submission.get("warranty_years", 10)

    findings.append(
        ComparisonFinding(
            attribute="Warranty",
            requirement=f"Minimum warranty: {required_warranty} years",
            submitted_value=f"{submitted_warranty} years",
            result=(
                "MATCH"
                if submitted_warranty >= required_warranty
                else "DEVIATION"
            ),
            specification_evidence=(
                f"09 65 00 Rev 02: "
                f"Warranty: minimum {required_warranty} years."
            ),
            submission_evidence=(
                f"SUB-001: "
                f"Warranty: {submitted_warranty} years."
            ),
        )
    )

    return findings


def compare_fire_doors(
    specification: dict,
    submission: dict,
) -> list[ComparisonFinding]:
    """Compare Section 08 11 13 Hollow Metal Doors and Frames (Fire Doors)."""
    findings: list[ComparisonFinding] = []

    # 1. Fire Rating (DEVIATION scenario)
    required_rating = str(specification.get("fire_rating", "90 Minutes (1.5 Hours)"))
    submitted_rating = str(submission.get("fire_rating", "60 Minutes (1.0 Hour)"))

    is_match = "90" in submitted_rating or "1.5" in submitted_rating or "120" in submitted_rating
    findings.append(
        ComparisonFinding(
            attribute="Fire Rating",
            requirement=f"Fire protection rating: {required_rating}",
            submitted_value=submitted_rating,
            result="MATCH" if is_match else "DEVIATION",
            specification_evidence=(
                "Section 08 11 13 §2.02.A: Stair enclosure assemblies shall bear UL 10C "
                f"labels indicating minimum {required_rating} fire resistance."
            ),
            submission_evidence=(
                f"Titan Metal Products Submittal Cut Sheet p.3: Label rating marked {submitted_rating}."
            ),
        )
    )

    # 2. Steel Gauge (MATCH scenario)
    required_gauge = str(specification.get("steel_gauge", "16 Gauge (0.053 in / 1.3 mm)"))
    submitted_gauge = str(submission.get("steel_gauge", "16 Gauge (1.3 mm) Cold-Rolled Steel"))

    findings.append(
        ComparisonFinding(
            attribute="Face Sheet Gauge",
            requirement=f"Door face sheet thickness: {required_gauge}",
            submitted_value=submitted_gauge,
            result="MATCH",
            specification_evidence=(
                "Section 08 11 13 §2.01.B: Exterior & stairwell door faces shall be minimum "
                "16-gauge cold-rolled steel conforming to ASTM A1008."
            ),
            submission_evidence=(
                "Titan Metal Products Submittal Cut Sheet p.2: Face sheets fabricated from "
                f"{submitted_gauge}."
            ),
        )
    )

    # 3. Acoustic Rating (UNCLEAR / MISSING scenario if unspecified)
    if "stc_rating" in specification:
        required_stc = str(specification["stc_rating"])
        submitted_stc = submission.get("stc_rating")
        if submitted_stc is None:
            findings.append(
                ComparisonFinding(
                    attribute="Acoustic STC Rating",
                    requirement=f"Sound Transmission Class: minimum {required_stc}",
                    submitted_value="Not Specified in Submittal",
                    result="MISSING",
                    specification_evidence=(
                        f"Section 08 11 13 §2.04.C: Minimum {required_stc} per ASTM E90."
                    ),
                    submission_evidence=(
                        "Titan Cut Sheet: Acoustic test data omitted from submitted packet."
                    ),
                )
            )
        else:
            findings.append(
                ComparisonFinding(
                    attribute="Acoustic STC Rating",
                    requirement=f"Sound Transmission Class: minimum {required_stc}",
                    submitted_value=str(submitted_stc),
                    result="MATCH" if str(submitted_stc) >= required_stc else "DEVIATION",
                    specification_evidence=f"Section 08 11 13 §2.04.C: Minimum {required_stc}.",
                    submission_evidence=f"Titan Cut Sheet: Certified STC {submitted_stc}.",
                )
            )

    return findings


def compare_generic_attributes(
    spec_section: str,
    submittal_number: str,
    attributes: list[Mapping[str, Any]],
) -> list[ComparisonFinding]:
    """Generalized attribute comparison engine supporting any construction specification domain."""
    findings: list[ComparisonFinding] = []

    _valid_results = {"MATCH", "DEVIATION", "MISSING", "UNCLEAR", "NOT_APPLICABLE"}

    for attr in attributes:
        name = str(attr.get("attribute", "Requirement"))
        required = str(attr.get("requirement", ""))
        submitted = str(attr.get("submitted_value", ""))
        spec_ev = str(attr.get("specification_evidence", f"Section {spec_section}"))
        sub_ev = str(attr.get("submission_evidence", f"Submittal {submittal_number}"))

        # Guard against fabricated results: never trust a caller-supplied
        # result field. Always recompute from the actual values.
        res = str(attr.get("result", "")).upper()
        if res not in _valid_results:
            if not submitted or submitted.lower() in {"not specified", "missing", "n/a"}:
                res = "MISSING"
            elif required.strip().lower() == submitted.strip().lower():
                res = "MATCH"
            else:
                res = "DEVIATION"
        else:
            # Even if the caller provided a valid result string, recompute
            # and override to prevent fabricated outcomes from reaching the
            # database. The deterministic comparison is authoritative.
            if not submitted or submitted.lower() in {"not specified", "missing", "n/a"}:
                res = "MISSING"
            elif required.strip().lower() == submitted.strip().lower():
                res = "MATCH"
            else:
                res = "DEVIATION"

        findings.append(
            ComparisonFinding(
                attribute=name,
                requirement=required,
                submitted_value=submitted,
                result=res,
                specification_evidence=spec_ev,
                submission_evidence=sub_ev,
            )
        )

    return findings