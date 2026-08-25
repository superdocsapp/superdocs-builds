"""Model Context Protocol (MCP) Adapter for SuperDocs Model Card Generator.

Exposes the SuperDocs 4-call document lifecycle and automated model card generation
as standardized MCP tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .normalizer import ManifestNormalizer, FALLBACK_VALUE
from .tabulator import BenchmarkTabulator
from .updater import SectionBoundaryUpdater, AnchorError
from .superdocs_client import SuperDocsClient, SuperDocsAPIError, extract_and_parse_diff
from .html_renderer import HTMLCardRenderer


class SuperDocsMCPAdapter:
    """MCP Server Adapter exposing SuperDocs 4-Call tools and Card Generators."""

    def __init__(self, client: Optional[SuperDocsClient] = None) -> None:
        self.client = client or SuperDocsClient()
        self.normalizer = ManifestNormalizer()
        self.tabulator = BenchmarkTabulator()

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return list of standard MCP tool definitions."""
        return [
            {
                "name": "superdocs_upload",
                "description": "Call 1/4: Upload base card document scaffold and initialize session/document ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Base markdown scaffold content."},
                        "title": {"type": "string", "description": "Title of the document."},
                        "metadata": {"type": "object", "description": "Optional document metadata dictionary."}
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "superdocs_chat",
                "description": "Call 2/4: Send targeted edit instructions to update evaluation tables or sections.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Target document ID."},
                        "instruction": {"type": "string", "description": "Instruction describing the edit."},
                        "evaluation_markdown": {"type": "string", "description": "New evaluation markdown table content."},
                        "timestamp": {"type": "string", "description": "ISO timestamp of the evaluation run."},
                        "run_id": {"type": "string", "description": "Unique evaluation run ID."},
                        "baseline_model": {"type": "string", "description": "Baseline model reference name."}
                    },
                    "required": ["document_id", "instruction", "evaluation_markdown"]
                }
            },
            {
                "name": "superdocs_approve",
                "description": "Call 3/4: Approve proposed changes, executing required double JSON deserialization.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Target document ID."},
                        "diff_payload": {
                            "type": ["string", "object"],
                            "description": "Proposed diff payload (either outer response object or double-encoded JSON diff string)."
                        }
                    },
                    "required": ["document_id", "diff_payload"]
                }
            },
            {
                "name": "superdocs_export",
                "description": "Call 4/4: Export finalized document in synchronized Markdown and PDF formats with async polling.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Document ID to export."},
                        "formats": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Export formats (e.g. ['markdown', 'pdf'])."
                        },
                        "output_dir": {"type": "string", "description": "Optional folder path to write output files."},
                        "base_filename": {"type": "string", "description": "Base filename for exported files."}
                    },
                    "required": ["document_id"]
                }
            },
            {
                "name": "generate_model_card",
                "description": "End-to-end model card generator workflow from manifest and evaluation logs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "manifest": {"type": ["object", "string"], "description": "Manifest dictionary or path to JSON file."},
                        "eval_results": {"type": ["object", "string", "array"], "description": "Evaluation data (dict, path to JSON/CSV, or list of metrics)."},
                        "sample_mode": {"type": "boolean", "description": "Slice evaluation metrics to 3 rows for quick handshake testing."},
                        "output_dir": {"type": "string", "description": "Directory to save exported files."}
                    },
                    "required": ["manifest"]
                }
            },
            {
                "name": "refresh_evaluation_tables",
                "description": "In-place evaluation table refresh preserving 100% of human-written narrative text.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "card_content_or_path": {"type": "string", "description": "Raw markdown card content or path to existing markdown file."},
                        "eval_results": {"type": ["object", "string", "array"], "description": "New benchmark evaluation results."},
                        "sample_mode": {"type": "boolean", "description": "Slice evaluation metrics to 3 rows."},
                        "timestamp": {"type": "string", "description": "Optional ISO timestamp."},
                        "run_id": {"type": "string", "description": "Optional run identifier."},
                        "baseline_model": {"type": "string", "description": "Optional baseline model reference."}
                    },
                    "required": ["card_content_or_path", "eval_results"]
                }
            }
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch MCP tool execution by name with given arguments."""
        if name == "superdocs_upload":
            return self.client.upload(
                content=arguments["content"],
                title=arguments.get("title", "Model Card"),
                metadata=arguments.get("metadata")
            )

        elif name == "superdocs_chat":
            return self.client.chat(
                document_id=arguments["document_id"],
                instruction=arguments["instruction"],
                evaluation_markdown=arguments["evaluation_markdown"],
                timestamp=arguments.get("timestamp"),
                run_id=arguments.get("run_id"),
                baseline_model=arguments.get("baseline_model")
            )

        elif name == "superdocs_approve":
            return self.client.approve(
                document_id=arguments["document_id"],
                chat_response_or_diff=arguments["diff_payload"]
            )

        elif name == "superdocs_export":
            return self.client.export(
                document_id=arguments["document_id"],
                output_dir=arguments.get("output_dir"),
                base_filename=arguments.get("base_filename", "model_card"),
                formats=arguments.get("formats", ["markdown", "pdf"])
            )

        elif name == "generate_model_card":
            raw_manifest = arguments["manifest"]
            if isinstance(raw_manifest, str) and Path(raw_manifest).is_file():
                with open(raw_manifest, "r", encoding="utf-8") as f:
                    raw_manifest = json.load(f)
            elif isinstance(raw_manifest, str):
                raw_manifest = json.loads(raw_manifest)

            normalized = self.normalizer.normalize(raw_manifest)
            eval_results = arguments.get("eval_results")
            sample_mode = bool(arguments.get("sample_mode", False))

            eval_markdown = "_No benchmark evaluation results recorded._\n"
            eval_data = {}
            if eval_results:
                eval_data = self.tabulator.load_eval_data(eval_results)
                eval_markdown = self.tabulator.render_markdown_tables(
                    records=eval_data.get("results", []),
                    sample_mode=sample_mode,
                    baseline_model_name=eval_data.get("baseline_model")
                )

            # Load default template
            tmpl_path = Path(__file__).resolve().parent.parent / "templates" / "base_card_template.md"
            with open(tmpl_path, "r", encoding="utf-8") as f:
                template_text = f.read()

            card_content = template_text.format(
                model_name=self.normalizer.format_markdown_field(normalized.get("model_name")),
                version=self.normalizer.format_markdown_field(normalized.get("version")),
                release_date=self.normalizer.format_markdown_field(normalized.get("release_date")),
                model_type=self.normalizer.format_markdown_field(normalized.get("model_type")),
                description=self.normalizer.format_markdown_field(normalized.get("description")),
                intended_purpose=self.normalizer.format_markdown_field(normalized.get("intended_purpose")),
                limitations=self.normalizer.format_markdown_field(normalized.get("limitations")),
                out_of_scope_uses=self.normalizer.format_markdown_field(normalized.get("out_of_scope_uses")),
                maintenance_contact=self.normalizer.format_markdown_field(normalized.get("maintenance_contact")),
                maintenance_contact_details=self.normalizer.format_markdown_field(normalized.get("maintenance_contact")),
                training_data_summary=self.normalizer.format_markdown_field(normalized.get("training_data_summary")),
                model_architecture=self.normalizer.format_markdown_field(normalized.get("model_architecture")),
                ethical_considerations=self.normalizer.format_markdown_field(normalized.get("ethical_considerations")),
                license=self.normalizer.format_markdown_field(normalized.get("license")),
                citation=self.normalizer.format_markdown_field(normalized.get("citation")),
                hardware_and_compute=self.normalizer.format_markdown_field(normalized.get("hardware_and_compute")),
                author_organization=self.normalizer.format_markdown_field(normalized.get("author_organization")),
                evaluation_timestamp=eval_data.get("timestamp", "2026-08-17 12:00:00 UTC"),
                evaluation_run_id=eval_data.get("run_id", "run-mcp-gen"),
                evaluation_baseline_model=eval_data.get("baseline_model", "Not specified"),
                evaluation_tables=eval_markdown,
            )

            # Perform 4-call execution
            upload_res = self.client.upload(content=card_content, title=normalized.get("model_name", "Model Card"))
            doc_id = upload_res["document_id"]
            chat_res = self.client.chat(
                document_id=doc_id,
                instruction="Sync initial benchmark evaluation tables.",
                evaluation_markdown=eval_markdown,
                timestamp=eval_data.get("timestamp"),
                run_id=eval_data.get("run_id"),
                baseline_model=eval_data.get("baseline_model")
            )
            approve_res = self.client.approve(document_id=doc_id, chat_response_or_diff=chat_res)
            export_res = self.client.export(
                document_id=doc_id,
                output_dir=arguments.get("output_dir"),
                base_filename=f"{normalized.get('model_name', 'model_card')}".lower().replace(" ", "_")
            )

            return {
                "document_id": doc_id,
                "version": approve_res.get("version"),
                "markdown_preview": card_content[:300] + "...",
                "exports": export_res
            }

        elif name == "refresh_evaluation_tables":
            card_input = arguments["card_content_or_path"]
            if Path(card_input).is_file():
                with open(card_input, "r", encoding="utf-8") as f:
                    content = f.read()
                is_file = True
                card_path = Path(card_input)
            else:
                content = card_input
                is_file = False
                card_path = None

            eval_results = arguments["eval_results"]
            sample_mode = bool(arguments.get("sample_mode", False))
            eval_data = self.tabulator.load_eval_data(eval_results)

            new_eval_markdown = self.tabulator.render_markdown_tables(
                records=eval_data.get("results", []),
                sample_mode=sample_mode,
                baseline_model_name=arguments.get("baseline_model") or eval_data.get("baseline_model")
            )

            updated = SectionBoundaryUpdater.update_evaluation(
                document_content=content,
                new_eval_markdown=new_eval_markdown,
                timestamp=arguments.get("timestamp") or eval_data.get("timestamp"),
                run_id=arguments.get("run_id") or eval_data.get("run_id"),
                baseline_model=arguments.get("baseline_model") or eval_data.get("baseline_model")
            )

            if is_file and card_path:
                with open(card_path, "w", encoding="utf-8") as f:
                    f.write(updated)

            return {
                "status": "refreshed",
                "narrative_preserved": True,
                "updated_content": updated
            }

        raise ValueError(f"Unknown MCP tool name: {name}")
