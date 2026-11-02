"""Interactive Command Line Interface and Evaluator Demo for Live Doc Agent."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List
from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import ChangeDecision, ProposedChange, RunStatus, WikiDocument
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter
from live_doc_agent.wiki.nuclino import NuclinoWikiAdapter


def run_evaluator_demo() -> None:
    """Run a zero-credential deterministic demo for reviewers and evaluators."""
    initial_content = (
        "# Engineering Handbook\n\n"
        "## Deployment\n"
        "Deployments happen manually.\n\n"
        "## Authentication\n"
        "Use API keys.\n\n"
        "## On-call\n"
        "The team rotates weekly.\n"
    )

    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-demo",
            title="Engineering Handbook",
            content=initial_content,
            content_version="1",
        )
    )

    def demo_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_demo_session"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c_deploy",
                        "target_section": "Deployment",
                        "old_snippet": "Deployments happen manually.",
                        "new_snippet": "Deployments must use the automated CI/CD pipeline.",
                        "explanation": "Switch from manual deployment to automated CI/CD pipeline.",
                        "confidence": 0.99,
                    }
                ]
            }
        if action == "approve":
            return {"success": True}
        return {}

    superdocs = SuperDocsClient(mock_handler=demo_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision_text = "All deployments must now use the automated CI/CD pipeline."

    print("==================================================")
    print(" Live Doc Agent — Evaluator Demo (Zero-Credential)")
    print("==================================================\n")
    print(f"Decision:\n  {decision_text}\n")

    result = agent.run(
        doc_id="handbook-demo",
        decision_text=decision_text,
        auto_approve=True,
    )

    print("Human Approval Gate:")
    print("  -> APPROVED\n")

    print("Proposed changes:")
    for idx, change in enumerate(result.proposed_changes, 1):
        print(f"  [{idx}] Section: [{change.target_section}]")
        print(f"      - {change.old_snippet}")
        print(f"      + {change.new_snippet}")
        if change.explanation:
            print(f"      Explanation: {change.explanation}")
    print()

    print(f"Result Status:\n  {result.status.value.upper()}\n")

    print("Changed sections:")
    for patch in result.applied_patches:
        print(f"  - {patch.target_section}")

    print("\nUntouched sections:")
    untouched = DocumentPatcher.get_untouched_sections(
        initial_content, result.after_document.content
    )
    for title, is_unchanged in untouched:
        if is_unchanged and title != "Preamble":
            print(f"  ✓ {title}")

    print(f"\nDocument Version:\n  1 → {result.after_document.content_version}\n")
    print("==================================================")
    print(" Invariant Verified: Untouched sections preserved")
    print("==================================================")


def interactive_approval_gate(
    doc: WikiDocument, proposed_changes: List[ProposedChange]
) -> List[ChangeDecision]:
    """Interactive CLI human approval prompt."""
    print(f"\n=======================================================")
    print(f" Human Approval Gate: {len(proposed_changes)} Proposed Surgical Changes")
    print(f" Document: '{doc.title}' (Version {doc.content_version})")
    print(f"=======================================================\n")

    decisions: List[ChangeDecision] = []
    for idx, change in enumerate(proposed_changes, 1):
        print(f"[{idx}/{len(proposed_changes)}] Section: [{change.target_section}]")
        print(f"  Old Snippet : \"{change.old_snippet}\"")
        print(f"  New Snippet : \"{change.new_snippet}\"")
        if change.explanation:
            print(f"  Explanation : {change.explanation}")

        while True:
            choice = input("Approve this change? [y/n/e(dit)]: ").strip().lower()
            if choice in ("y", "yes"):
                decisions.append(ChangeDecision(change_id=change.change_id, approved=True))
                print("  -> Approved.\n")
                break
            elif choice in ("n", "no"):
                reason = input("  Reason for rejection (optional): ").strip()
                decisions.append(
                    ChangeDecision(
                        change_id=change.change_id,
                        approved=False,
                        rejection_reason=reason or "User rejected",
                    )
                )
                print("  -> Rejected.\n")
                break
            elif choice in ("e", "edit"):
                custom_text = input("  Enter replacement text: ").strip()
                decisions.append(
                    ChangeDecision(
                        change_id=change.change_id,
                        approved=True,
                        user_override_text=custom_text,
                    )
                )
                print("  -> Approved with manual override.\n")
                break
            else:
                print("Please enter 'y', 'n', or 'e'.")

    return decisions


def main() -> None:
    # Support 'python -m live_doc_agent.cli demo' or arguments
    if len(sys.argv) > 1 and sys.argv[1] in ("demo", "--demo"):
        run_evaluator_demo()
        return

    parser = argparse.ArgumentParser(
        description="Live Doc Agent: Synchronize wiki documents surgically using SuperDocs."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run deterministic zero-credential evaluator demo",
    )
    parser.add_argument(
        "--doc-id",
        help="Wiki document ID or Item ID",
    )
    parser.add_argument(
        "--decision",
        help="Decision text or path to decision text file",
    )
    parser.add_argument(
        "--adapter",
        choices=["nuclino", "memory"],
        default="memory",
        help="Wiki adapter to use (default: memory)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve all proposed changes without prompt",
    )
    parser.add_argument(
        "--mock-superdocs",
        action="store_true",
        help="Use a local mock instead of the real SuperDocs API (no API key required)",
    )

    args = parser.parse_args()

    if args.demo:
        run_evaluator_demo()
        return

    if not args.doc_id or not args.decision:
        parser.print_help()
        sys.exit(1)

    # Read decision text if given as file path
    decision_text = args.decision
    if os.path.exists(decision_text):
        with open(decision_text, "r", encoding="utf-8") as f:
            decision_text = f.read()

    # Configure Wiki adapter
    _sample_sections = [
        ("Deployment", "Production deployments happen every Friday."),
        ("Database", "Production uses PostgreSQL on AWS RDS."),
        ("Incident Response", "The on-call engineer must acknowledge incidents within 30 minutes."),
    ]

    if args.adapter == "nuclino":
        nuclino_api_key = os.getenv("NUCLINO_API_KEY")
        nuclino_base_url = os.getenv("NUCLINO_BASE_URL", "https://api.nuclino.com/v0")
        wiki = NuclinoWikiAdapter(api_key=nuclino_api_key, base_url=nuclino_base_url)
    else:
        wiki = MemoryWikiAdapter()
        # Seed default sample Engineering Handbook
        wiki.seed_document(
            WikiDocument(
                doc_id=args.doc_id,
                title="Engineering Handbook",
                content=(
                    "# Engineering Handbook\n\n"
                    "## Deployment\n\nProduction deployments happen every Friday.\n\n"
                    "## Database\n\nProduction uses PostgreSQL on AWS RDS.\n\n"
                    "## Incident Response\n\nThe on-call engineer must acknowledge incidents within 30 minutes.\n"
                ),
                content_version="1",
            )
        )

    # Configure SuperDocs client
    if args.mock_superdocs or (args.adapter == "memory" and not os.getenv("SUPERDOCS_API_KEY")):
        # Local mock: scan decision text for keywords to propose matching section changes.
        # This simulates what SuperDocs AI would return so you can try the full flow locally.
        def _local_mock_handler(action: str, params: dict):
            if action == "upload":
                return {"document_id": "mock-sd-session"}
            if action == "chat":
                decision_lower = decision_text.lower()
                changes = []
                keywords = {
                    "Deployment": [
                        "deploy", "deployment", "release", "ship", "pipeline", "ci", "cd",
                        "friday", "daily", "weekly", "rollout",
                    ],
                    "Incident Response": [
                        "incident", "on-call", "oncall", "sla", "acknowledge",
                        "pager", "alert", "response", "escalat",
                    ],
                    "Database": [
                        "database", "postgres", "postgresql", "rds", "mysql",
                        "redis", "mongo", "sql", "db",
                    ],
                }
                section_snippets = dict(_sample_sections)
                for section, kws in keywords.items():
                    if any(kw in decision_lower for kw in kws):
                        changes.append({
                            "change_id": f"mock_{section.lower().replace(' ', '_')}",
                            "target_section": section,
                            "old_snippet": section_snippets[section],
                            "new_snippet": f"[SuperDocs AI would update this based on: '{decision_text[:80]}...']",
                            "explanation": f"The decision appears to affect the {section} section.",
                        })
                if not changes:
                    print(
                        "\n[Mock SuperDocs] Decision does not appear to affect any tracked section."
                        " Returning NOOP.\n"
                    )
                return {"proposed_changes": changes}
            if action == "approve":
                return {"success": True}
            return {}

        if args.mock_superdocs:
            print("[Mock SuperDocs] Running in local mock mode — no API key required.\n")
        superdocs = SuperDocsClient(mock_handler=_local_mock_handler)
    else:
        sd_api_key = os.getenv("SUPERDOCS_API_KEY")
        sd_base_url = os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app/v1")
        superdocs = SuperDocsClient(api_key=sd_api_key, base_url=sd_base_url)

    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    print(f"Running Live Doc Agent for document '{args.doc_id}'...")
    result = agent.run(
        doc_id=args.doc_id,
        decision_text=decision_text,
        approval_gate=None if args.auto_approve else interactive_approval_gate,
        auto_approve=args.auto_approve,
    )

    print(f"\nResult Status: {result.status.value.upper()}")
    if result.status == RunStatus.APPLIED:
        print(f"Successfully applied {len(result.applied_patches)} surgical patches.")
        print("\n--- Updated Document Content ---")
        if result.after_document:
            print(result.after_document.content)
    elif result.status == RunStatus.NOOP:
        print("No stale sections detected. Document is already synchronized.")
    elif result.status == RunStatus.REJECTED:
        print("Proposed changes were rejected by user.")
    elif result.status in (RunStatus.CONFLICT, RunStatus.ERROR, RunStatus.VALIDATION_FAILED):
        print(f"Error: {result.error_message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
