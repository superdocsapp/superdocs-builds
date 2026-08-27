#!/usr/bin/env python3
"""
Utility script to convert sample markdown documents into valid DOCX files
for SuperDocs API ingestion.
"""
from pathlib import Path
import docx

BASE_DIR = Path(__file__).resolve().parent.parent / "sample_data"

def md_to_docx(md_path: Path, docx_path: Path):
    doc = docx.Document()
    content = md_path.read_text(encoding="utf-8")
    
    for line in content.splitlines():
        line_str = line.strip()
        if line_str.startswith("# "):
            doc.add_heading(line_str[2:], level=1)
        elif line_str.startswith("## "):
            doc.add_heading(line_str[3:], level=2)
        elif line_str.startswith("### "):
            doc.add_heading(line_str[4:], level=3)
        elif line_str.startswith("- ") or line_str.startswith("* "):
            doc.add_paragraph(line_str[2:], style='List Bullet')
        elif line_str:
            doc.add_paragraph(line_str)
            
    doc.save(docx_path)
    print(f"Created DOCX: {docx_path.name}")

def convert_all():
    for period in ["period_1", "period_2"]:
        pdir = BASE_DIR / period
        for md_file in pdir.glob("*.md"):
            docx_file = pdir / f"{md_file.stem}.docx"
            md_to_docx(md_file, docx_file)

if __name__ == "__main__":
    convert_all()
