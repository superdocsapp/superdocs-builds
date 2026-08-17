#!/usr/bin/env python3
"""
Render STUDY.md and ARTICLE.md into the docx-notes site.

Both pages are built to what the study measured: the symptom in the title rather
than a question, code near the top, a visible date, and no external requests.

Usage:  python3 13_publish.py [site-dir]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Developer" / "docx-notes")

PAGES = [
    ("STUDY.md", "what-people-are-stuck-on",
     "What people are stuck on when software has to touch a Word document",
     "Fifteen of the most-read pages on document tooling, what they have in common, "
     "and the split between what's solved and what isn't."),
    ("ARTICLE.md", "tracked-changes-lost-in-conversion",
     "Tracked changes disappear when a document round-trips through markdown",
     "Why w:ins, w:del and comment anchors don't survive a conversion, and how to "
     "check whether your pipeline drops them."),
]

CSS = """
  :root { color-scheme: light dark; }
  body { max-width: 46rem; margin: 0 auto; padding: 2.5rem 1.25rem;
         font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         color: #1a1a1a; background: #fff; }
  h1 { font-size: 1.6rem; line-height: 1.25; }
  h2 { font-size: 1.15rem; margin-top: 2rem; }
  a { color: #0b57d0; }
  time, .byline { color: #666; font-size: .9rem; }
  pre { background: #f6f7f9; padding: .9rem 1rem; overflow-x: auto; border-radius: 6px;
        font-size: .85rem; line-height: 1.5; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
  pre code { font-size: 1em; }
  table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto;
          font-size: .9rem; margin: 1.2rem 0; }
  th, td { border: 1px solid #ddd; padding: .45rem .6rem; text-align: left; vertical-align: top; }
  th { background: #f6f7f9; }
  blockquote { border-left: 3px solid #ddd; margin: 1.2rem 0; padding: .2rem 0 .2rem 1rem;
               color: #444; }
  em { color: #444; }
  @media (prefers-color-scheme: dark) {
    body { color: #e6e6e6; background: #111; } a { color: #8ab4f8; }
    time, .byline, em { color: #9aa0a6; }
    pre { background: #1b1b1b; } th { background: #1b1b1b; }
    th, td { border-color: #333; } blockquote { border-left-color: #333; color: #bbb; }
  }
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<style>{css}</style>
</head>
<body>
<p class="byline"><a href="../">docx notes</a></p>
{body}
</body>
</html>
"""


def render(md_text: str) -> str:
    import markdown
    return markdown.Markdown(extensions=["extra", "sane_lists", "toc"]).convert(md_text)


def main() -> int:
    if not SITE.exists():
        print(f"site not found: {SITE}")
        return 2

    # Remove the pages these replace, so the old text stops being served.
    for stale in ("what-a-cited-page-contains", "tracked-change-author-blank"):
        d = SITE / stale
        if d.exists():
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
            print(f"removed {stale}/")

    entries = []
    for src, slug, title, desc in PAGES:
        body = render((HERE / src).read_text(encoding="utf-8"))
        out = SITE / slug
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(
            TEMPLATE.format(title=title, desc=desc, css=CSS, body=body), encoding="utf-8")
        print(f"wrote {slug}/index.html")
        entries.append((slug, title))

    index = SITE / "index.html"
    html = index.read_text(encoding="utf-8")
    items = "\n".join(
        f'  <li><a href="{slug}/">{title}</a><br>\n'
        f'      <time datetime="2026-08-17">17 August 2026</time></li>'
        for slug, title in entries)
    html = re.sub(r"<ul>.*?</ul>", f"<ul>\n{items}\n</ul>", html, flags=re.S)
    index.write_text(html, encoding="utf-8")
    print("updated index.html")

    # Nothing on these pages may fetch anything from another host.
    for slug, _ in entries:
        text = (SITE / slug / "index.html").read_text(encoding="utf-8")
        external = re.findall(r'(?:src|href)="(https?://[^"]+)"', text)
        offenders = [u for u in external if not u.startswith(("https://stackoverflow.com",
                                                              "https://github.com",
                                                              "https://news.ycombinator.com"))]
        subresources = re.findall(r'<(?:img|script|link)[^>]+(?:src|href)="https?://', text)
        print(f"{slug}: {len(external)} outbound links, {len(subresources)} external subresources"
              f"{' — PROBLEM' if subresources else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
