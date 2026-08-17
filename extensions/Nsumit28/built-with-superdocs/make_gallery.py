#!/usr/bin/env python3
"""
Generate the gallery page from gallery/manifest.json.

The manifest is the only place an entry exists. Adding a project means opening a
pull request against a JSON file that a human reads — not filling in a form that
writes straight to a page. That is deliberate: the review step is the product,
and a generator that can only render what the manifest already contains keeps it
impossible to add an entry without someone having reviewed it.

The page is standalone. CSS is inline, the badge is inlined as SVG, and there is
not one subresource request in the file — it renders identically from file://,
from GitHub Pages, or from a laptop on a plane. `verify_gallery.py` enforces that.

Usage:  python3 make_gallery.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "gallery" / "manifest.json"
BADGE = HERE / "badge.svg"
OUT = HERE / "index.html"

CORAL = "#f97766"
NEAR_BLACK = "#110b0b"
CREAM = "#fbfaf6"
WARM_GRAY = "#a09b97"

CSS = f"""
:root {{
  --coral: {CORAL}; --ink: {NEAR_BLACK}; --paper: {CREAM}; --muted: #6f6864;
  --rule: #e8e5e1; --card: #fff;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink: #f4f1ed; --paper: #14100f; --muted: {WARM_GRAY};
           --rule: #2a2422; --card: #1b1615; }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 46rem; margin: 0 auto; padding: 4rem 1.5rem 5rem; }}
header {{ border-bottom: 1px solid var(--rule); padding-bottom: 2.5rem; }}
h1 {{ font-size: clamp(2rem, 6vw, 2.75rem); line-height: 1.1; letter-spacing: -0.02em;
     margin: 0 0 1rem; }}
.standfirst {{ font-size: 1.125rem; color: var(--muted); margin: 0 0 2rem; max-width: 34rem; }}
.badge-strip {{ display: flex; align-items: center; gap: 0.875rem; flex-wrap: wrap; }}
.badge-strip svg {{ display: block; }}
.badge-strip span {{ font-size: 0.8125rem; color: var(--muted); }}
h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.1em;
     color: var(--muted); margin: 3.5rem 0 1.25rem; font-weight: 600; }}
.entry {{
  background: var(--card); border: 1px solid var(--rule); border-radius: 10px;
  padding: 1.5rem 1.5rem 1.25rem; margin-bottom: 1rem;
}}
.entry h3 {{ margin: 0 0 0.5rem; font-size: 1.1875rem; letter-spacing: -0.01em; }}
.entry h3 a {{ color: inherit; text-decoration: none;
               border-bottom: 2px solid var(--coral); }}
.entry h3 a:hover {{ color: var(--coral); }}
.entry p {{ margin: 0 0 1rem; color: var(--muted); }}
.did {{ margin: 0 0 1rem; padding: 0; list-style: none;
        border-left: 2px solid var(--coral); padding-left: 0.875rem; }}
.did li {{ font-size: 0.9375rem; margin-bottom: 0.25rem; }}
.meta {{ display: flex; gap: 1.25rem; flex-wrap: wrap; font-size: 0.8125rem;
         color: var(--muted); border-top: 1px solid var(--rule); padding-top: 0.875rem; }}
.meta a {{ color: var(--coral); }}
.note {{ font-size: 0.9375rem; font-style: italic; color: var(--muted);
         margin: 0 0 1rem; }}
.conflict {{ font-size: 0.875rem; color: var(--muted); margin: 0 0 1rem;
             background: rgba(249,119,102,0.08); border-radius: 6px;
             padding: 0.75rem 0.875rem; }}
.conflict strong {{ color: var(--coral); }}
.declined {{ border-style: dashed; background: transparent; }}
.declined h3 {{ color: var(--muted); font-size: 1.0625rem; }}
.code {{ display: inline-block; font: 600 0.75rem/1 ui-monospace, monospace;
         color: var(--coral); border: 1px solid var(--coral); border-radius: 4px;
         padding: 0.25rem 0.375rem; margin-right: 0.5rem; vertical-align: 0.1em; }}
