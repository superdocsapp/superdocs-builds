import json
from pathlib import Path


REPORT_STATE = Path("report_state.json")


STAGES = [
    "draft",
    "editorial_review",
    "finance_review",
    "legal_review",
    "approved",
]


def load_state():
    if not REPORT_STATE.exists():
        raise FileNotFoundError(
            "report_state.json not found."
        )

    with open(
        REPORT_STATE,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def save_state(state):
    with open(
        REPORT_STATE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False,
        )


def print_documents(state):
    documents = state.get("documents", {})

    print("\n" + "-" * 70)
    print("CURRENT REVIEW STATE")
    print("-" * 70)

    for index, (name, document) in enumerate(
        documents.items(),
        start=1,
    ):
        print(
            f"{index}. {name}"
        )
        print(
            f"   Stage:      {document.get('stage', 'unknown')}"
        )
        print(
            f"   Document ID: {document.get('document_id', 'unknown')}"
        )


def update_document_stage(state):
    documents = state.get("documents", {})

    document_names = list(documents.keys())

    print("\n" + "-" * 70)
    print("SELECT DOCUMENT")
    print("-" * 70)

    for index, name in enumerate(
        document_names,
        start=1,
    ):
        current_stage = documents[name].get(
            "stage",
            "unknown",
        )

        print(
            f"{index}. {name} "
            f"(current: {current_stage})"
        )

    print()

    try:
        document_choice = int(
            input("Select document [number]: ").strip()
        )
    except ValueError:
        print("\n✗ Invalid document selection.")
        return False

    if not (
        1 <= document_choice <= len(document_names)
    ):
        print("\n✗ Invalid document selection.")
        return False

    document_name = document_names[
        document_choice - 1
    ]

    document = documents[document_name]

    current_stage = document.get(
        "stage",
        "unknown",
    )

    print("\n" + "-" * 70)
    print("SELECT NEW REVIEW STAGE")
    print("-" * 70)

    for index, stage in enumerate(
        STAGES,
        start=1,
    ):
        marker = ""

        if stage == current_stage:
            marker = "  ← current"

        print(
            f"{index}. {stage}{marker}"
        )

    print()

    try:
        stage_choice = int(
            input("Select stage [number]: ").strip()
        )
    except ValueError:
        print("\n✗ Invalid stage selection.")
        return False

    if not (
        1 <= stage_choice <= len(STAGES)
    ):
        print("\n✗ Invalid stage selection.")
        return False

    new_stage = STAGES[
        stage_choice - 1
    ]

    if new_stage == current_stage:
        print(
            f"\nNo change required. "
            f"{document_name} is already in "
            f"'{current_stage}'."
        )
        return False

    print("\n" + "-" * 70)
    print("REVIEW STATE CHANGE")
    print("-" * 70)

    print(
        f"Document: {document_name}"
    )

    print(
        f"Current stage: {current_stage}"
    )

    print(
        f"New stage:     {new_stage}"
    )

    print(
        "\nSave this change? [y/N]: ",
        end="",
    )

    confirmation = (
        input()
        .strip()
        .lower()
    )

    if confirmation != "y":
        print("\n✗ Change cancelled.")
        return False

    document["stage"] = new_stage

    save_state(state)

    print("\n✓ Review state updated.")
    print(
        f"  Document: {document_name}"
    )
    print(
        f"  Changed:  {current_stage} → {new_stage}"
    )
    print(
        f"  Saved to: {REPORT_STATE}"
    )

    return True


def main():

    print("\n" + "=" * 70)
    print("ANNUAL REPORT REVIEW STATE")
    print("=" * 70)

    state = load_state()

    print(
        f"\nReport: "
        f"{state.get('report_title', 'Annual Report')}"
    )

    print_documents(state)

    print("\n" + "-" * 70)
    print("REVIEW STATE ACTION")
    print("-" * 70)

    print("1. Change document review stage")
    print("2. Exit")

    print()

    choice = input(
        "Select action [1/2]: "
    ).strip()

    if choice == "1":
        update_document_stage(state)

    elif choice == "2":
        print("\nNo changes made.")

    else:
        print("\n✗ Invalid selection.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()