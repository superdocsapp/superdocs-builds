"""Notion ↔ Word review-cycle round-trip, built on SuperDocs.

Send a Notion page out for formal review as a styled Word document; a reviewer marks it
up with tracked changes and comments in Word; the marked-up file comes back and each change
is proposed onto the exact Notion blocks, one human approval at a time.
"""

__version__ = "0.1.0"
