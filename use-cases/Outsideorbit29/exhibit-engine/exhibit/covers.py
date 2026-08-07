"""Cover pages: the human-facing label of each exhibit.

Every exhibit gets a numbered cover page that says at a glance what the exhibit
is and what it proves. One renderer is used both for standalone cover markup and
for the pages inside the assembled packet, so covers can never diverge from what
the packet actually contains.
"""

from __future__ import annotations

import html as _html

from .model import Exhibit, ExhibitSet


def render_cover(exhibit: Exhibit) -> str:
    """One exhibit cover page (HTML), labelled with its current number."""
    source = _source_line(exhibit)
    return f"""
<section class="page exhibit-cover" style="page-break-before: always;">
  <div class="exhibit-no">Exhibit {exhibit.number}</div>
  <h1 class="exhibit-title">{_html.escape(exhibit.title)}</h1>
  <p class="exhibit-proves">{_html.escape(exhibit.proves)}</p>
  {source}
</section>"""


def render_packet_cover(set_: ExhibitSet) -> str:
    """The packet's own front cover page."""
    return f"""
<section class="page cover">
  <div class="packet-title">Filing Exhibit Packet</div>
  <div class="packet-count">{len(set_)} exhibits</div>
  <div class="packet-note">Prepared by the Evidence Exhibit Indexer</div>
</section>"""


def _source_line(exhibit: Exhibit) -> str:
    if exhibit.source is None or not str(exhibit.source):
        return ""
    return f'<div class="exhibit-source">Source: {_html.escape(exhibit.source.name)}</div>'
