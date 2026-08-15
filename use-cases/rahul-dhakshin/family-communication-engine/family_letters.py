#!/usr/bin/env python3
"""
family_letters.py — Multilingual family communication engine, built on SuperDocs.

Takes a district template + a teacher comment bank + a family roster, and
generates each family's report-card comment letter in their recorded home
language: merges in the child's and teacher's details and the selected
teacher comment, and asks SuperDocs to translate the whole letter while
preserving the district template's layout across scripts (including
right-to-left and CJK). Export goes through SuperDocs' own
`/v1/documents/export` endpoint (docx/pdf/html/markdown/txt, free of
operation cost), not a local conversion tool -- see cmd_export() below.

Usage:
    export SUPERDOCS_API_KEY=sk_...
    python family_letters.py generate                       # generate all pending letters
    python family_letters.py edit-comment C1 "new text"      # edit a comment, regenerate ONLY affected pending letters
    python family_letters.py export                          # export via SuperDocs' /v1/documents/export, then combine

Data lives in data/: district_template.html, comment_bank.json,
families.json. All fictional/synthetic, safe to commit.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.request

CHAT_API_URL = "https://api.superdocs.app/v1/chat"
EXPORT_API_URL = "https://api.superdocs.app/v1/documents/export"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# SuperDocs' translated HTML carries no dir/alignment markup of its own --
# correctly so, translation and layout direction are different concerns.
# Adding it explicitly here is defense in depth: SuperDocs' own export
# renderer is a real browser engine and should honor dir="rtl" correctly on
# its own, but earlier testing (see RECONCILIATION_REPORT.md) found that a
# local LibreOffice HTML->PDF pass did NOT infer RTL paragraph alignment
# from a single dir="rtl" on <html> alone -- so every block is tagged
# individually rather than trusting any single renderer's inference.
RTL_LANGUAGE_CODES = {"ar", "he", "fa", "ur"}


def wrap_html(inner_html: str, language_code: str, language_name: str) -> str:
    if language_code in RTL_LANGUAGE_CODES:
        import re

        inner_html = re.sub(r"<(h1|h2|h3|p)(?![^>]*dir=)", r'<\1 dir="rtl"', inner_html)
        style = (
            "body{direction:rtl;text-align:right;}"
            "p,h1,h2,h3{direction:rtl;text-align:right;unicode-bidi:embed;}"
        )
        return (
            f'<html dir="rtl" lang="{language_code}"><head><meta charset="utf-8">'
            f"<style>{style}</style></head><body dir=\"rtl\">{inner_html}</body></html>"
        )
    return f'<html lang="{language_code}"><body>{inner_html}</body></html>'


def load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def save_json(name, data):
    with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_template():
    with open(os.path.join(DATA_DIR, "district_template.html"), encoding="utf-8") as f:
        return f.read()


def call_superdocs_chat(message: str, document_html: str, session_id: str, api_key: str) -> str:
    body = json.dumps(
        {"message": message, "session_id": session_id, "document_html": document_html}
    ).encode("utf-8")
    req = urllib.request.Request(
        CHAT_API_URL,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["document_changes"]["updated_html"]


def call_superdocs_export(html: str, fmt: str, filename: str, api_key: str) -> bytes:
    """Calls SuperDocs' real /v1/documents/export endpoint -- the actual
    product surface for turning edited HTML into a downloadable file, per
    docs.superdocs.app/concepts/documents#exporting-documents. Exports are
    free (don't consume the monthly operation allowance). Returns the raw
    file bytes; caller writes them to disk."""
    body = json.dumps(
        {"html": html, "format": fmt, "options": {"filename": filename}}
    ).encode("utf-8")
    req = urllib.request.Request(
        EXPORT_API_URL,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        warnings_header = resp.headers.get("X-Export-Warnings")
        if warnings_header:
            import base64

            warnings = json.loads(base64.b64decode(warnings_header))
            for w in warnings:
                print(f"  export warning: {w.get('code')}: {w.get('message')}")
        return resp.read()


def merge_fields(template: str, family: dict, comment_text: str) -> str:
    """Deterministic, byte-exact field merge -- done in plain Python, not by
    asking the LLM to do it. Tried the single "merge AND translate" prompt
    first (ask SuperDocs to fill fields and translate in one instruction);
    it left stale, untranslated {{comment_text}}/{{teacher_name}} scaffolding
    behind alongside a duplicated, partially-filled paragraph -- a real
    product limitation worth designing around, not papering over. Splitting
    "merge" (deterministic, Python, always correct) from "translate" (one
    single-purpose SuperDocs call) fixed it completely: see PROGRESS.md."""
    return (
        template.replace("{{child_name}}", family["child_name"])
        .replace("{{grade}}", family["grade"])
        .replace("{{teacher_name}}", family["teacher_name"])
        .replace("{{comment_text}}", comment_text)
    )


def build_translate_prompt(family: dict) -> str:
    return (
        f"Translate this entire document into {family['language_name']}, preserving the "
        f"exact layout, heading structure, and formatting. Do not translate proper names "
        f"(student, teacher, or district names)."
    )


def generate_letter(family: dict, comment_bank: dict, template: str, api_key: str) -> str:
    comment_text = comment_bank[family["comment_id"]]
    merged_html = merge_fields(template, family, comment_text)
    message = build_translate_prompt(family)
    html = call_superdocs_chat(message, merged_html, f"family-letter-{family['id']}", api_key)
    wrapped = wrap_html(html, family["language_code"], family["language_name"])
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{family['id']}_{family['language_code']}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(wrapped)
    return out_path


def cmd_generate(api_key: str) -> None:
    families = load_json("families.json")
    comment_bank = load_json("comment_bank.json")
    template = load_template()
    for family in families:
        if family["status"] != "pending":
            print(f"skip {family['id']} (status={family['status']})")
            continue
        print(f"generating {family['id']} ({family['language_name']})...")
        path = generate_letter(family, comment_bank, template, api_key)
        print(f"  -> {path}")


def cmd_edit_comment(comment_id: str, new_text: str, api_key: str) -> None:
    """The whole point of a shared comment bank: edit once, and the change
    flows to every generated letter that's still pending. Letters already
    marked `sent` must never change retroactively."""
    comment_bank = load_json("comment_bank.json")
    if comment_id not in comment_bank:
        sys.exit(f"unknown comment id {comment_id}")
    comment_bank[comment_id] = new_text
    save_json("comment_bank.json", comment_bank)
    print(f"updated {comment_id} in comment bank")

    families = load_json("families.json")
    template = load_template()
    affected = [f for f in families if f["comment_id"] == comment_id and f["status"] == "pending"]
    untouched = [f for f in families if f["comment_id"] == comment_id and f["status"] != "pending"]

    for family in untouched:
        print(f"  leaving {family['id']} untouched (status={family['status']}, already sent)")
    for family in affected:
        print(f"  regenerating {family['id']} ({family['language_name']}) with updated comment...")
        path = generate_letter(family, comment_bank, template, api_key)
        print(f"    -> {path}")


def cmd_export(api_key: str) -> None:
    """Per-family PDFs come from SuperDocs' own /v1/documents/export
    endpoint (format="pdf"), not a local conversion tool -- this is the real
    product surface for the "approve -> export" half of the four-call
    contract (upload, edit, approve, export) described in the task brief.

    The combined print run is still assembled locally, by merging the
    already-exported PDFs via `pdfunite`: that's a step SuperDocs' export
    endpoint doesn't offer (it exports one document per call), and CSS
    page-break-* does not reliably survive HTML->PDF conversion in any
    renderer tested, so merging real, already-paginated PDF pages is the
    robust design regardless of which renderer produced them."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_files = sorted(
        p for p in glob.glob(os.path.join(OUTPUT_DIR, "*.html")) if "_print_run_combined" not in p
    )
    pdf_paths = []
    for html_path in html_files:
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        filename = os.path.splitext(os.path.basename(html_path))[0]
        pdf_bytes = call_superdocs_export(html, "pdf", filename, api_key)
        pdf_path = html_path.replace(".html", ".pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"exported {pdf_path} (via SuperDocs /v1/documents/export)")
        pdf_paths.append(pdf_path)

    if pdf_paths:
        combined_pdf_path = os.path.join(OUTPUT_DIR, "_print_run_combined.pdf")
        subprocess.run(["pdfunite", *pdf_paths, combined_pdf_path], check=True)
        print(f"exported combined print run -> {combined_pdf_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="generate all pending family letters")
    sub.add_parser("export", help="export per-family PDFs via SuperDocs' export API, then combine")
    edit_p = sub.add_parser("edit-comment", help="edit a comment bank entry and regenerate affected pending letters")
    edit_p.add_argument("comment_id")
    edit_p.add_argument("new_text")
    args = ap.parse_args()

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if args.command in ("generate", "edit-comment", "export") and not api_key:
        sys.exit(
            "Set SUPERDOCS_API_KEY first (use.superdocs.app -> Settings -> API Keys -> Create)."
        )

    if args.command == "generate":
        cmd_generate(api_key)
    elif args.command == "edit-comment":
        cmd_edit_comment(args.comment_id, args.new_text, api_key)
    elif args.command == "export":
        cmd_export(api_key)


if __name__ == "__main__":
    main()
