"""Renderers that turn resolved property+block data into premium HTML.

The HTML is consumed by SuperDocs which round-trips it into print-grade
DOCX/PDF. Every renderer is deterministic and layout-stable across
languages: same structure, same photo slots, same page breaks — only
words change.
"""

from .manual import render_manual
from .card import render_card
from .listing import build_listing_texts, render_listing

__all__ = ["render_manual", "render_card", "render_listing", "build_listing_texts"]
