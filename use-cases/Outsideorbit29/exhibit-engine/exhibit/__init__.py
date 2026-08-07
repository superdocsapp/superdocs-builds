"""Evidence exhibit indexer and cover-page engine.

An immigration paralegal's tool: take a brief and a pile of mixed-format
evidence, propose an exhibit order that follows the brief's argument, generate a
numbered cover page per exhibit (what it proves), build an exhibit index with
page ranges that exactly match the assembled packet, insert in-brief citations at
the points that rely on each exhibit, and export the whole filing as one
paginated file. Adding an exhibit late renumbers covers, index, citations and
page ranges together.

Run it with ``python -m exhibit.cli`` or the ``exhibit-engine`` console script.
"""

from __future__ import annotations

__version__ = "1.0.0"

from .model import Citation, Exhibit, ExhibitSet, PaginatedPacket
from .order import EvidenceItem
from .paging import paginate_set, render_packet

__all__ = [
    "Citation",
    "EvidenceItem",
    "Exhibit",
    "ExhibitSet",
    "PaginatedPacket",
    "paginate_set",
    "render_packet",
]