.bar {{ font-size: 0.9375rem; color: var(--muted); }}
.bar a {{ color: var(--coral); }}
footer {{ margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--rule);
          font-size: 0.8125rem; color: var(--muted); }}
footer a {{ color: var(--coral); }}
"""


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def inline_badge() -> str:
    """Inline the badge so the page has no subresource of any kind."""
    svg = BADGE.read_text(encoding="utf-8")
    # Strip the XML prolog if one ever appears; inline SVG must not carry it.
    return re.sub(r"^<\?xml[^>]*\?>\s*", "", svg).strip()


def render_entry(e: dict) -> str:
    did = "".join(f"<li>{esc(s)}</li>" for s in e.get("superdocs_surfaces", []))
    ev = e.get("evidence", {})
    # A conflict is rendered on the entry itself, never in a footnote. An
    # undisclosed conflict is the failure mode of every curated list.
    conflict = (f'<p class="conflict"><strong>Conflict:</strong> '
                f'{esc(e["conflict"])}</p>') if e.get("conflict") else ""
    return f"""
<article class="entry">
  <h3><a href="{esc(e['link'])}">{esc(e['name'])}</a></h3>
  <p>{esc(e['summary'])}</p>
  <ul class="did">{did}</ul>
  <p class="note">{esc(e.get('reviewer_note', ''))}</p>
  {conflict}
  <div class="meta">
    <span>Submitted by {esc(e.get('submitted_by', 'the project owner'))}</span>
    <span>Reviewed {esc(e.get('reviewed_on', ''))}</span>
    <span><a href="{esc(ev.get('url', '#'))}">Evidence</a></span>
  </div>
</article>"""


def render_declined(d: dict) -> str:
    code = (f'<span class="code">{esc(d["reason_code"])}</span>'
            if d.get("reason_code") else "")
    return f"""
<article class="entry declined">
  <h3>{code}{esc(d['name'])}</h3>
  <p>{esc(d['why'])}</p>
  <div class="meta"><span>Declined {esc(d.get('reviewed_on', ''))}</span></div>
</article>"""


def build() -> str:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    g = m["gallery"]
    entries = "".join(render_entry(e) for e in m["entries"]
                      if e.get("decision") == "listed")
    declined = "".join(render_declined(d) for d in m.get("not_listed", []))
    note = m.get("_note_on_size", "")

    declined_block = f'<h2>Not in the gallery</h2>{declined}' if declined else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(g['title'])}</title>
<meta name="description" content="{esc(g['standfirst'][:150])}">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{esc(g['title'])}</h1>
  <p class="standfirst">{esc(g['standfirst'])}</p>
  <div class="badge-strip">
    {inline_badge()}
    <span>The badge every listed project may display.</span>
  </div>
</header>

<h2>Listed</h2>
{entries}
<p class="bar">{esc(note)}</p>

{declined_block}

<h2>Getting listed</h2>
<p class="bar">
  The bar is written down, and so are the reasons an entry is declined — see
  <a href="{esc(g.get('curation', 'CURATION.md'))}">the curation rule</a>, then
  <a href="{esc(g.get('submit', 'SUBMITTING.md'))}">submit a build</a>.
  Submissions come from the person who built the project. Nothing is harvested,
  and nothing is listed that its owner did not offer. A decline is answered in
  public with a numbered reason, not closed in silence.
</p>

<footer>
  Built and curated by Sumit Negi as a Round 2 candidate submission for
  <a href="https://twitter.com/superdocsapp">@superdocsapp</a>. Not an official
  SuperDocs property. Updated {esc(g.get('updated', ''))}.
</footer>
</div>
</body>
</html>
"""


def main() -> int:
    if not BADGE.exists():
        print("badge missing — run make_badge.py first")
        return 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    page = build()
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT}  {len(page.encode()):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
