"""What a commitment is, and how one is read back out of a document.

The distinction this whole build turns on: a commitment is an obligation somebody
**accepted**, not a topic somebody **mentioned**. "We should be able to have it by the
14th" is not a commitment. "We will deliver it by 14 March" is. Collapsing the two is
exactly the polite summary the card asks us not to write.

So candidates are classified rather than filtered. Everything the extraction considered
is kept, with a status saying why it did or did not qualify, and the rejected ones are
shown to the reviewer too. A tool that silently drops nine tenths of what it read is
asking to be trusted; one that shows its working can be checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

#: Somebody accepted this. It belongs in the letter.
FIRM = "firm"
#: Real once, replaced later in the same thread by a different date or scope.
SUPERSEDED = "superseded"
#: An intention, not an undertaking. "should be able to", "hopefully", "aim for".
HEDGED = "hedged"
#: Somebody reporting what a third party might do. Not theirs to promise.
SECOND_HAND = "second-hand"
#: Floated, not agreed.
PROPOSED = "proposed"

#: Only this one goes into the letter without a human saying otherwise.
INCLUDABLE = frozenset({FIRM})

ALL_STATUSES = (FIRM, SUPERSEDED, HEDGED, SECOND_HAND, PROPOSED)

_COLUMNS = ("party", "owes_to", "obligation", "due", "status", "source", "quote")

#: Quote marks a model wraps around the thing it is quoting. Stripped on the way in, so
#: the stored quote is the words themselves — otherwise every display adds another pair
#: and verification has to keep re-stripping them.
_WRAPPERS = "\"'`\u00ab\u00bb\u201e\u201c\u201d\u2018\u2019 \t"


def strip_wrappers(quote: str) -> str:
    return (quote or "").strip().strip(_WRAPPERS).strip()


@dataclass
class Commitment:
    party: str
    owes_to: str
    obligation: str
    due: str
    status: str
    source: str
    quote: str
    #: Filled in by the verifier: did this quote really appear in the thread?
    quote_found: bool = False
    quote_note: str = ""
    #: Which message the quote was actually located in, once verified.
    located_in: int | None = None

    @property
    def is_firm(self) -> bool:
        return self.status == FIRM

    @property
    def usable(self) -> bool:
        """Firm *and* backed by words somebody really wrote."""
        return self.is_firm and self.quote_found

    def to_public(self) -> dict[str, object]:
        return {
            "party": self.party, "owes_to": self.owes_to, "obligation": self.obligation,
            "due": self.due, "status": self.status, "source": self.source,
            "quote": self.quote, "quote_found": self.quote_found,
            "quote_note": self.quote_note, "located_in": self.located_in,
        }


class _TableReader(HTMLParser):
    """Pull the first table out of a generated document, as rows of cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            self._depth -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(c for c in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _normalise_status(raw: str) -> str:
    text = (raw or "").strip().lower().replace("_", "-")
    for status in ALL_STATUSES:
        if status in text:
            return status
    if "second" in text or "third" in text:
        return SECOND_HAND
    if "hedge" in text or "tentative" in text or "intent" in text:
        return HEDGED
    if "supersed" in text or "replaced" in text or "revised" in text:
        return SUPERSEDED
    if "propos" in text or "suggest" in text:
        return PROPOSED
    # Anything unrecognised is treated as not-firm. Guessing "firm" from a word we do
    # not understand is how an intention becomes an undertaking.
    return PROPOSED if text else PROPOSED


def _source_index(raw: str) -> str:
    match = re.search(r"\d+", raw or "")
    return match.group(0) if match else (raw or "").strip()


def parse(document_html: str) -> list[Commitment]:
    """Read commitments out of the document the extraction turn produced.

    Tolerant of column order changing, because the header row names the columns and
    trusting position alone would break the first time the model reorders them.
    """
    reader = _TableReader()
    reader.feed(document_html or "")
    if not reader.rows:
        return []

    header = [h.strip().lower() for h in reader.rows[0]]
    order = _column_order(header)
    if order is None:
        return []

    out: list[Commitment] = []
    for row in reader.rows[1:]:
        if len(row) < len(_COLUMNS):
            row = row + [""] * (len(_COLUMNS) - len(row))
        values = {name: row[order[name]] if order[name] < len(row) else ""
                  for name in _COLUMNS}
        if not values["obligation"] and not values["quote"]:
            continue
        out.append(Commitment(
            party=values["party"], owes_to=values["owes_to"],
            obligation=values["obligation"], due=values["due"],
            status=_normalise_status(values["status"]),
            source=_source_index(values["source"]),
            quote=strip_wrappers(values["quote"]),
        ))
    return out


def _column_order(header: list[str]) -> dict[str, int] | None:
    """Map our column names onto whatever the header row actually says."""
    synonyms = {
        "party": ("party", "who", "committed by", "from"),
        "owes_to": ("owes to", "to whom", "to", "beneficiary", "owed to"),
        "obligation": ("obligation", "commitment", "what", "undertaking"),
        "due": ("due", "when", "date", "deadline", "by"),
        "status": ("status", "kind", "type"),
        "source": ("source", "message", "source message", "from message"),
        "quote": ("quote", "exact quote", "verbatim", "evidence"),
    }
    order: dict[str, int] = {}
    for name, options in synonyms.items():
        for i, cell in enumerate(header):
            if any(cell == opt or cell.startswith(opt) for opt in options):
                order[name] = i
                break
    # The two that carry the meaning. Without them the table is not a commitments table.
    if "obligation" not in order or "quote" not in order:
        return None
    for name in _COLUMNS:
        order.setdefault(name, len(header) + list(_COLUMNS).index(name))
    return order


def _dedupe_key(c: "Commitment") -> tuple[str, ...]:
    return (
        _party_key(c.party),
        " ".join((c.obligation or "").lower().split()),
        " ".join((c.due or "").lower().split()),
        c.status,
    )


def dedupe(commitments: list["Commitment"]) -> list["Commitment"]:
    """Collapse rows that say the same thing about the same obligation.

    A model asked for a table will sometimes list one commitment twice — same party, same
    obligation, same date, same status — usually with the quote trimmed differently. Two
    rows for one promise makes a reviewer check the same thing twice and makes the counts
    lie, so the first is kept and the rest dropped. Rows differing in *any* of party,
    obligation, date or status are left alone: a date that moved is two commitments, not
    one, and collapsing those would hide exactly what this build exists to surface.
    """
    seen: set[tuple[str, ...]] = set()
    kept: list[Commitment] = []
    for c in commitments:
        key = _dedupe_key(c)
        if key in seen:
            continue
        seen.add(key)
        kept.append(c)
    return kept


def _party_key(party: str) -> str:
    return " ".join((party or "").lower().replace("&", "and").split())


def dangling_superseded(commitments: list[Commitment]) -> list[Commitment]:
    """Superseded commitments whose replacement is missing.

    If something was superseded then something replaced it, and the replacement is the
    one that belongs in the letter. An extraction that lists only the dead version is
    worse than one that lists neither: it looks complete while omitting the very
    obligation the thread was about.

    Observed live — a thread's revised delivery date was dropped while the original was
    correctly marked superseded, which would have produced a letter missing the vendor's
    actual commitment.
    """
    firm_parties = {_party_key(c.party) for c in commitments if c.is_firm}
    return [
        c for c in commitments
        if c.status == SUPERSEDED and _party_key(c.party) not in firm_parties
    ]


def summarise(commitments: list[Commitment]) -> dict[str, int]:
    counts = {status: 0 for status in ALL_STATUSES}
    for c in commitments:
        counts[c.status] = counts.get(c.status, 0) + 1
    counts["usable"] = sum(1 for c in commitments if c.usable)
    counts["unverified"] = sum(1 for c in commitments if not c.quote_found)
    counts["dangling"] = len(dangling_superseded(commitments))
    return counts
