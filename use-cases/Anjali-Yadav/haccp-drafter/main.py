"""
HACCP / food-safety-plan drafter.

Usage:
    python main.py "Chicken Nuggets"
        # starts a new plan, REPL mode

    python main.py "Chicken Nuggets" --batch entries.json
        # non-interactive, for demos/tests

Each entry you describe becomes one chat turn against a SINGLE long-lived
session — SuperDocs' own chat/session history IS the versioning (each turn
is a new state you could revert to), so no separate versioning system is
built here; the task's "versions it as the process evolves" requirement
is satisfied by session continuity, not a bolt-on version table.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared modules
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import (  # noqa: E402
    get_budget_floor,
    get_required_api_key,
    load_environment,
)
from common.run_state import RunState, state_path_for  # noqa: E402
from common.superdocs_client import (  # noqa: E402
    BudgetExceeded,
    OperationBudget,
    SuperDocsClient,
)
from template import (  # noqa: E402
    build_template_html,
    chat_instruction_for_entry,
    classify,
    verify_professional_review_note_present,
    verify_entry_placement,
)


# ---------------------------------------------------------------------------
# SuperDocs client
# ---------------------------------------------------------------------------

def make_client() -> SuperDocsClient:
    """
    Create an authenticated SuperDocs client.

    The API key is loaded from the application's .env file by main()
    before this function is called.

    We intentionally do NOT fall back to self-signup here.

    Rationale:
    - A configured API key means the user already has a SuperDocs account.
    - Falling back to signup when .env loading fails masks configuration bugs.
    - Self-signup now requires explicit terms acceptance.
    - Authentication/configuration should fail clearly rather than silently
      creating another account.
    """
    api_key = get_required_api_key()

    budget = OperationBudget(
        floor=get_budget_floor()
    )

    return SuperDocsClient(
        api_key,
        budget=budget,
    )


# ---------------------------------------------------------------------------
# HACCP entry processing
# ---------------------------------------------------------------------------

def add_entry(
    client: SuperDocsClient,
    session_id: str,
    step: str,
    hazard: str,
    approve_all: bool = False,
) -> dict:
    """
    Add one HACCP process step to the long-lived SuperDocs session.

    The local classifier provides a non-authoritative hint. SuperDocs'
    response remains the source of the actual document placement decision.
    """
    hint = classify(f"{step} {hazard}")
    instruction = chat_instruction_for_entry(step, hazard, hint)

    result = client.chat_with_review(
        session_id,
        instruction,
        approve_all=approve_all,
    )

    placed_text = result.get("response", "")

    # Post-hoc sanity check:
    #
    # Does the AI response mention a DIFFERENT section than our local hint
    # predicted?
    #
    # This is surfaced as a flag for the user to review. It never
    # automatically overrides the SuperDocs placement decision.
    from template import SECTION_TITLES

    hint_title = SECTION_TITLES[hint.best_section]

    other_titles = [
        title
        for section, title in SECTION_TITLES.items()
        if section != hint.best_section
    ]

    mentions_other_section = any(
        title.split(" (")[0] in placed_text
        for title in other_titles
    )

    mentions_hint_section = (
        hint_title.split(" (")[0] in placed_text
    )

    disagreement_flag = None

    if (
        hint.confidence != "none"
        and mentions_other_section
        and not mentions_hint_section
    ):
        disagreement_flag = (
            f"Local heuristic expected '{hint_title}' but the AI's "
            f"response references a different section — worth a manual "
            f"glance to confirm placement."
        )

    remaining = result.get("usage", {}).get("monthly_remaining")

    return {
        "step": step,
        "hazard": hazard,
        "local_hint": hint.best_section,
        "hint_confidence": hint.confidence,
        "ai_response": placed_text,
        "disagreement_flag": disagreement_flag,
        "operations_remaining": remaining,
        "approved": bool(result.get("review_committed")),
        "approval_status": "committed" if result.get("review_committed") else "no_change",
    }


# ---------------------------------------------------------------------------
# Export + verification
# ---------------------------------------------------------------------------

def export_and_verify(
    client: SuperDocsClient,
    session_id: str,
    out_dir: Path,
    entries: list[dict] | None = None,
) -> bool:
    """
    Export the final HACCP plan and verify that the professional-review
    disclaimer survived into the exported document.
    """
    docx_path = out_dir / "haccp_plan.docx"
    pdf_path = out_dir / "haccp_plan.pdf"

    client.export(
        session_id,
        "docx",
        str(docx_path),
    )

    client.export(
        session_id,
        "pdf",
        str(pdf_path),
    )

    # Verify the disclaimer literally, rather than trusting the AI's
    # response that it would preserve it.
    #
    # ASSUMPTION FLAGGED:
    # We verify against a markdown export because it is plain text and
    # straightforward to inspect. If markdown is not supported by the
    # production API, this should be replaced with another supported
    # read/export mechanism.
    md_path = out_dir / "haccp_plan_verify.md"

    client.export(
        session_id,
        "markdown",
        str(md_path),
    )

    content = md_path.read_text(
        encoding="utf-8"
    )

    if entries:
        placement_report = []
        for entry in entries:
            hint = classify(f"{entry['step']} {entry['hazard']}")
            placement_report.append(
                {
                    "step": entry["step"],
                    "expected_section": hint.best_section,
                    "found_under_expected_section": verify_entry_placement(
                        content,
                        entry["step"],
                        hint.best_section,
                    ),
                    "requires_professional_review": True,
                }
            )
        (out_dir / "haccp_placement_verification.json").write_text(
            json.dumps(placement_report, indent=2),
            encoding="utf-8",
        )

    return verify_professional_review_note_present(content)


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draft a HACCP / food-safety plan using SuperDocs."
    )

    parser.add_argument(
        "product_name",
        help="Product name, e.g. 'Chicken Nuggets'",
    )

    parser.add_argument(
        "--batch",
        help=(
            "JSON file containing [{step, hazard}, ...] "
            "for non-interactive runs"
        ),
    )

    parser.add_argument(
        "--out-dir",
        default="./output",
        help="Directory where exported files and run state are stored",
    )

    parser.add_argument(
        "--restart",
        action="store_true",
        help=(
            "Ignore saved progress for this product+batch and start fresh "
            "(batch mode only; default behavior RESUMES automatically from "
            "a prior run's state file)"
        ),
    )
    parser.add_argument(
        "--approve-all",
        action="store_true",
        help="Approve every proposal without prompting (use only in automation)",
    )

    parser.add_argument(
        "--list-versions",
        action="store_true",
        help=(
            "Show this plan's version history via SuperDocs' "
            "session history and exit"
        ),
    )

    parser.add_argument(
        "--revert-to",
        type=int,
        default=None,
        metavar="TURN_INDEX",
        help="Revert this plan to an earlier turn index and exit",
    )

    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------------
    app_dir = Path(__file__).resolve().parent
    load_environment(app_dir)

    # Create the authenticated client only after .env has been loaded.
    #
    # If the key is missing, get_required_api_key() raises a clear
    # configuration error instead of silently attempting self-signup.
    try:
        client = make_client()
    except RuntimeError as exc:
        print(f"\nConfiguration error: {exc}", file=sys.stderr)
        print(
            "\nSet SUPERDOCS_API_KEY in one of these ways:",
            file=sys.stderr,
        )
        print(
            "  1. Add it to haccp-drafter/.env",
            file=sys.stderr,
        )
        print(
            "  2. Set it as a PowerShell environment variable:",
            file=sys.stderr,
        )
        print(
            '     $env:SUPERDOCS_API_KEY="your-api-key"',
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    # -----------------------------------------------------------------------
    # Output directory
    # -----------------------------------------------------------------------
    out_dir = Path(args.out_dir)
    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -----------------------------------------------------------------------
    # Resume state
    # -----------------------------------------------------------------------
    if args.batch:
        # Idempotency for batch mode:
        #
        # The state key is based on both product name and the actual batch
        # file contents. Re-running the same batch therefore resumes and
        # skips entries that were already approved instead of paying for
        # them again.
        batch_content = Path(args.batch).read_text(
            encoding="utf-8"
        )

        content_key = hashlib.sha256(
            f"{args.product_name}:{batch_content}".encode()
        ).hexdigest()

        state = RunState(
            state_path_for(
                out_dir,
                content_key,
            )
        )

        if args.restart:
            state.reset()

            state = RunState(
                state_path_for(
                    out_dir,
                    content_key,
                )
            )

    else:
        content_key = hashlib.sha256(
            f"interactive:{args.product_name}".encode()
        ).hexdigest()
        state = RunState(state_path_for(out_dir, content_key))

        if args.restart:
            state.acquire_lock()
            state.reset()
        else:
            state.acquire_lock()
            state.reload()

    if state._lock_file is None:
        state.acquire_lock()
        state.reload()
    atexit.register(state.release_lock)

    # -----------------------------------------------------------------------
    # Create or resume SuperDocs session
    # -----------------------------------------------------------------------
    if state and state.session_id:
        session_id = state.session_id

        print(
            f"Resuming existing plan session {session_id} "
            f"({state.completed_count} entries already done)"
        )

    else:
        session_id = f"haccp-{uuid.uuid4()}"

        initial_html = build_template_html(
            args.product_name
        )

        # Templates surface:
        #
        # Register the blank HACCP skeleton as a reusable SuperDocs template,
        # rather than only creating a one-off document.
        #
        # This allows future plans to start from a reusable skeleton.
        try:
            tmpl_result = client.upload_template(
                f"haccp-skeleton-{args.product_name}",
                initial_html,
            )

            print(
                "Registered as reusable template: "
                f"{tmpl_result.get('template_id', tmpl_result)}"
            )

        except Exception as exc:  # noqa: BLE001
            print(
                f"Template registration failed ({exc}) — "
                "continuing with a plain document instead. "
                "See the ASSUMPTION FLAGGED comment on "
                "upload_template() in superdocs_client.py."
            )

        client.upload(
            f"{args.product_name}_haccp_plan.html",
            initial_html,
            session_id,
        )

        if state:
            state.set_session_id(session_id)

        print(
            f"Started HACCP plan for '{args.product_name}', "
            f"session {session_id}"
        )

    # -----------------------------------------------------------------------
    # Version history
    # -----------------------------------------------------------------------
    if args.list_versions:
        try:
            history = client.get_session_history(
                session_id
            )

            print(
                f"\n{len(history)} version(s) in this plan's history:"
            )

            for turn in history:
                print(f"  {turn}")

        except Exception as exc:  # noqa: BLE001
            print(
                f"Could not fetch version history ({exc}). "
                "See the ASSUMPTION FLAGGED comment on "
                "get_session_history() in superdocs_client.py."
            )

        return

    # -----------------------------------------------------------------------
    # Revert
    # -----------------------------------------------------------------------
    if args.revert_to is not None:
        result = client.revert(
            session_id,
            turn_index=args.revert_to,
        )

        print(
            f"Reverted to turn {args.revert_to}: {result}"
        )

        return

    # -----------------------------------------------------------------------
    # Process entries
    # -----------------------------------------------------------------------
    log = []
    failed_entries = []
    entries = []

    try:
        if args.batch:
            entries = json.loads(
                Path(args.batch).read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(entries, list):
                raise ValueError(
                    "Batch JSON must contain a list of entries."
                )

            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"Batch entry {i} must be a JSON object."
                    )

                if "step" not in entry or "hazard" not in entry:
                    raise ValueError(
                        f"Batch entry {i} must contain "
                        "'step' and 'hazard'."
                    )

                entry_key = (
                    f"entry-{i}-{entry['step']}"
                )

                if state.is_completed(entry_key):
                    print(
                        f"\n--- {entry['step']} "
                        "(already done, skipping) ---"
                    )
                    continue

                print(
                    f"\n--- {entry['step']} ---"
                )

                try:
                    result = add_entry(
                        client,
                        session_id,
                        entry["step"],
                        entry["hazard"],
                        args.approve_all,
                    )

                    log.append(result)

                    print(
                        f"  local hint: "
                        f"{result['local_hint']} "
                        f"({result['hint_confidence']})"
                    )

                    if result["disagreement_flag"]:
                        print(
                            f"  FLAG: "
                            f"{result['disagreement_flag']}"
                        )

                    if not result["approved"]:
                        failed_entries.append((entry["step"], result["approval_status"]))
                        continue

                    # Save immediately.
                    #
                    # If the NEXT entry fails or the process crashes,
                    # this completed entry remains resumable.
                    state.mark_completed(entry_key)

                except BudgetExceeded:
                    raise

                except Exception as exc:  # noqa: BLE001
                    # Graceful degradation:
                    #
                    # One problematic entry should not kill the entire
                    # batch. The failed entry is logged and the next entry
                    # is attempted.
                    print(
                        f"  ENTRY FAILED, "
                        f"continuing to next: {exc}"
                    )

                    failed_entries.append(
                        (
                            entry["step"],
                            str(exc),
                        )
                    )

        else:
            print(
                "Describe process steps one at a time. "
                "Empty step name to finish.\n"
            )

            while True:
                step = input(
                    "Process step: "
                ).strip()

                if not step:
                    break

                hazard = input(
                    "Hazard/detail: "
                ).strip()

                entry_key = "entry-" + hashlib.sha256(
                    f"{step}\0{hazard}".encode()
                ).hexdigest()
                if state.is_completed(entry_key):
                    print("  already approved in this interactive plan; skipping.")
                    continue

                result = add_entry(
                    client,
                    session_id,
                    step,
                    hazard,
                    args.approve_all,
                )

                log.append(result)
                entries.append({"step": step, "hazard": hazard})

                print(
                    f"  -> {result['ai_response'][:200]}"
                )

                if result["disagreement_flag"]:
                    print(
                        f"  FLAG: "
                        f"{result['disagreement_flag']}"
                    )

                if result["approved"]:
                    state.mark_completed(entry_key)

    except BudgetExceeded as exc:
        print(
            f"\nSTOPPING EARLY: {exc}"
        )

        if args.batch:
            print(
                "Re-run the same command to resume — "
                "already-completed entries will be skipped."
            )

    # -----------------------------------------------------------------------
    # Export + verification
    # -----------------------------------------------------------------------
    note_survived = export_and_verify(
        client,
        session_id,
        out_dir,
        entries,
    )

    log_path = out_dir / "session_log.json"

    log_path.write_text(
        json.dumps(
            {
                "entries": log,
                "failed_entries": failed_entries,
                "professional_review_note_verified": note_survived,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Final report
    # -----------------------------------------------------------------------
    print(
        f"\nExported to "
        f"{out_dir}/haccp_plan.docx and .pdf"
    )

    print(
        "Professional-review disclaimer present in export: "
        f"{note_survived}"
    )

    if not note_survived:
        print(
            "WARNING: the disclaimer did not survive to export — "
            "check the plan manually before using it."
        )

    print(
        f"Session log: {log_path}"
    )


if __name__ == "__main__":
    main()