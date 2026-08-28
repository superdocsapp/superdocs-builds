"""Extract text node for the Understand stage.

Converts raw_content to plain text based on MIME type. Supports skip when
the input is already text/plain, and handles transient errors (timeout, memory)
and permanent errors (corrupted file) appropriately.
"""

import asyncio
from typing import Callable, Optional, Protocol

from src.pipeline.state import PipelineState, SkippedNodeEntry


class TextExtractor(Protocol):
    """Protocol for document-to-text extraction backends."""

    async def extract(self, raw_content: bytes, timeout_seconds: int) -> str:
        """Extract plain text from raw document bytes.

        Args:
            raw_content: The raw bytes of the document.
            timeout_seconds: Maximum seconds allowed for extraction.

        Returns:
            The extracted plain text.

        Raises:
            asyncio.TimeoutError: If extraction exceeds the timeout.
            MemoryError: If extraction exceeds available memory.
            ValueError: If the file is corrupted or cannot be parsed.
        """
        ...


async def _default_pdf_extract(raw_content: bytes, timeout_seconds: int) -> str:
    """Placeholder PDF text extraction.

    Will be replaced with a real PDF library (e.g., pdfplumber, PyMuPDF) later.

    Raises:
        asyncio.TimeoutError: If extraction exceeds the timeout.
        MemoryError: If extraction exceeds available memory.
        ValueError: If the PDF is corrupted.
    """
    raise NotImplementedError("PDF extraction not yet wired to a real library")


async def _default_docx_extract(raw_content: bytes, timeout_seconds: int) -> str:
    """Placeholder DOCX text extraction.

    Will be replaced with a real DOCX library (e.g., python-docx) later.

    Raises:
        asyncio.TimeoutError: If extraction exceeds the timeout.
        MemoryError: If extraction exceeds available memory.
        ValueError: If the DOCX is corrupted.
    """
    raise NotImplementedError("DOCX extraction not yet wired to a real library")


# Module-level extractors that can be overridden for testing or wiring
_pdf_extractor: Callable[[bytes, int], "asyncio.coroutines"] = _default_pdf_extract
_docx_extractor: Callable[[bytes, int], "asyncio.coroutines"] = _default_docx_extract


def set_pdf_extractor(extractor: Callable[[bytes, int], "asyncio.coroutines"]) -> None:
    """Set the PDF text extraction backend."""
    global _pdf_extractor
    _pdf_extractor = extractor


def set_docx_extractor(extractor: Callable[[bytes, int], "asyncio.coroutines"]) -> None:
    """Set the DOCX text extraction backend."""
    global _docx_extractor
    _docx_extractor = extractor


async def extract_text(
    state: PipelineState,
    pdf_extractor: Optional[Callable[[bytes, int], "asyncio.coroutines"]] = None,
    docx_extractor: Optional[Callable[[bytes, int], "asyncio.coroutines"]] = None,
) -> PipelineState:
    """Extract text from raw_content based on MIME type.

    Node contract:
        Input keys: raw_content, mime_type, config
        Output keys: extracted_text, current_node, node_status, error_type,
                     error_detail, skipped_nodes, completed_nodes

    Terminal states:
        - completed: text successfully extracted
        - skipped: input already text/plain (skip_reason="input_already_text")
        - error/permanent: corrupted file
        - error/transient: timeout or memory error

    Args:
        state: The current pipeline state.
        pdf_extractor: Optional PDF extraction callable (for dependency injection).
        docx_extractor: Optional DOCX extraction callable (for dependency injection).

    Returns:
        Updated PipelineState with extracted text or error information.
    """
    pdf_fn = pdf_extractor or _pdf_extractor
    docx_fn = docx_extractor or _docx_extractor

    raw_content = state["raw_content"]
    mime_type = state["mime_type"]
    config = state["config"]
    timeout_seconds = config["extract_text_timeout_seconds"]

    # Start with copies of mutable state fields
    skipped_nodes = list(state["skipped_nodes"])
    completed_nodes = list(state["completed_nodes"])

    # Skip case: input is already plain text
    if mime_type == "text/plain":
        extracted_text = raw_content.decode("utf-8") if raw_content else ""
        skipped_nodes.append(
            SkippedNodeEntry(node_name="extract_text", reason="input_already_text")
        )
        completed_nodes.append("extract_text")
        return PipelineState(
            **{
                **state,
                "extracted_text": extracted_text,
                "current_node": "extract_text",
                "node_status": "skipped",
                "error_type": None,
                "error_detail": None,
                "skipped_nodes": skipped_nodes,
                "completed_nodes": completed_nodes,
            }
        )

    # Extraction based on MIME type
    try:
        if mime_type == "application/pdf":
            extracted_text = await pdf_fn(raw_content, timeout_seconds)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            extracted_text = await docx_fn(raw_content, timeout_seconds)
        else:
            # Unsupported MIME type — treat as permanent error
            return PipelineState(
                **{
                    **state,
                    "current_node": "extract_text",
                    "node_status": "error",
                    "error_type": "permanent",
                    "error_detail": f"Unsupported MIME type for text extraction: {mime_type}",
                    "skipped_nodes": skipped_nodes,
                    "completed_nodes": completed_nodes,
                }
            )

        # Success
        completed_nodes.append("extract_text")
        return PipelineState(
            **{
                **state,
                "extracted_text": extracted_text,
                "current_node": "extract_text",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "skipped_nodes": skipped_nodes,
                "completed_nodes": completed_nodes,
            }
        )

    except asyncio.TimeoutError:
        return PipelineState(
            **{
                **state,
                "current_node": "extract_text",
                "node_status": "error",
                "error_type": "transient",
                "error_detail": "Text extraction timed out",
                "skipped_nodes": skipped_nodes,
                "completed_nodes": completed_nodes,
            }
        )

    except MemoryError:
        return PipelineState(
            **{
                **state,
                "current_node": "extract_text",
                "node_status": "error",
                "error_type": "transient",
                "error_detail": "Text extraction exceeded available memory",
                "skipped_nodes": skipped_nodes,
                "completed_nodes": completed_nodes,
            }
        )

    except ValueError as exc:
        return PipelineState(
            **{
                **state,
                "current_node": "extract_text",
                "node_status": "error",
                "error_type": "permanent",
                "error_detail": f"Corrupted file: {exc}",
                "skipped_nodes": skipped_nodes,
                "completed_nodes": completed_nodes,
            }
        )
