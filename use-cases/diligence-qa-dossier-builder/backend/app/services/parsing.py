import io
from typing import List, Optional
from pydantic import BaseModel
import pypdf
import docx
import openpyxl

from backend.app.exceptions import UnsupportedFileError, FileIngestionError

class ExtractedSegment(BaseModel):
    content: str
    page_number: Optional[int] = None
    section: Optional[str] = None

def parse_txt(file_bytes: bytes) -> List[ExtractedSegment]:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("cp1252", errors="replace")
        except Exception as e:
            raise FileIngestionError(f"Failed to decode text file: {e}")
    return [ExtractedSegment(content=text, page_number=None, section=None)]

def parse_pdf(file_bytes: bytes) -> List[ExtractedSegment]:
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        segments = []
        for idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                segments.append(ExtractedSegment(
                    content=text.strip(),
                    page_number=idx + 1,
                    section=None
                ))
        return segments
    except Exception as e:
        raise FileIngestionError(f"Failed to parse PDF file: {e}")

def parse_docx(file_bytes: bytes) -> List[ExtractedSegment]:
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        segments = []
        current_section = None

        # Parse paragraphs
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            
            # Watch for heading styles to dynamically set current section
            if para.style and para.style.name and para.style.name.startswith("Heading"):
                current_section = text
            
            segments.append(ExtractedSegment(
                content=text,
                page_number=None,
                section=current_section
            ))
            
        # Parse tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text)
                if row_text.strip():
                    segments.append(ExtractedSegment(
                        content=row_text.strip(),
                        page_number=None,
                        section=current_section
                    ))
        return segments
    except Exception as e:
        raise FileIngestionError(f"Failed to parse Word Document (.docx): {e}")

def parse_xlsx(file_bytes: bytes) -> List[ExtractedSegment]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        segments = []
        for sheet in wb.worksheets:
            sheet_name = sheet.title
            rows_text = []
            for row in sheet.iter_rows(values_only=True):
                # Format cell values to string
                row_vals = [str(val).strip() if val is not None else "" for val in row]
                if any(row_vals):  # Skip completely empty rows
                    rows_text.append(" | ".join(row_vals))
            
            if rows_text:
                sheet_content = f"Sheet: {sheet_name}\n" + "\n".join(rows_text)
                segments.append(ExtractedSegment(
                    content=sheet_content,
                    page_number=None,
                    section=f"Sheet: {sheet_name}"
                    # No page numbers for excel, sheet title serves as section context
                ))
        return segments
    except Exception as e:
        raise FileIngestionError(f"Failed to parse Excel spreadsheet (.xlsx): {e}")

def extract_document_text(filename: str, file_bytes: bytes) -> List[ExtractedSegment]:
    """
    Router that identifies the file extension and extracts content segments.
    Explicitly rejects legacy formats like .xls.
    """
    ext = filename.lower().split(".")[-1]
    
    if ext == "xls":
        raise UnsupportedFileError(
            "Legacy Excel format (.xls) is not supported. Please convert it to .xlsx format."
        )
    elif ext == "xlsx":
        return parse_xlsx(file_bytes)
    elif ext == "docx":
        return parse_docx(file_bytes)
    elif ext == "pdf":
        return parse_pdf(file_bytes)
    elif ext in ["txt", "md", "csv"]:
        return parse_txt(file_bytes)
    else:
        raise UnsupportedFileError(
            f"Unsupported file format: .{ext}. Supported formats are .pdf, .docx, .xlsx, .txt, .md, .csv"
        )
