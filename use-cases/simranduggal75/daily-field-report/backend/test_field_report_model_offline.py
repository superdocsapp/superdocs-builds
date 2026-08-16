"""
Offline pytest tests for FieldReportData / DelayEntry pure-logic
validators. No network calls, no SUPERDOCS_API_KEY required.

Covers:
- cause_category: exact vocabulary, synonym mapping, unknown fallback
- safety_observations: dict-shape coercion (the exact payload captured
  from a live SuperDocs extraction failure), plain-string passthrough,
  unrecognized shapes, empty input
"""

from app.models.field_report import DelayEntry, FieldReportData


# ---------------------------------------------------------------------
# cause_category
# ---------------------------------------------------------------------


def test_cause_category_exact_vocabulary_passes_through():
    for category in (
        "weather",
        "equipment_failure",
        "material_delay",
        "labor_shortage",
        "permitting_inspection",
        "design_coordination",
        "site_conditions",
        "other",
    ):
        entry = DelayEntry(description="x", cause_category=category)
        assert entry.cause_category == category


def test_cause_category_known_synonyms_map_to_closed_vocabulary():
    cases = {
        "rain": "weather",
        "Weather delay": "weather",
        "WEATHER": "weather",
        "hydraulic issue": "equipment_failure",
        "machine breakdown": "equipment_failure",
        "material delay": "material_delay",
        "labour shortage": "labor_shortage",
        "permit": "permitting_inspection",
        "rfi": "design_coordination",
        "site access": "site_conditions",
    }
    for raw, expected in cases.items():
        entry = DelayEntry(description="x", cause_category=raw)
        assert entry.cause_category == expected, f"{raw!r} -> {entry.cause_category!r}"


def test_cause_category_unrecognized_value_falls_back_to_other():
    entry = DelayEntry(description="x", cause_category="some totally novel unmapped cause")
    assert entry.cause_category == "other"


def test_cause_category_non_string_value_falls_back_to_other_without_raising():
    entry = DelayEntry(description="x", cause_category=12345)
    assert entry.cause_category == "other"


def test_cause_category_none_and_empty_string_stay_none():
    assert DelayEntry(description="x", cause_category=None).cause_category is None
    assert DelayEntry(description="x", cause_category="").cause_category is None


# ---------------------------------------------------------------------
# safety_observations
# ---------------------------------------------------------------------


def _minimal_report(**overrides) -> dict:
    base = {
        "project": None,
        "report_date": None,
        "total_headcount": None,
        "manpower": [],
        "equipment": [],
        "work_by_area": [],
        "weather": None,
        "delays": [],
        "safety_observations": [],
        "source_notes": "x",
    }
    base.update(overrides)
    return base


def test_safety_observations_coerces_the_exact_live_failure_payload():
    # Captured verbatim from a real SuperDocs extraction response that
    # crashed the whole report before this fix.
    malformed = _minimal_report(
        safety_observations=[{"observation": "All workers wore PPE."}]
    )
    report = FieldReportData.model_validate(malformed)
    assert report.safety_observations == ["All workers wore PPE."]


def test_safety_observations_plain_strings_pass_through_unchanged():
    data = _minimal_report(
        safety_observations=["All workers wore PPE.", "Hard hats required in Zone A."]
    )
    report = FieldReportData.model_validate(data)
    assert report.safety_observations == [
        "All workers wore PPE.",
        "Hard hats required in Zone A.",
    ]


def test_safety_observations_unrecognized_dict_shape_is_preserved_not_dropped():
    data = _minimal_report(
        safety_observations=[{"unexpected_key": "some safety note"}]
    )
    report = FieldReportData.model_validate(data)
    assert len(report.safety_observations) == 1
    assert "unexpected_key" in report.safety_observations[0]
    assert "some safety note" in report.safety_observations[0]


def test_safety_observations_empty_and_none_produce_empty_list():
    assert FieldReportData.model_validate(_minimal_report(safety_observations=[])).safety_observations == []
    assert FieldReportData.model_validate(_minimal_report(safety_observations=None)).safety_observations == []


def test_safety_observations_mixed_strings_and_dicts():
    data = _minimal_report(
        safety_observations=[
            "All workers wore PPE.",
            {"observation": "Hard hats required."},
            {"text": "Fall protection in use."},
        ]
    )
    report = FieldReportData.model_validate(data)
    assert report.safety_observations == [
        "All workers wore PPE.",
        "Hard hats required.",
        "Fall protection in use.",
    ]
