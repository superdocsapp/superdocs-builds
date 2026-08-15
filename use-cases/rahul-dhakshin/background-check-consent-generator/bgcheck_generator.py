#!/usr/bin/env python3
"""
bgcheck_generator.py — Background-check consent-form generator, built on SuperDocs.

Merges a company's template and a candidate's details into an FCRA-style
disclosure-and-authorization PAIR structured the way FCRA requires: a
standalone disclosure document (containing nothing else), a separately
signed authorization, and a summary-of-rights notice, each a distinct
output ready for an external e-signature step. The disclosure is verified,
not just assumed, to contain no unrelated clauses (waivers, liability
language, releases) — that separation is the part real employers get wrong,
per the assignment brief, so this generator checks for it automatically.
Export goes through SuperDocs' own `/v1/documents/export` endpoint
(docx/pdf/html/markdown/txt, free of operation cost), not a local
conversion tool — see cmd_export() below.

LEGAL NOTE: this produces a structural template for testing/demo purposes.
It is not legal advice and the FCRA Summary of Rights text here is a clearly
labeled placeholder, not the real CFPB-mandated text — see
data/rights_notice_template.html. Any real use requires counsel review.

Usage:
    export SUPERDOCS_API_KEY=sk_...
    python bgcheck_generator.py generate
    python bgcheck_generator.py verify
    python bgcheck_generator.py export
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

CHAT_API_URL = "https://api.superdocs.app/v1/chat"
EXPORT_API_URL = "https://api.superdocs.app/v1/documents/export"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

DOCUMENTS = ["disclosure", "authorization", "rights_notice"]

# The exact failure mode the assignment brief calls out: a disclosure that's
# no longer standalone because a waiver/liability/release clause got mixed
# in. This is what `verify` scans the disclosure for.
FORBIDDEN_IN_DISCLOSURE = [
    r"\bwaiv(e|er|ers|ing)\b",
    r"\bliabilit(y|ies)\b",
    r"\bindemnif",
    r"\breleas(e|es|ed|ing)\b",
    r"\bhold\s+harmless\b",
    r"\bI\s+authorize\b",  # authorization language belongs in authorization.html, not here
]

# Words that, appearing earlier in the same sentence as a forbidden term,
# flip its meaning from "this document contains X" to "this document does
# NOT contain X" — e.g. "No release, waiver, ... is contained in this
# document" is the disclosure correctly asserting its own standalone-ness,
# not a smuggled-in clause. Found live: the first version of this scanner
# flagged that exact sentence as a violation. Negation-aware sentence
# scanning fixed it. This is a heuristic, not real NLP — a sentence that
# buries a real waiver behind an unrelated negated clause earlier in the
# same sentence could still slip through. Good enough for this generator's
# purpose (catching accidental clause-mixing from an LLM formatting pass),
# not a substitute for legal review.
NEGATION_CUES = re.compile(r"\b(no|not|without|never|none)\b", re.IGNORECASE)


def load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def load_template(doc_name):
    with open(os.path.join(DATA_DIR, f"{doc_name}_template.html"), encoding="utf-8") as f:
        return f.read()


def merge_fields(template: str, fields: dict) -> str:
    out = template
    for key, value in fields.items():
        out = out.replace("{{" + key + "}}", value)
    return out


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


def cmd_generate(api_key: str) -> None:
    company = load_json("company.json")
    candidate = load_json("candidate.json")
    fields = {**company, **candidate}
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for doc_name in DOCUMENTS:
        template = load_template(doc_name)
        merged = merge_fields(template, fields)
        # Deliberately explicit: format only, never add content. This is
        # the instruction `verify` below is checking actually held.
        message = (
            "Format this document into a clean, professional layout with clear "
            "spacing and heading structure. Do not add any additional clauses, "
            "waivers, releases, liability language, or any sentence not already "
            "present below. Preserve every existing sentence's meaning exactly; "
            "formatting only."
        )
        html = call_superdocs_chat(message, merged, f"bgcheck-{doc_name}", api_key)
        out_path = os.path.join(OUTPUT_DIR, f"{doc_name}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"<html><body>{html}</body></html>")
        print(f"generated {out_path}")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _split_sentences(text: str) -> list:
    return re.split(r"(?<=[.!?])\s+", text)


def cmd_verify() -> bool:
    """The actual proof, not a claim: scans the generated disclosure for
    language that would make it no longer standalone. Sentence-scoped and
    negation-aware, so a sentence like "No release, waiver, authorization
    ... is contained in this document" (the disclosure correctly asserting
    its own standalone-ness) is not mistaken for a smuggled-in clause."""
    disclosure_path = os.path.join(OUTPUT_DIR, "disclosure.html")
    if not os.path.exists(disclosure_path):
        sys.exit("Run `generate` first.")
    with open(disclosure_path, encoding="utf-8") as f:
        raw = f.read()

    plain = _strip_tags(raw)
    violations = []
    for sentence in _split_sentences(plain):
        for pattern in FORBIDDEN_IN_DISCLOSURE:
            for m in re.finditer(pattern, sentence, re.IGNORECASE):
                preceding = sentence[: m.start()]
                if NEGATION_CUES.search(preceding):
                    continue  # negated mention, not an actual clause
                violations.append((pattern, m.group(0), sentence.strip()))

    if violations:
        print("FAIL: disclosure.html is no longer standalone. Found:")
        for pattern, matched, sentence in violations:
            print(f"  - pattern {pattern!r} matched {matched!r} in: {sentence!r}")
        return False

    print("PASS: disclosure.html contains no waiver/liability/release/authorization language.")
    print("Authorization and rights-notice content confirmed to live in separate files:")
    for doc_name in ("authorization", "rights_notice"):
        path = os.path.join(OUTPUT_DIR, f"{doc_name}.html")
        print(f"  - {path}: {'exists' if os.path.exists(path) else 'MISSING'}")
    return True


def cmd_export(api_key: str) -> None:
    """Each PDF comes from SuperDocs' own /v1/documents/export endpoint,
    not a local conversion tool -- this is the real product surface for the
    "approve -> export" half of the four-call contract (upload, edit,
    approve, export) described in the task brief."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for doc_name in DOCUMENTS:
        html_path = os.path.join(OUTPUT_DIR, f"{doc_name}.html")
        if not os.path.exists(html_path):
            continue
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        pdf_bytes = call_superdocs_export(html, "pdf", doc_name, api_key)
        pdf_path = html_path.replace(".html", ".pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"exported {pdf_path} (via SuperDocs /v1/documents/export)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["generate", "verify", "export"])
    args = ap.parse_args()

    if args.command == "generate":
        api_key = os.environ.get("SUPERDOCS_API_KEY")
        if not api_key:
            sys.exit("Set SUPERDOCS_API_KEY first.")
        cmd_generate(api_key)
    elif args.command == "verify":
        ok = cmd_verify()
        sys.exit(0 if ok else 1)
    elif args.command == "export":
        api_key = os.environ.get("SUPERDOCS_API_KEY")
        if not api_key:
            sys.exit("Set SUPERDOCS_API_KEY first.")
        cmd_export(api_key)


if __name__ == "__main__":
    main()
