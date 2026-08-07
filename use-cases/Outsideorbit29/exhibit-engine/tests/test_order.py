"""Exhibit ordering: the evidence pile is sequenced to follow the brief's
argument — evidence appears in the order the brief relies on it."""

from __future__ import annotations

from exhibit.order import EvidenceItem, propose_order


def _items(*sources: str) -> list[EvidenceItem]:
    return [EvidenceItem(source=s, text=s.replace(".", " ").replace("-", " ")) for s in sources]


def test_order_follows_the_brief_argument():
    brief = (
        "First the passport and identity must be established. Next, the marriage "
        "must be shown. Only then does the lease matter, and finally the bank "
        "accounts matter."
    )
    items = _items("bank_accounts.pdf", "passport.pdf", "marriage.pdf", "lease.pdf")
    ordered = propose_order(brief, items)
    titles = [it.source for it in ordered]
    # passport is touched first by the brief, marriage second; lease and bank are
    # mentioned in the same final sentence, and the lease keyword appears first.
    assert titles.index("passport.pdf") < titles.index("marriage.pdf")
    assert titles.index("marriage.pdf") < titles.index("lease.pdf")
    assert titles.index("lease.pdf") < titles.index("bank_accounts.pdf")


def test_unmatched_evidence_appended_last_in_input_order():
    brief = "Only the lease and the bank matter to this application."
    items = _items("lease.pdf", "blueprint.pdf", "bank.pdf", "blueprint2.pdf")
    ordered = propose_order(brief, items)
    titles = [it.source for it in ordered]
    # the two blueprint files are never mentioned: they land last, in input order
    assert titles.index("blueprint.pdf") < titles.index("blueprint2.pdf")
    assert titles[-1] == "blueprint2.pdf"
    assert titles.index("lease.pdf") < titles.index("blueprint.pdf")


def test_empty_brief_preserves_input_order():
    items = _items("a.pdf", "b.pdf", "c.pdf")
    assert [it.source for it in propose_order("", items)] == ["a.pdf", "b.pdf", "c.pdf"]


def test_nothing_is_dropped():
    items = _items("a.pdf", "b.pdf", "c.pdf", "d.pdf")
    ordered = propose_order("the b document is central to this case", items)
    assert sorted(it.source for it in ordered) == sorted(it.source for it in items)
