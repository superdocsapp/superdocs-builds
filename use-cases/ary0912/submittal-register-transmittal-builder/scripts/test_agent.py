import sys
from pathlib import Path

# Add the backend directory to Python's import path.
# This allows imports from the backend app package when the script is run
# from the project root.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.agents.runtime import workflow


def main():
    result = workflow.invoke(
        {
            "project_id": "BROD-2026",
            "submittal_id": "SUB-001",
        },
        config={"configurable": {"thread_id": "test-agent-script"}},
    )

    print("\n=== WORKFLOW RESULT ===\n")

    print("Stage:")
    print(result.get("current_stage"))

    print("\nReview:")
    print(result.get("review_status"))

    print("\nFindings:")

    findings = result.get("findings", [])

    if not findings:
        print("No findings returned.")
        return

    for finding in findings:
        print("\n---")
        print("Attribute:", finding.get("attribute"))
        print("Requirement:", finding.get("requirement"))
        print("Submitted:", finding.get("submitted_value"))
        print("Result:", finding.get("result"))
        print("Specification:", finding.get("specification_evidence"))
        print("Submission:", finding.get("submission_evidence"))


if __name__ == "__main__":
    main()
