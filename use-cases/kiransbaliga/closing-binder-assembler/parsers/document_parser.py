"""Multi-format document parser (PDF, DOCX, TXT, MD) with legal entity & title extraction."""

import os
import re
import uuid
from typing import List, Optional, Tuple
from pydantic import BaseModel

from core.enums import ExecutionStatus
from core.models import DocumentMetadata, SignatureBlock
from parsers.signature_detector import SignatureDetector


class DocumentParser:
    """Parses PDF, DOCX, TXT, and Markdown files, extracting text, pages, and legal metadata."""

    LEGAL_TITLE_PATTERNS = [
        r"(AGREEMENT\s+AND\s+PLAN\s+OF\s+MERGER)",
        r"(STOCK\s+PURCHASE\s+AGREEMENT)",
        r"(ASSET\s+PURCHASE\s+AGREEMENT)",
        r"(ESCROW\s+AGREEMENT)",
        r"(TRANSITION\s+SERVICES\s+AGREEMENT)",
        r"(NON-COMPETITION\s+(?:AND|&)\s+NON-SOLICITATION\s+AGREEMENT)",
        r"(INTELLECTUAL\s+PROPERTY\s+ASSIGNMENT\s+AGREEMENT)",
        r"(VOTING\s+(?:AND|&)\s+SUPPORT\s+AGREEMENT)",
        r"(REGISTRATION\s+RIGHTS\s+AGREEMENT)",
        r"(SECRETARY(?:'S)?\s+CERTIFICATE)",
        r"(OFFICER(?:'S)?\s+CLOSING\s+CERTIFICATE)",
        r"(SOLVENCY\s+CERTIFICATE)",
        r"(LEGAL\s+OPINION\s+OF\s+COUNSEL)",
        r"(CERTIFICATE\s+OF\s+INCORPORATION)",
        r"(ARTICLES\s+OF\s+INCORPORATION)",
        r"(ARTICLES\s+OF\s+MERGER)",
        r"(BYLAWS|AMENDED\s+AND\s+RESTATED\s+BYLAWS)",
        r"(BOARD\s+RESOLUTIONS|WRITTEN\s+CONSENT\s+OF\s+THE\s+BOARD)",
        r"(SHAREHOLDER\s+CONSENT|WRITTEN\s+CONSENT\s+OF\s+STOCKHOLDERS)",
        r"(CERTIFICATE\s+OF\s+GOOD\s+STANDING)",
        r"(FUNDS\s+FLOW\s+MEMORANDUM)",
        r"(PAYOFF\s+LETTER)",
        r"(UCC-3\s+TERMINATION\s+STATEMENT)",
        r"(CLOSING\s+STATEMENT)",
        r"(DISCLOSURE\s+SCHEDULES?)",
    ]

    PARTY_PATTERNS = [
        r"(?:by and (?:between|among)|entered into by)\s+([A-Z][A-Za-z0-9\.,\s]+?(?:LLC|Inc\.|Corp\.|Corporation|L\.P\.|Company|Holdings|Technologies|LP))",
        r"([A-Z][A-Za-z0-9\.,\s]+?(?:LLC|Inc\.|Corp\.|Corporation|L\.P\.|Company|Holdings|Technologies|LP))\s*\(\"[A-Za-z\s]+\"\)",
    ]

    GOVERNING_LAW_PATTERN = re.compile(
        r"governed\s+by(?:,\s+and\s+construed\s+in\s+accordance\s+with,)?\s+the\s+laws\s+of\s+the\s+State\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        re.IGNORECASE,
    )

    DATE_PATTERN = re.compile(
        r"(?:dated\s+as\s+of|entered\s+into\s+as\s+of|made\s+as\s+of)\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        re.IGNORECASE,
    )

    def __init__(self):
        self.signature_detector = SignatureDetector()
        self.title_regex = re.compile("|".join(self.LEGAL_TITLE_PATTERNS), re.IGNORECASE)

    def parse_file(
        self,
        file_path: str,
        expected_parties: Optional[List[str]] = None,
        signatures_required: bool = True,
    ) -> DocumentMetadata:
        """Parses an individual file into structured DocumentMetadata."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Document file not found: {file_path}")

        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower().replace(".", "")
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"

        raw_text, page_count = self._extract_raw_text(file_path, ext)
        detected_title = self._detect_title(raw_text, filename)
        detected_parties = self._detect_parties(raw_text)
        detected_date = self._detect_date(raw_text)
        governing_law = self._detect_governing_law(raw_text)

        exec_status, sig_blocks = self.signature_detector.analyze_document_text(
            full_text=raw_text,
            expected_parties=expected_parties,
            signatures_required=signatures_required,
        )

        return DocumentMetadata(
            doc_id=doc_id,
            original_filename=filename,
            file_type=ext,
            file_path=os.path.abspath(file_path),
            page_count=max(1, page_count),
            raw_text=raw_text,
            detected_title=detected_title,
            detected_parties=detected_parties,
            detected_date=detected_date,
            governing_law=governing_law,
            signature_blocks=sig_blocks,
            execution_status=exec_status,
            is_scanned_ocr="OCR" in filename.upper() or "SCAN" in filename.upper(),
        )

    def _extract_raw_text(self, file_path: str, ext: str) -> Tuple[str, int]:
        """Extracts text content and page count from given file."""
        if ext == "pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(file_path)
                pages_text = []
                for page in reader.pages:
                    pages_text.append(page.extract_text() or "")
                return "\n\n--- PAGE BREAK ---\n\n".join(pages_text), len(reader.pages)
            except Exception:
                return f"[PDF Parse Fallback - {os.path.basename(file_path)}]", 1

        elif ext == "docx":
            try:
                import docx
                doc = docx.Document(file_path)
                full_text = []
                for para in doc.paragraphs:
                    full_text.append(para.text)
                for table in doc.tables:
                    for row in table.rows:
                        row_text = " | ".join(cell.text.strip() for cell in row.cells)
                        full_text.append(row_text)
                text = "\n".join(full_text)
                words = len(text.split())
                pages = max(1, (words + 399) // 400)
                return text, pages
            except Exception:
                return f"[DOCX Parse Fallback - {os.path.basename(file_path)}]", 1

        else:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                words = len(text.split())
                pages = max(1, (words + 399) // 400)
                return text, pages
            except Exception as e:
                return f"[Text File Error: {e}]", 1

    def _detect_title(self, text: str, filename: str) -> str:
        """Extracts legal title from the document header or recitals."""
        first_chunk = text[:3000]
        if match := self.title_regex.search(first_chunk):
            return match.group(0).strip()

        lines = [line.strip() for line in first_chunk.splitlines() if line.strip()]
        for line in lines[:5]:
            if line.isupper() and len(line) > 5 and len(line) < 100:
                return line

        clean_name = os.path.splitext(filename)[0]
        clean_name = re.sub(r"[_\-\.]+", " ", clean_name)
        return clean_name.title()

    def _detect_parties(self, text: str) -> List[str]:
        """Extracts contracting parties from recitals and preamble."""
        parties = []
        first_chunk = text[:4000]
        for pat in self.PARTY_PATTERNS:
            for match in re.finditer(pat, first_chunk):
                party = match.group(1).strip()
                if len(party) > 3 and party not in parties:
                    parties.append(party)
        return parties[:5]

    def _detect_date(self, text: str) -> Optional[str]:
        """Extracts agreement date from preamble."""
        if match := self.DATE_PATTERN.search(text[:3000]):
            return match.group(1).strip()
        return None

    def _detect_governing_law(self, text: str) -> Optional[str]:
        """Extracts governing jurisdiction from miscellaneous section."""
        if match := self.GOVERNING_LAW_PATTERN.search(text):
            return match.group(1).strip()
        return None
