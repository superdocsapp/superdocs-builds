from pathlib import Path
import json

from docx import Document


BASE_DIR = Path("sample_documents")


def create_scenario_a() -> None:
    output_dir = BASE_DIR / "scenario_a"
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    doc = Document()

    doc.add_heading(
        "Random sales call notes",
        level=1,
    )

    doc.add_paragraph(
        "- It's too expensive"
    )
    doc.add_paragraph(
        "resp: Start with a small pilot rather than a full rollout."
    )

    doc.add_paragraph(
        "* SECURITY???"
    )
    doc.add_paragraph(
        "We encrypt data in transit and at rest."
    )

    doc.add_paragraph(
        '"We already use another vendor"'
    )
    doc.add_paragraph(
        "-> Migration can be phased alongside the existing workflow."
    )

    doc.add_paragraph(
        "• Implementation looks complicated"
    )
    # Deliberately no response.

    doc.add_paragraph(
        "what about support?"
    )
    doc.add_paragraph(
        "A: Support is available during onboarding."
    )

    doc.add_paragraph(
        "- Our team is too small"
    )
    doc.add_paragraph(
        "Response: Start with a limited team and expand later."
    )

    doc.save(
        output_dir
        / "messy_objection_notes.docx"
    )

    ground_truth = {
        "scenario_id": "SCENARIO-A",
        "expected_objection_count": 6,
        "expected_complete_count": 5,
        "expected_missing_response_count": 1,
        "expected_dropped_count": 0,
        "entries": [
            {
                "objection": "It's too expensive",
                "response": (
                    "Start with a small pilot rather than a full rollout."
                ),
            },
            {
                "objection": "SECURITY???",
                "response": (
                    "We encrypt data in transit and at rest."
                ),
            },
            {
                "objection": "We already use another vendor",
                "response": (
                    "Migration can be phased alongside the existing workflow."
                ),
            },
            {
                "objection": "Implementation looks complicated",
                "response": None,
            },
            {
                "objection": "what about support?",
                "response": (
                    "Support is available during onboarding."
                ),
            },
            {
                "objection": "Our team is too small",
                "response": (
                    "Start with a limited team and expand later."
                ),
            },
        ],
    }

    (
        output_dir
        / "ground_truth.json"
    ).write_text(
        json.dumps(
            ground_truth,
            indent=2,
        ),
        encoding="utf-8",
    )


def create_scenario_b() -> None:
    output_dir = BASE_DIR / "scenario_b"
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    doc = Document()

    doc.add_heading(
        "Q4 notes - messy version",
        level=1,
    )

    doc.add_paragraph(
        "OBJ: Budget is frozen"
    )
    doc.add_paragraph(
        "ANS: Revisit the conversation in Q4."
    )

    doc.add_paragraph(
        '"Already using Competitor X"'
    )
    doc.add_paragraph(
        "→ Migration can be phased."
    )

    doc.add_paragraph(
        "- Worried about onboarding"
    )
    # Deliberately missing response.

    doc.add_paragraph(
        "* Need training?"
    )
    doc.add_paragraph(
        "answer: Training is included during onboarding."
    )

    doc.save(
        output_dir
        / "different_format_notes.docx"
    )

    ground_truth = {
        "scenario_id": "SCENARIO-B",
        "expected_objection_count": 4,
        "expected_complete_count": 3,
        "expected_missing_response_count": 1,
        "expected_dropped_count": 0,
        "entries": [
            {
                "objection": "Budget is frozen",
                "response": (
                    "Revisit the conversation in Q4."
                ),
            },
            {
                "objection": "Already using Competitor X",
                "response": (
                    "Migration can be phased."
                ),
            },
            {
                "objection": "Worried about onboarding",
                "response": None,
            },
            {
                "objection": "Need training?",
                "response": (
                    "Training is included during onboarding."
                ),
            },
        ],
    }

    (
        output_dir
        / "ground_truth.json"
    ).write_text(
        json.dumps(
            ground_truth,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    create_scenario_a()
    create_scenario_b()

    print("Scenario A generated:")
    print(
        "  6 objections / "
        "5 responses / "
        "1 missing"
    )

    print()
    print("Scenario B generated:")
    print(
        "  4 objections / "
        "3 responses / "
        "1 missing"
    )


if __name__ == "__main__":
    main()