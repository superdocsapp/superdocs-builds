#!/usr/bin/env python3
"""
family_letters.py — Multilingual family communication engine, built on SuperDocs.

Takes a district template + a teacher comment bank + a family roster, and
generates each family's report-card comment letter in their recorded home
language: merges in the child's and teacher's details and the selected
teacher comment, and asks SuperDocs to translate the whole letter while
preserving the district template's layout across scripts (including
right-to-left and CJK).

Usage:
    export SUPERDOCS_API_KEY=sk_...
    python family_letters.py generate                       # generate all pending letters
    python family_letters.py edit-comment C1 "new text"      # edit a comment, regenerate ONLY affected pending letters
    python family_letters.py export                          # render per-family PDFs + one combined print-run PDF

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

API_URL = "https://api.superdocs.app/v1/chat"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# SuperDocs' translated HTML carries no dir/alignment markup of its own --
# correctly so, translation and layout direction are different concerns.
# But PDF export (LibreOffice's HTML->PDF path) does NOT infer RTL
# paragraph alignment from a single dir="rtl" on <html>; without the
# explicit per-block styling below, Arabic/Hebrew/etc. render with correct
# script but left-aligned paragraphs. See RECONCILIATION_REPORT.md.
RTL_LANGUAGE_CODES = {"ar", "he", "fa", "ur"}


def wrap_html(inner_html: str, language_code: str, language_name: str) -> str:
    if language_code in RTL_LANGUAGE_CODES:
        # tag every block element dir="rtl" individually -- a single dir on
        # <html>/<body> is not enough for LibreOffice's PDF export to honor
        # right alignment per paragraph.
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


def call_superdocs(message: str, document_html: str, session_id: str, api_key: str) -> str:
    body = json.dumps(
        {"message": message, "session_id": session_id, "document_html": document_html}
    ).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["document_changes"]["updated_html"]


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
    html = call_superdocs(message, merged_html, f"family-letter-{family['id']}", api_key)
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


def _html_to_pdf(html_path: str) -> None:
    # pandoc's default LaTeX engine cannot render Arabic (babel has no
    # "arabic" language file in a typical install) or CJK (no matching
    # Unicode font mapping) -- it errors out on exactly the scripts this
    # build exists to support. LibreOffice's HTML->PDF path handles both
    # correctly, so it's used for every export here, not just as a fallback.
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", os.path.dirname(html_path), html_path],
        check=True,
    )


def cmd_export() -> None:
    """Per-family PDFs first, then the combined print run is assembled by
    merging those already-rendered PDFs (via `pdfunite`), not by relying on
    CSS page-break-* surviving an HTML->PDF conversion -- LibreOffice's
    Writer/Web HTML import filter does not honor page-break-before/-after
    at all (tried both; tried routing through an intermediate .odt too),
    so every "combined print run" attempt built that way silently ran every
    letter onto the same page. Merging real PDF pages sidesteps the whole
    problem and is the more robust design regardless."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_files = sorted(
        p for p in glob.glob(os.path.join(OUTPUT_DIR, "*.html")) if "_print_run_combined" not in p
    )
    pdf_paths = []
    for html_path in html_files:
        _html_to_pdf(html_path)
        pdf_path = html_path.replace(".html", ".pdf")
        print(f"exported {pdf_path}")
        pdf_paths.append(pdf_path)

    if pdf_paths:
        combined_pdf_path = os.path.join(OUTPUT_DIR, "_print_run_combined.pdf")
        subprocess.run(["pdfunite", *pdf_paths, combined_pdf_path], check=True)
        print(f"exported combined print run -> {combined_pdf_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="generate all pending family letters")
    sub.add_parser("export", help="render per-family + combined print-run PDFs")
    edit_p = sub.add_parser("edit-comment", help="edit a comment bank entry and regenerate affected pending letters")
    edit_p.add_argument("comment_id")
    edit_p.add_argument("new_text")
    args = ap.parse_args()

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if args.command in ("generate", "edit-comment") and not api_key:
        sys.exit(
            "Set SUPERDOCS_API_KEY first (use.superdocs.app -> Settings -> API Keys -> Create)."
        )

    if args.command == "generate":
        cmd_generate(api_key)
    elif args.command == "edit-comment":
        cmd_edit_comment(args.comment_id, args.new_text, api_key)
    elif args.command == "export":
        cmd_export()


if __name__ == "__main__":
    main()
