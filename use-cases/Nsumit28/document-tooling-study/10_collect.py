#!/usr/bin/env python3
"""
A1r — collect candidate pages for the redone study.

Difference from the first pass: instead of recording whatever a search tool
happened to cite, this queries the platforms directly and pulls their own
engagement counters. Stack Overflow gives score and view count, GitHub gives
comments and reactions, Hacker News gives points and comments. Those are
published numbers, so every row in the study can be checked by clicking it.

Fifteen problems, all things people hit when an AI or a script has to read or
edit a real document, and all still live in 2026.

Writes raw/10-candidates.tsv. No selection happens here — that is a separate
step, so the ranking rule can be written down before the candidates are seen.

Usage:  python3 10_collect.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "raw" / "10-candidates.tsv"

UA = "Mozilla/5.0 (research; document-tooling study)"

# The problem set. Each is a real failure people hit when a program or an agent
# has to work on a document that a human will open afterwards.
PROBLEMS = [
    # (slug, long query for GitHub's index, short keyword query for Stack Overflow
    #  and HN — their full-text search returns nothing for long phrases)
    ("tracked-changes",     "docx tracked changes author blank programmatically", "docx tracked changes author"),
    ("agent-edits-docx",    "AI agent edit docx without breaking formatting",     "python-docx preserve formatting"),
    ("section-edit",        "LLM rewrites whole document instead of one section", "docx replace text keep formatting"),
    ("html-to-docx-tables", "convert HTML to docx preserve table formatting",     "html to docx table"),
    ("docx-comments",       "add comments to docx programmatically python",       "python-docx comments"),
    ("style-loss",          "docx styles lost after programmatic edit",           "docx styles lost"),
    ("docx-mcp",            "MCP server Word document editing agent",             "MCP server document"),
    ("pdf-table-extract",   "extract tables from PDF to spreadsheet accurately",  "extract table from pdf"),
    ("contract-redline",    "automate contract redlining review AI",              "contract redline automation"),
    ("template-merge",      "generate docx from template placeholders bulk",      "docx template merge field"),
    ("md-docx-roundtrip",   "markdown to docx round trip loses formatting",       "markdown to docx"),
    ("large-doc-context",   "large document exceeds LLM context window chunking", "chunking large document llm"),
    ("docx-compare",        "compare two docx files show differences",            "compare two docx files"),
    ("esign-docx",          "e-signature integration document workflow API",      "esignature api document"),
    ("ooxml-validity",      "generated OOXML invalid Word won't open file",       "docx corrupt word cannot open"),
]


def clean(v) -> str:
    """Collapse whitespace. GitHub titles contain newlines, which split a TSV row
    into two and quietly corrupt every column after it."""
    return " ".join(str(v).split())


def get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def stackoverflow(query: str, n: int = 4):
    """Score and view_count are Stack Overflow's own published counters."""
    q = urllib.parse.urlencode({
        "order": "desc", "sort": "votes", "q": query, "site": "stackoverflow",
        "pagesize": n, "filter": "default",
    })
    try:
        data = get_json(f"https://api.stackexchange.com/2.3/search/advanced?{q}")
    except Exception as e:
        print(f"  stackoverflow failed: {e}", file=sys.stderr)
        return []
    rows = []
    for it in data.get("items", [])[:n]:
        rows.append({
            "platform": "Stack Overflow",
            "title": it.get("title", ""),
            "url": it.get("link", ""),
            "engagement": it.get("score", 0),
            "engagement_kind": "votes",
            "secondary": it.get("view_count", 0),
            "secondary_kind": "views",
            "answers": it.get("answer_count", 0),
            "created": it.get("creation_date", 0),
            "updated": it.get("last_activity_date", 0),
        })
    return rows


def github(query: str, n: int = 4):
    """Comments and reactions on issues; both are visible on the page."""
    try:
        out = subprocess.run(
            ["gh", "api", "-X", "GET", "search/issues",
             "-f", f"q={query} in:title,body", "-f", "sort=reactions",
             "-f", "order=desc", "-f", "per_page=" + str(n)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(out.stdout or "{}")
    except Exception as e:
        print(f"  github failed: {e}", file=sys.stderr)
        return []
    rows = []
    for it in data.get("items", [])[:n]:
        rows.append({
            "platform": "GitHub",
            "title": it.get("title", ""),
            "url": it.get("html_url", ""),
            "engagement": (it.get("reactions") or {}).get("total_count", 0),
            "engagement_kind": "reactions",
            "secondary": it.get("comments", 0),
            "secondary_kind": "comments",
            "answers": 0,
            "created": it.get("created_at", ""),
            "updated": it.get("updated_at", ""),
        })
    return rows


def hackernews(query: str, n: int = 3):
    q = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": n})
    try:
        data = get_json(f"https://hn.algolia.com/api/v1/search?{q}")
    except Exception as e:
        print(f"  hn failed: {e}", file=sys.stderr)
        return []
    rows = []
    for it in data.get("hits", [])[:n]:
        url = it.get("url") or f"https://news.ycombinator.com/item?id={it.get('objectID')}"
        rows.append({
            "platform": "Hacker News",
            "title": it.get("title", ""),
            "url": url,
            "engagement": it.get("points") or 0,
            "engagement_kind": "points",
            "secondary": it.get("num_comments") or 0,
            "secondary_kind": "comments",
            "answers": 0,
            "created": it.get("created_at", ""),
            "updated": it.get("created_at", ""),
        })
    return rows


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cols = ["problem", "platform", "engagement", "engagement_kind", "secondary",
            "secondary_kind", "answers", "created", "updated", "title", "url"]
    seen: set[str] = set()
    n_rows = 0

    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# A1r — candidate pages with each platform's own engagement counters\n")
        fh.write("# Collected 2026-08-16. Engagement numbers are the platform's, not mine.\n")
        fh.write("\t".join(cols) + "\n")

        for slug, gh_query, kw_query in PROBLEMS:
            print(f"{slug}: {kw_query}")
            rows = stackoverflow(kw_query) + github(gh_query) + hackernews(kw_query)
            for r in rows:
                if not r["url"] or r["url"] in seen:
                    continue
                seen.add(r["url"])
                r["problem"] = slug
                fh.write("\t".join(clean(r.get(c, "")) for c in cols) + "\n")
                n_rows += 1
            print(f"  {len(rows)} candidates")
            time.sleep(1.2)   # be polite to the free APIs

    print(f"\n{n_rows} unique candidates -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
