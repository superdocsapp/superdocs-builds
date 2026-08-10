"""Portable tool specifications consumed by thin framework bindings."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapter import SuperDocsAdapter
from .checkpoints import checkpoint_name, operation_fingerprint
from .models import ExportFormat, Job


@dataclass(frozen=True)
class ToolSpec:
    """The lowest common denominator of function-tool APIs."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Callable[..., dict[str, Any]]


class SuperDocsToolset:
    """Creates framework-neutral tools backed by one adapter instance."""

    def __init__(
        self,
        adapter: SuperDocsAdapter,
        *,
        output_directory: str | Path = "output",
        on_progress: Callable[[Job], None] | None = None,
    ) -> None:
        self.adapter = adapter
        self.output_directory = Path(output_directory)
        self.on_progress = on_progress

    def edit_document(
        self,
        file_path: str,
        instruction: str,
        output_format: str = "txt",
    ) -> dict[str, Any]:
        """Upload, edit with review, approve, export, and save one document."""
        export_format = ExportFormat(output_format)
        fingerprint = operation_fingerprint(
            file_path,
            instruction,
            export_format,
            "core",
            "balanced",
        )
        checkpoint_path = self.output_directory / ".superdocs-state" / checkpoint_name(fingerprint)
        result = self.adapter.edit_and_export(
            file_path,
            instruction,
            export_format=export_format,
            output_filename="superdocs-output",
            checkpoint_path=checkpoint_path,
            on_progress=self.on_progress,
        )
        saved_path = result.export.save(self.output_directory / result.export.filename)
        canonical = result.canonical()
        canonical["output_path"] = saved_path.as_posix()
        return canonical

    def specs(self) -> tuple[ToolSpec, ...]:
        return (
            ToolSpec(
                name="superdocs_edit_document",
                description=(
                    "Upload a document to SuperDocs, request an AI edit, approve all proposed "
                    "changes, export the finished document, and return a canonical result."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the source document.",
                        },
                        "instruction": {
                            "type": "string",
                            "description": "Exact natural-language editing instruction.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": [item.value for item in ExportFormat],
                            "default": "txt",
                        },
                    },
                    "required": ["file_path", "instruction"],
                    "additionalProperties": False,
                },
                handler=self.edit_document,
            ),
        )
