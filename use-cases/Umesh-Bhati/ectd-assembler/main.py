import argparse
import json
import os
import shutil
import sys

from requests.exceptions import RequestException

from client import SuperDocsClient, session_url
from diff_report import compare_section_exports
from hasher import get_file_hashes
from manifest import Manifest, detect_changed_sources, select_upload_target

STATE_FILE = "session_state.json"
FINAL_DOCX = "final_module2.docx"
PREVIOUS_DOCX = "final_module2.previous.docx"
SHELL_DOCX = "module2_shell.docx"
MANIFEST_PATH = "manifest.json"


def build_section_prompt(section_num: str, title: str, source_filenames: list[str]) -> str:
    heading = f"{section_num} {title}"
    sources = ", ".join(source_filenames)
    return (
        f"The document already contains a Heading 1 titled '{heading}'. "
        f"Replace ONLY the placeholder paragraph(s) directly under that existing heading with drafted body text. "
        f"Do NOT add a new heading, subheading, or duplicate of '{heading}' anywhere. "
        f"Do not modify any other section. "
        f"Use the attached Module 5 study report(s): {sources}. "
        f"Pull facts only from those sources. "
        f"For every drafted paragraph, add a citation pointing to the exact source report and section."
    )


def build_toc_prompt(section_headings: list[str]) -> str:
    headings = ", ".join(section_headings)
    return (
        "Update the 'Table of Contents' section near the top of the document. "
        "Replace the TOC placeholder with a readable list of all major section headings and their titles. "
        f"Include these sections: {headings}. "
        "Use plain text or a simple list — do not insert Word field codes. "
        "Do not change any section body text."
    )


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def print_diff_report(report) -> None:
    print("\nIncremental diff report:")
    print(f"  Expected to change: {', '.join(report.expected_changed) or '(none)'}")
    print(f"  Actually changed:   {', '.join(report.changed_sections) or '(none)'}")
    print(f"  Unchanged:          {', '.join(report.unchanged_sections) or '(none)'}")
    if report.proof_passed:
        print("  Proof: PASSED — only dependent sections changed.")
    else:
        print("  Proof: REVIEW NEEDED — changed sections do not match manifest dependencies.")


def run_pipeline(*, browser_review: bool) -> None:
    print("Starting eCTD Module 2 Assembler Pipeline...")
    client = SuperDocsClient()

    try:
        if not client.verify_connection():
            print("Error: Could not verify connection to SuperDocs API.")
            print("Tip: confirm SUPERDOCS_API_KEY is set and valid (GET /v1/sessions should return 200).")
            sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except RequestException as e:
        print(f"Error: Could not connect to SuperDocs API. ({e})")
        sys.exit(1)

    manifest = Manifest(MANIFEST_PATH)
    sources = manifest.get_all_sources()

    old_state = load_state()
    old_hashes = old_state.get("hashes", {})
    new_hashes = get_file_hashes(sources)
    changed_sources = detect_changed_sources(sources, old_hashes, new_hashes)

    print(f"Changed sources detected: {sorted(changed_sources) or '(none)'}")

    if not changed_sources:
        print("No changes detected in source documents. Exiting early.")
        return

    affected_sections = manifest.get_affected_sections(changed_sources)
    expected_changed_section_ids = [section_num for section_num, _, _ in affected_sections]

    if os.path.exists(FINAL_DOCX):
        shutil.copy(FINAL_DOCX, PREVIOUS_DOCX)
        print(f"Saved previous export to {PREVIOUS_DOCX} for diff proof.")

    upload_target = select_upload_target(FINAL_DOCX, SHELL_DOCX)
    if upload_target == FINAL_DOCX:
        print("Incremental run detected. Uploading previous export as the working document...")
    else:
        print("First run detected. Uploading module2_shell.docx as the working document...")

    try:
        bootstrap = client.bootstrap_session(upload_target, sorted(sources))
        session_id = bootstrap["session_id"]
        print(f"Session ready: {bootstrap['session_url']}")

        all_section_headings = [
            f"{num} {data['title']}" for num, data in manifest.sections.items()
        ]

        for section_num, title, section_sources in affected_sections:
            source_filenames = [os.path.basename(src) for src in section_sources]
            prompt = build_section_prompt(section_num, title, source_filenames)
            print(f"\nDrafting section {section_num} - {title}...")
            job_id = client.chat_async(session_id, prompt)
            print(f"  Job started: {job_id}")
            client.resolve_job(session_id, job_id, browser_review=browser_review)
            print(f"  Section {section_num} complete.")

        if affected_sections:
            print("\nUpdating table of contents...")
            toc_job_id = client.chat_async(session_id, build_toc_prompt(all_section_headings))
            client.resolve_job(session_id, toc_job_id, browser_review=browser_review)
            print("  Table of contents updated.")

        print("\nExporting final document...")
        client.export_document(session_id, FINAL_DOCX)
        print(f"Successfully exported to {FINAL_DOCX}.")

        if os.path.exists(PREVIOUS_DOCX):
            report = compare_section_exports(
                PREVIOUS_DOCX,
                FINAL_DOCX,
                manifest.get_all_section_ids(),
                expected_changed_section_ids,
            )
            print_diff_report(report)

        save_state(
            {
                "session_id": session_id,
                "document_id": bootstrap.get("document_id"),
                "attachments": bootstrap.get("attachments", {}),
                "hashes": new_hashes,
            }
        )
        print(f"Pipeline complete. State saved to {STATE_FILE}.")
        print(f"Open session: {session_url(session_id)}")

    except RequestException as e:
        print(f"\nPipeline failed due to API error: {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble eCTD Module 2 summaries from Module 5 study reports.")
    parser.add_argument(
        "--browser-review",
        action="store_true",
        help="Wait for a human to approve changes in the SuperDocs web UI instead of auto-approving via API.",
    )
    args = parser.parse_args()
    run_pipeline(browser_review=args.browser_review)


if __name__ == "__main__":
    main()
