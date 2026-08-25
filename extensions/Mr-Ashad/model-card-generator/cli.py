#!/usr/bin/env python3
"""Model and System Card Generator CLI.

Automated Model/System Card creation and in-place evaluation refresh engine
integrating SuperDocs 4-Call document lifecycle.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure package modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.normalizer import ManifestNormalizer, FALLBACK_VALUE
from src.tabulator import BenchmarkTabulator
from src.updater import SectionBoundaryUpdater, AnchorError
from src.superdocs_client import SuperDocsClient, SuperDocsAPIError
from src.html_renderer import HTMLCardRenderer
from src.pdf_renderer import PDFCardRenderer


def print_banner() -> None:
    """Print welcome header."""
    banner = """
========================================================================
   MODEL & SYSTEM CARD GENERATOR (SuperDocs 4-Call Integration Engine)
========================================================================
"""
    print(banner)


def run_generate(args: argparse.Namespace) -> int:
    """Execute complete initial Model Card generation."""
    print(f"[*] Starting Model Card Generation...")
    print(f"    Manifest:     {args.manifest}")
    print(f"    Eval Results: {args.eval_results}")
    if args.sample_mode:
        print(f"    [!] Sample Mode ACTIVE: Processing 3-row metric slice for verification handshake.")

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"[!] Error: Manifest file not found: {args.manifest}", file=sys.stderr)
        return 1

    eval_path = Path(args.eval_results) if args.eval_results else None
    if eval_path and not eval_path.is_file():
        print(f"[!] Error: Evaluation results file not found: {args.eval_results}", file=sys.stderr)
        return 1

    # 1. Normalize Manifest with Strict Completeness
    normalizer = ManifestNormalizer()
    with open(manifest_path, "r", encoding="utf-8") as f:
        raw_manifest = json.load(f)

    is_valid, errors = normalizer.validate(raw_manifest)
    if not is_valid:
        print(f"[!] Warning: Manifest schema validation notices: {errors}", file=sys.stderr)

    normalized = normalizer.normalize(raw_manifest)
    print(f"[+] Model manifest normalized. (Missing fields set to '{FALLBACK_VALUE}')")

    # 2. Compile Evaluation Metrics & Deltas
    tabulator = BenchmarkTabulator()
    eval_markdown = "_No benchmark evaluation results recorded._\n"
    eval_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    eval_run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    eval_baseline = "Not specified"

    processed_records = []
    if eval_path:
        eval_data = tabulator.load_eval_data(eval_path)
        eval_run_id = eval_data.get("run_id") or eval_run_id
        if eval_data.get("timestamp"):
            eval_timestamp = eval_data["timestamp"]
        if eval_data.get("baseline_model"):
            eval_baseline = eval_data["baseline_model"]

        processed_records = tabulator.process_records(eval_data.get("results", []), sample_mode=args.sample_mode)
        eval_markdown = tabulator.render_markdown_tables(
            records=eval_data.get("results", []),
            sample_mode=args.sample_mode,
            baseline_model_name=eval_baseline
        )
        print(f"[+] Evaluation tables compiled. ({len(eval_data.get('results', []))} benchmark records)")

    # 3. Populate Base Card Template
    template_path = Path(args.template) if args.template else Path(__file__).resolve().parent / "templates" / "base_card_template.md"
    if not template_path.is_file():
        print(f"[!] Error: Base card template not found: {template_path}", file=sys.stderr)
        return 1

    with open(template_path, "r", encoding="utf-8") as f:
        template_text = f.read()

    # Format fields for markdown insertion
    card_content = template_text.format(
        model_name=normalizer.format_markdown_field(normalized.get("model_name")),
        version=normalizer.format_markdown_field(normalized.get("version")),
        release_date=normalizer.format_markdown_field(normalized.get("release_date")),
        model_type=normalizer.format_markdown_field(normalized.get("model_type")),
        description=normalizer.format_markdown_field(normalized.get("description")),
        intended_purpose=normalizer.format_markdown_field(normalized.get("intended_purpose")),
        limitations=normalizer.format_markdown_field(normalized.get("limitations")),
        out_of_scope_uses=normalizer.format_markdown_field(normalized.get("out_of_scope_uses")),
        maintenance_contact=normalizer.format_markdown_field(normalized.get("maintenance_contact")),
        maintenance_contact_details=normalizer.format_markdown_field(normalized.get("maintenance_contact")),
        training_data_summary=normalizer.format_markdown_field(normalized.get("training_data_summary")),
        model_architecture=normalizer.format_markdown_field(normalized.get("model_architecture")),
        ethical_considerations=normalizer.format_markdown_field(normalized.get("ethical_considerations")),
        license=normalizer.format_markdown_field(normalized.get("license")),
        citation=normalizer.format_markdown_field(normalized.get("citation")),
        hardware_and_compute=normalizer.format_markdown_field(normalized.get("hardware_and_compute")),
        author_organization=normalizer.format_markdown_field(normalized.get("author_organization")),
        evaluation_timestamp=eval_timestamp,
        evaluation_run_id=eval_run_id,
        evaluation_baseline_model=eval_baseline,
        evaluation_tables=eval_markdown,
    )

    # 4. SuperDocs 4-Call Integration
    output_dir = Path(args.output_dir or "./output")
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = args.output_name or f"{normalized.get('model_name', 'model_card')}".lower().replace(" ", "_")

    client = SuperDocsClient(
        api_key=args.api_key,
        base_url=args.base_url,
        mock_mode=args.offline or not bool(args.api_key or os.environ.get("SUPERDOCS_API_KEY"))
    )

    mode_label = "Local / Offline Simulation" if client.mock_mode else f"Live REST ({client.base_url})"
    print(f"[*] SuperDocs Client Mode: {mode_label}")

    try:
        # Call 1: Upload
        print(f"[*] [Call 1/4] Uploading initial card structure to SuperDocs...")
        upload_res = client.upload(
            content=card_content,
            title=f"Model Card: {normalized.get('model_name')}",
            metadata={"version": normalized.get("version"), "generator": "model-card-generator-v1"}
        )
        doc_id = upload_res["document_id"]
        print(f"[+] Document registered. ID: {doc_id}")

        # Call 2: Edit (targeted refresh)
        print(f"[*] [Call 2/4] Sending targeted evaluation update instruction...")
        chat_res = client.chat(
            document_id=doc_id,
            instruction="Synchronize benchmark evaluation tables and run timestamp.",
            evaluation_markdown=eval_markdown,
            timestamp=eval_timestamp,
            run_id=eval_run_id,
            baseline_model=eval_baseline
        )
        print(f"[+] Proposed diff received.")

        # Call 3: Approve (Crucial Double JSON Parse Handled Inside)
        print(f"[*] [Call 3/4] Approving diff (executing double JSON deserialization)...")
        approve_res = client.approve(
            document_id=doc_id,
            chat_response_or_diff=chat_res
        )
        print(f"[+] Diff approved and committed. Document version: {approve_res.get('version')}")

        # Call 4: Export (Markdown + PDF with Async Polling)
        print(f"[*] [Call 4/4] Exporting publication-ready Markdown & PDF (polling with backoff)...")
        export_res = client.export(
            document_id=doc_id,
            output_dir=output_dir,
            base_filename=base_name,
            formats=["markdown", "pdf"]
        )

        # Generate Publication-Ready PDF Card with full rich styling
        eval_meta_dict = {
            "timestamp": eval_timestamp,
            "run_id": eval_run_id,
            "baseline_model": eval_baseline
        }
        rich_pdf_bytes = PDFCardRenderer.render(
            manifest=normalized,
            evaluation_records=processed_records if 'processed_records' in locals() else [],
            evaluation_metadata=eval_meta_dict,
            raw_markdown=card_content
        )
        pdf_file = output_dir / f"{base_name}.pdf"
        with open(pdf_file, "wb") as f:
            f.write(rich_pdf_bytes)

        # Generate Interactive HTML Card
        html_content = HTMLCardRenderer.render(
            manifest=normalized,
            evaluation_records=processed_records if 'processed_records' in locals() else [],
            evaluation_metadata=eval_meta_dict,
            raw_markdown=card_content
        )
        html_file = output_dir / f"{base_name}.html"
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"\n[✓] SUCCESS: Model Card Generated & Exported:")
        print(f"    - Interactive HTML: {html_file}")
        print(f"    - Markdown:         {export_res.get('markdown_path')}")
        print(f"    - PDF:              {pdf_file}")
        return 0

    except SuperDocsAPIError as api_err:
        print(f"[!] SuperDocs API Error: {api_err}", file=sys.stderr)
        return 1
    except Exception as ex:
        print(f"[!] Unexpected error during generation: {ex}", file=sys.stderr)
        return 1


def run_refresh(args: argparse.Namespace) -> int:
    """Execute in-place evaluation table & timestamp refresh."""
    print(f"[*] Starting In-Place Evaluation Table Refresh...")
    print(f"    Target Card:  {args.card_file}")
    print(f"    Eval Results: {args.eval_results}")
    if args.sample_mode:
        print(f"    [!] Sample Mode ACTIVE: Slicing to 3-row metric sample for verification.")

    card_path = Path(args.card_file)
    if not card_path.is_file():
        print(f"[!] Error: Model card markdown file not found: {args.card_file}", file=sys.stderr)
        return 1

    eval_path = Path(args.eval_results)
    if not eval_path.is_file():
        print(f"[!] Error: Evaluation results file not found: {args.eval_results}", file=sys.stderr)
        return 1

    # 1. Compile New Evaluation Tables
    tabulator = BenchmarkTabulator()
    eval_data = tabulator.load_eval_data(eval_path)
    eval_run_id = args.run_id or eval_data.get("run_id") or f"refresh-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    eval_timestamp = args.timestamp or eval_data.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    eval_baseline = args.baseline_model or eval_data.get("baseline_model") or "Not specified"

    new_eval_markdown = tabulator.render_markdown_tables(
        records=eval_data.get("results", []),
        sample_mode=args.sample_mode,
        baseline_model_name=eval_baseline
    )

    # 2. Perform In-Place Update (100% untouched narrative preservation)
    try:
        updated_content, modified = SectionBoundaryUpdater.update_file_in_place(
            card_file_path=card_path,
            new_eval_markdown=new_eval_markdown,
            timestamp=eval_timestamp,
            run_id=eval_run_id,
            baseline_model=eval_baseline
        )
        print(f"[+] In-place evaluation update applied to {card_path} (Narrative text 100% preserved).")
    except AnchorError as ae:
        print(f"[!] Anchor Error during update: {ae}", file=sys.stderr)
        return 1

    # 3. SuperDocs 4-Call Sync (if output directory or export is requested)
    if args.export or args.output_dir:
        output_dir = Path(args.output_dir or card_path.parent)
        base_name = args.output_name or card_path.stem

        client = SuperDocsClient(
            api_key=args.api_key,
            base_url=args.base_url,
            mock_mode=args.offline or not bool(args.api_key or os.environ.get("SUPERDOCS_API_KEY"))
        )

        try:
            print(f"[*] Synchronizing updated card via SuperDocs 4-Call lifecycle...")
            upload_res = client.upload(content=updated_content, title=f"Refreshed {card_path.name}")
            doc_id = upload_res["document_id"]

            chat_res = client.chat(
                document_id=doc_id,
                instruction="Apply updated evaluation benchmark tables.",
                evaluation_markdown=new_eval_markdown,
                timestamp=eval_timestamp,
                run_id=eval_run_id,
                baseline_model=eval_baseline
            )

            approve_res = client.approve(document_id=doc_id, chat_response_or_diff=chat_res)

            export_res = client.export(
                document_id=doc_id,
                output_dir=output_dir,
                base_filename=base_name,
                formats=["markdown", "pdf"]
            )

            # Also update publication-ready PDF and interactive HTML
            refreshed_records = tabulator.process_records(eval_data.get("results", []), sample_mode=args.sample_mode)
            eval_meta_dict = {
                "timestamp": eval_timestamp,
                "run_id": eval_run_id,
                "baseline_model": eval_baseline
            }
            rich_pdf_bytes = PDFCardRenderer.render(
                manifest={"model_name": base_name.replace("_", " ").title(), "version": "Refreshed"},
                evaluation_records=refreshed_records,
                evaluation_metadata=eval_meta_dict,
                raw_markdown=updated_content
            )
            pdf_file = output_dir / f"{base_name}.pdf"
            with open(pdf_file, "wb") as f:
                f.write(rich_pdf_bytes)

            html_content = HTMLCardRenderer.render(
                manifest={"model_name": base_name.replace("_", " ").title(), "version": "Refreshed"},
                evaluation_records=refreshed_records,
                evaluation_metadata=eval_meta_dict,
                raw_markdown=updated_content
            )
            html_file = output_dir / f"{base_name}.html"
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)

            print(f"[✓] Refreshed exports available at:")
            print(f"    - Interactive HTML: {html_file}")
            print(f"    - Markdown:         {export_res.get('markdown_path')}")
            print(f"    - PDF:              {pdf_file}")
        except Exception as e:
            print(f"[!] SuperDocs export sync warning: {e}", file=sys.stderr)

    print(f"\n[✓] In-place evaluation refresh complete.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Model and System Card Generator with Automated In-Place Refresh and SuperDocs 4-Call Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Generate Subcommand
    gen_parser = subparsers.add_parser("generate", help="Generate complete initial Model/System Card")
    gen_parser.add_argument("--manifest", "-m", required=True, help="Path to static model manifest JSON file")
    gen_parser.add_argument("--eval-results", "-e", required=False, help="Path to raw benchmark results (JSON / CSV)")
    gen_parser.add_argument("--template", "-t", required=False, help="Path to custom base card template Markdown file")
    gen_parser.add_argument("--output-dir", "-o", default="./output", help="Directory to save generated .md and .pdf files")
    gen_parser.add_argument("--output-name", "-n", required=False, help="Base name for generated files")
    gen_parser.add_argument("--sample-mode", action="store_true", help="Run against 3-row metric slice to verify handshake")
    gen_parser.add_argument("--offline", "--local", action="store_true", help="Force offline/local execution without network API calls")
    gen_parser.add_argument("--api-key", required=False, help="SuperDocs API key (or set SUPERDOCS_API_KEY env)")
    gen_parser.add_argument("--base-url", required=False, help="SuperDocs API base URL (default: https://docs.superdocs.app)")

    # Refresh Subcommand
    ref_parser = subparsers.add_parser("refresh", help="Perform automated in-place evaluation table refresh on existing card")
    ref_parser.add_argument("--card-file", "-c", required=True, help="Path to existing Model Card Markdown file to update")
    ref_parser.add_argument("--eval-results", "-e", required=True, help="Path to new benchmark results (JSON / CSV)")
    ref_parser.add_argument("--sample-mode", action="store_true", help="Run against 3-row metric slice for verification")
    ref_parser.add_argument("--run-id", required=False, help="Custom evaluation run identifier")
    ref_parser.add_argument("--timestamp", required=False, help="Custom ISO timestamp string")
    ref_parser.add_argument("--baseline-model", required=False, help="Baseline model name for deltas")
    ref_parser.add_argument("--export", action="store_true", help="Export refreshed Markdown and PDF after in-place update")
    ref_parser.add_argument("--output-dir", "-o", required=False, help="Directory to save exported files")
    ref_parser.add_argument("--output-name", "-n", required=False, help="Base name for exported files")
    ref_parser.add_argument("--offline", "--local", action="store_true", help="Force offline/local mode")
    ref_parser.add_argument("--api-key", required=False, help="SuperDocs API key")
    ref_parser.add_argument("--base-url", required=False, help="SuperDocs API base URL")

    return parser


def main() -> int:
    """CLI entry point."""
    print_banner()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "generate":
        return run_generate(args)
    elif args.command == "refresh":
        return run_refresh(args)
    else:
        print(f"[!] Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
