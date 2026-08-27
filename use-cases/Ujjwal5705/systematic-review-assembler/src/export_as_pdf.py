import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from superdocs_client import export_document

# Point this at whatever session_id your last successful assembly run used —
# check the printed "Session:" or the job_id logs from that run.
SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else None
if not SESSION_ID:
    print("Usage: python export_as_pdf.py <session_id>")
    sys.exit(1)

path = export_document(
    SESSION_ID, format="pdf", output_path="../output/final_review_package.pdf"
)
print(f"Exported PDF: {path}")
