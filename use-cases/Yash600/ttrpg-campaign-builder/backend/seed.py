"""
seed.py -- RETIRED in v2.

v1 auto-uploaded one hardcoded campaign ("The Shattered Crown") into
SuperDocs and the database at startup/on-demand. That auto-ingestion has
been deliberately removed: v2's data model (models.py) has no seed content
at all -- every Campaign starts empty, and every Document/Character/NPC/
Location is created or imported by a human through the API (see main.py's
POST /campaigns, POST /campaigns/{id}/documents, POST /campaigns/{id}
/documents/import, POST /campaigns/{id}/characters|npcs|locations).

This file is kept only so old invocations fail loudly with an explanation
instead of silently crashing on missing imports (the old models it used --
Entity, Reference, DocType, etc. -- no longer exist; see git history for
the v1 implementation if you need to reference it).

If you want sample content to try the app with, create it through the API
or the frontend's "New Campaign" / "Import Document" flows -- there is
intentionally no scripted shortcut around that anymore.
"""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "seed.py is retired in v2 -- there is no auto-ingestion. "
        "Create a campaign and its documents through the API or frontend instead "
        "(POST /campaigns, then /campaigns/{id}/documents or /documents/import).",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
