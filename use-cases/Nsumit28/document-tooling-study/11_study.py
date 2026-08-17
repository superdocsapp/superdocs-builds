#!/usr/bin/env python3
"""
A2r — select fifteen pages from the candidate pool and measure each one.

Selection rule, fixed before the picks were made:

  1. Relevance. The page has to be about doing something to a real document with
     code or with an AI: editing in place, tracked changes, comments, keeping
     styles, docx to and from markdown or HTML, templates, diffing, OOXML Word
     refuses to open, pulling tables out of PDFs, or driving any of that from an
     agent.
  2. Reach. Prefer the highest counter the platform publishes, because that is
     the evidence people actually land there.
  3. Currency. Active in 2024 or later, unless it is a long-lived reference that
     still ranks.
  4. Spread. At least three platforms, and no more than four rows from one
     problem area.

Every row is selected by its URL, taken from raw/10-candidates.tsv. Engagement
numbers come from that file — the platforms' own counters, recorded at collection
time — and are not re-derived here. Content is read through each platform's API,
so nothing depends on scraping a page and hoping the right thing came back.

Writes out/11-pages.csv and out/11-summary.json.
"""

from __future__ import annotations

import csv
import html
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
POOL = HERE / "raw" / "10-candidates.tsv"
OUT = HERE / "out"
UA = "Mozilla/5.0 (research; document-tooling study)"

# (url, problem area, why this one)
SELECTION = [
    ("https://stackoverflow.com/questions/16383237/how-can-doc-docx-files-be-converted-to-markdown-or-structured-text",
     "docx to markdown", "The most-viewed conversion question in the pool. People arrive here when a document has to leave Word."),
    ("https://stackoverflow.com/questions/14249811/markdown-to-docx-including-complex-template",
     "markdown to docx", "The same journey in reverse, and it asks specifically about keeping a template intact."),
    ("https://stackoverflow.com/questions/28532770/extract-identify-tables-from-pdf-python",
     "pdf tables", "Table extraction from PDF, one of the highest-reach questions in the set."),
    ("https://stackoverflow.com/questions/47533875/how-to-extract-a-table-as-text-from-the-pdf",
     "pdf tables", "A second table question with comparable reach, which shows the demand is not one thread."),
    ("https://stackoverflow.com/questions/34779724/python-docx-replace-string-in-paragraph-while-keeping-style",
     "edit without losing style", "The closest thing in the pool to what editing inside a document is for: change the words, keep the formatting."),
    ("https://stackoverflow.com/questions/17858598/add-styling-rules-in-pandoc-tables-for-odt-docx-output-table-borders",
     "styles through conversion", "Table styling surviving a conversion, still drawing activity."),
    ("https://stackoverflow.com/questions/4224649/diff-2-open-xml-word-documents",
     "diffing documents", "Comparing two Word files at the XML level."),
    ("https://stackoverflow.com/questions/53892070/inserting-a-comment-in-docx-file-using-python-3",
     "comments", "Adding a comment to a docx from code, which most libraries skip entirely."),
    ("https://github.com/cicero-im/plate/pull/66",
     "tracked changes", "Open 2026 work on importing and exporting tracked changes and comments, with a real thread on it."),
    ("https://github.com/cicero-im/plate/pull/131",
     "docx import/export", "Active 2026 work on getting docx in and out of an editor."),
    ("https://github.com/microsoft/markitdown/issues/1211",
     "tables", "The most-reacted feature request in the pool, about tables surviving a format change."),
    ("https://github.com/LegalQuants/lq-ai/pull/315",
     "AI editing in Word", "A 2026 request for AI editing inside Word itself, which is exactly this product surface."),
    ("https://github.com/tabulapdf/tabula-java",
     "pdf tables", "The highest-scoring document story in the pool and the tool people still link to."),
    ("https://github.com/PSPDFKit/nutrient-dws-mcp-server",
     "agents on documents", "An MCP server for document processing — the 2026 shape of this problem."),
    ("https://github.com/Lulzx/tinydocx",
     "docx libraries", "A 2025 Word/ODT library, which says the tooling layer is still being rebuilt."),
]

QUESTION_WORDS = re.compile(r"^(how|what|why|when|where|can|is|are|does|do|should|which)\b", re.I)


def words(text: str) -> int:
    return len(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).split())


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout) if out.stdout.strip().startswith(("{", "[")) else {}


