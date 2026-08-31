import json
from pathlib import Path
from datetime import datetime, timezone


STATE_FILE = Path(__file__).parent / "report_state.json"


REVIEW_STAGES = [
    "draft",
    "editorial_review",
    "finance_review",
    "legal_review",
    "approved",
]


def load_state():
    """Load the persistent annual report state."""

    if not STATE_FILE.exists():
        raise FileNotFoundError(
            f"Missing state file: {STATE_FILE}"
        )

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    """Persist report state so it survives reloads."""

    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def set_stage(section, stage):
    """Move a report section to a new review stage."""

    if stage not in REVIEW_STAGES:
        raise ValueError(
            f"Invalid stage '{stage}'. "
            f"Choose from: {', '.join(REVIEW_STAGES)}"
        )

    state = load_state()

    if section not in state["documents"]:
        raise ValueError(
            f"Unknown report section: '{section}'"
        )

    state["documents"][section]["stage"] = stage
    state["documents"][section]["updated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    save_state(state)

    return state


def get_report_status():
    """Print the current review status."""

    state = load_state()

    print("\n" + "=" * 70)
    print(state["report_title"])
    print("REVIEW STATUS")
    print("=" * 70)

    for section, document in state["documents"].items():
        print(f"\n{section}")
        print(f"  Document ID: {document['document_id']}")
        print(f"  Stage:       {document['stage']}")
        print(
            f"  Updated:     "
            f"{document.get('updated_at', state.get('updated_at'))}"
        )

    print("\n" + "=" * 70)

    return state


if __name__ == "__main__":
    get_report_status()