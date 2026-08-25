"""DOCX document loader and parser."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from docx import Document as DocxDocument
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from superdocs_template_inference.exceptions import DocumentLoadError
from superdocs_template_inference.models import (
    Document,
    ParagraphBlock,
    TableBlock,
)

from .loader import DocumentLoader


class DOCXLoader(DocumentLoader):
    """Loader for DOCX format documents.
    
    Extracts paragraphs, headings, lists, and tables from DOCX files
    and normalizes them into a standard Document representation.
    """

    # Heading style patterns (common in Word)
    HEADING_STYLE_PATTERN = re.compile(r"^Heading\s+(\d)$", re.IGNORECASE)

    def load(self, file_path: str) -> Document:
        """Load and normalize a DOCX document.
        
        Args:
            file_path: Path to the DOCX file.
            
        Returns:
            A normalized Document object with extracted blocks.
            
        Raises:
            DocumentLoadError: If the file cannot be opened or parsed.
        """
        try:
            docx_doc = DocxDocument(file_path)
        except Exception as e:
            raise DocumentLoadError(f"Failed to load DOCX file {file_path}: {e}")

        # Generate document ID and extract filename
        document_id = str(uuid4())
        filename = Path(file_path).name
        file_type = "docx"
        loaded_at = datetime.utcnow().isoformat() + "Z"

        # Extract blocks from document
        blocks = self._extract_blocks(docx_doc)

        return Document(
            document_id=document_id,
            filename=filename,
            file_type=file_type,
            loaded_at=loaded_at,
            blocks=blocks,
        )

    def _extract_blocks(self, docx_doc: DocxDocument) -> list:
        """Extract content blocks from DOCX document.
        
        Preserves document order and extracts paragraphs, tables, etc.
        Ignores empty paragraphs without meaningful content.
        
        Args:
            docx_doc: A python-docx Document object.
            
        Returns:
            A list of Block objects in document order.
        """
        blocks = []

        for element in docx_doc.element.body:
            # Handle paragraphs
            if element.tag.endswith("}p"):
                paragraph = None
                # Find the corresponding paragraph in docx_doc.paragraphs
                for para in docx_doc.paragraphs:
                    if para._element == element:
                        paragraph = para
                        break

                if paragraph is not None:
                    block = self._extract_paragraph_block(paragraph)
                    # Only include non-empty paragraphs or structurally meaningful ones
                    if block is not None:
                        blocks.append(block)

            # Handle tables
            elif element.tag.endswith("}tbl"):
                table = None
                # Find the corresponding table in docx_doc.tables
                for tbl in docx_doc.tables:
                    if tbl._element == element:
                        table = tbl
                        break

                if table is not None:
                    block = self._extract_table_block(table)
                    blocks.append(block)

        return blocks

    def _extract_paragraph_block(self, paragraph) -> Optional[ParagraphBlock]:
        """Extract a paragraph as a ParagraphBlock.
        
        Args:
            paragraph: A python-docx paragraph object.
            
        Returns:
            A ParagraphBlock, or None if the paragraph is empty and
            has no meaningful structural information.
        """
        text = paragraph.text.strip()

        # Ignore purely empty paragraphs
        if not text:
            return None

        # Detect heading style
        is_heading = False
        heading_level = None
        style_name = paragraph.style.name if paragraph.style else None

        if style_name:
            match = self.HEADING_STYLE_PATTERN.match(style_name)
            if match:
                is_heading = True
                heading_level = int(match.group(1))

        # Detect list information
        is_list = self._is_list_paragraph(paragraph)
        list_level = self._get_list_level(paragraph) if is_list else None
        list_ordered = self._is_ordered_list(paragraph) if is_list else None

        font_name = None
        font_size = None
        bold = None
        italic = None
        underline = None
        alignment = None
        spacing_before = None
        spacing_after = None
        indent_left = None
        indent_first_line = None

        runs = getattr(paragraph, "runs", None)
        if runs is not None:
            try:
                runs = list(runs)
            except TypeError:
                runs = []
            try:
                filtered_runs = [run for run in runs if getattr(run, "text", "").strip()]
            except (AttributeError, TypeError):
                filtered_runs = []

            if filtered_runs:
                first_run = filtered_runs[0]
                run_font = getattr(first_run, "font", None)
                if run_font is not None:
                    font_name = getattr(run_font, "name", None)
                    font_size = self._coerce_font_size(getattr(run_font, "size", None))
                    underline = self._coerce_underline(getattr(run_font, "underline", None))
                bold = bool(getattr(first_run, "bold", None)) if getattr(first_run, "bold", None) is not None else None
                italic = bool(getattr(first_run, "italic", None)) if getattr(first_run, "italic", None) is not None else None

        alignment_value = getattr(paragraph, "alignment", None)
        if alignment_value is not None:
            try:
                alignment = self._normalize_alignment(alignment_value)
            except Exception:
                alignment = None

        format_props = getattr(paragraph, "paragraph_format", None)
        if format_props is not None:
            spacing_before = self._coerce_length(getattr(format_props, "space_before", None))
            spacing_after = self._coerce_length(getattr(format_props, "space_after", None))
            indent_left = self._coerce_length(getattr(format_props, "left_indent", None))
            indent_first_line = self._coerce_length(getattr(format_props, "first_line_indent", None))

        return ParagraphBlock(
            text=text,
            style_name=style_name,
            is_heading=is_heading,
            heading_level=heading_level,
            is_list=is_list,
            list_level=list_level,
            list_ordered=list_ordered,
            font_name=font_name,
            font_size=font_size,
            bold=bold,
            italic=italic,
            underline=underline,
            alignment=alignment,
            spacing_before=spacing_before,
            spacing_after=spacing_after,
            indent_left=indent_left,
            indent_first_line=indent_first_line,
        )

    def _extract_table_block(self, table) -> TableBlock:
        """Extract a table as a TableBlock.
        
        Args:
            table: A python-docx table object.
            
        Returns:
            A TableBlock with rows and column information.
        """
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(cells)

        return TableBlock(rows=rows)

    def _normalize_alignment(self, alignment_value) -> Optional[str]:
        """Map python-docx paragraph alignments to generic label values."""
        if alignment_value is None:
            return None
        mapping = {
            WD_PARAGRAPH_ALIGNMENT.LEFT: "left",
            WD_PARAGRAPH_ALIGNMENT.CENTER: "center",
            WD_PARAGRAPH_ALIGNMENT.RIGHT: "right",
            WD_PARAGRAPH_ALIGNMENT.JUSTIFY: "justify",
            WD_PARAGRAPH_ALIGNMENT.DISTRIBUTE: "distributed",
        }
        return mapping.get(alignment_value, None)

    def _coerce_length(self, value) -> Optional[float]:
        """Convert a python-docx length to a point value if measurable."""
        if value is None:
            return None
        try:
            if hasattr(value, "pt"):
                return float(value.pt)
            if isinstance(value, (int, float)):
                return float(value)
        except Exception:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_font_size(self, value) -> Optional[float]:
        """Convert a docx font-size object to a float point value."""
        if value is None:
            return None
        try:
            return float(value.pt)
        except Exception:
            return self._coerce_length(value)

    def _coerce_underline(self, value) -> Optional[bool]:
        """Normalize underlining state into a simple boolean or None."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        try:
            return bool(value)
        except Exception:
            return None

    def _is_list_paragraph(self, paragraph) -> bool:
        """Determine if a paragraph is part of a list.
        
        Checks for list formatting in the paragraph properties.
        
        Args:
            paragraph: A python-docx paragraph object.
            
        Returns:
            True if the paragraph is a list item, False otherwise.
        """
        # Check for list numbering in pPr (paragraph properties)
        pPr = paragraph._element.get_or_add_pPr()

        # Check for numPr (numbering properties)
        numPr = pPr.find(qn("w:numPr"))
        if numPr is not None:
            return True

        # Check for pStyle with list-like styles
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is not None:
            style_val = pStyle.get(qn("w:val"))
            if style_val and ("List" in style_val or "list" in style_val):
                return True

        return False

    def _get_list_level(self, paragraph) -> Optional[int]:
        """Get the nesting level of a list paragraph.
        
        Args:
            paragraph: A python-docx paragraph object.
            
        Returns:
            The list nesting level (0-indexed), or None if not a list.
        """
        pPr = paragraph._element.get_or_add_pPr()
        ilvl = pPr.find(qn("w:ilvl"))

        if ilvl is not None:
            try:
                return int(ilvl.get(qn("w:val")))
            except (ValueError, TypeError):
                pass

        return None

    def _is_ordered_list(self, paragraph) -> Optional[bool]:
        """Determine if a list paragraph is ordered or unordered.
        
        Checks the numbering format to distinguish between ordered
        and unordered lists.
        
        Args:
            paragraph: A python-docx paragraph object.
            
        Returns:
            True for ordered lists, False for unordered, None if not a list.
        """
        pPr = paragraph._element.get_or_add_pPr()
        numPr = pPr.find(qn("w:numPr"))

        if numPr is None:
            return None

        # Try to access the numbering properties from the document's numbering part
        # This is a simplified check; a full implementation would parse the numbering.xml
        # For now, we use heuristics:
        # - If we can determine it's a bullet, return False
        # - If we can determine it's a numbered list, return True
        # - If uncertain, return None

        try:
            # Access the document's numbering definitions
            if hasattr(paragraph._element.getroottree().getroot(), "document_part"):
                # This would require deeper access to numbering styles
                # For Milestone 1, we conservatively return None if we can't determine
                pass
        except Exception:
            pass

        # Conservative approach: return None unless we can definitively determine
        return None