def load_pool() -> dict:
    lines = [l for l in POOL.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    return {r["url"]: r for r in csv.DictReader(lines, delimiter="\t")}


def measure(url: str) -> dict:
    """Read the page's content through the API that owns it."""
    if "stackoverflow.com/questions/" in url:
        qid = url.split("/questions/")[1].split("/")[0]
        q = urllib.parse.urlencode({"site": "stackoverflow", "filter": "withbody"})
        it = (get_json(f"https://api.stackexchange.com/2.3/questions/{qid}?{q}")
              .get("items") or [{}])[0]
        body = it.get("body", "")
        return {"kind": "question", "words": words(body), "code_blocks": body.count("<pre"),
                "responses": it.get("answer_count", 0),
                "status": "answered" if it.get("is_answered") else "unanswered",
                "tags": ",".join(it.get("tags", [])[:4]),
                "api_title": html.unescape(it.get("title", ""))}

    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)", url)
    if m:
        owner, repo, _, num = m.groups()
        it = gh(f"repos/{owner}/{repo}/issues/{num}")
        body = it.get("body") or ""
        return {"kind": "issue/PR", "words": words(body),
                "code_blocks": (body.count("```") // 2),
                "responses": it.get("comments", 0),
                "status": it.get("state", ""),
                "tags": ",".join(l["name"] for l in (it.get("labels") or [])[:4]),
                "api_title": it.get("title", "")}

    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/?$", url)
    if m:
        owner, repo = m.groups()
        it = gh(f"repos/{owner}/{repo}")
        readme = gh(f"repos/{owner}/{repo}/readme")
        import base64
        text = ""
        if readme.get("content"):
            text = base64.b64decode(readme["content"]).decode("utf-8", "replace")
        return {"kind": "project", "words": words(text),
                "code_blocks": text.count("```") // 2,
                "responses": it.get("stargazers_count", 0),
                "status": f"{it.get('stargazers_count', 0)} stars",
                "tags": ",".join((it.get("topics") or [])[:4]),
                "api_title": it.get("full_name", "")}

    return {"kind": "page", "words": 0, "code_blocks": 0, "responses": 0,
            "status": "", "tags": "", "api_title": ""}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    pool = load_pool()
    rows = []

    for url, problem, why in SELECTION:
        base = pool.get(url)
        if not base:
            print(f"  NOT IN POOL, skipped: {url}", file=sys.stderr)
            continue
        try:
            met = measure(url)
        except Exception as e:
            print(f"  could not measure {url}: {e}", file=sys.stderr)
            continue
        title = met["api_title"] or base["title"]
        rows.append({
            "platform": base["platform"], "problem": problem, "title": title, "url": url,
            "engagement": int(base["engagement"] or 0), "engagement_kind": base["engagement_kind"],
            "reach": int(base["secondary"] or 0), "reach_kind": base["secondary_kind"],
            "kind": met["kind"], "words": met["words"], "code_blocks": met["code_blocks"],
            "responses": met["responses"], "status": met["status"], "tags": met["tags"],
            "question_shaped_title": bool(QUESTION_WORDS.match(title)),
            "created": base["created"], "last_activity": base["updated"],
            "why_selected": why,
        })
        r = rows[-1]
        print(f"{r['platform'][:4]:<4} {r['engagement']:>4} {r['engagement_kind'][:5]:<6} "
              f"{r['reach']:>7} {r['reach_kind'][:6]:<7} {r['words']:>5}w {r['code_blocks']}cb  {title[:46]}")

    cols = list(rows[0].keys()) if rows else []
    with (OUT / "11-pages.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    ws = sorted(r["words"] for r in rows)
    so = [r for r in rows if r["platform"] == "Stack Overflow"]
    summary = {
        "pages": n,
        "platforms": {p: sum(1 for r in rows if r["platform"] == p)
                      for p in sorted({r["platform"] for r in rows})},
        "problem_areas": len({r["problem"] for r in rows}),
        "median_words": ws[n // 2] if n else 0,
        "with_code": sum(1 for r in rows if r["code_blocks"] > 0),
        "question_shaped_titles": sum(1 for r in rows if r["question_shaped_title"]),
        "stackoverflow_views_total": sum(r["reach"] for r in so),
        "active_2024_or_later": sum(1 for r in rows if str(r["last_activity"])[:4] >= "2024"
                                    or (str(r["last_activity"]).isdigit()
                                        and int(r["last_activity"]) > 1704067200)),
    }
    (OUT / "11-summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n{n} pages measured")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
