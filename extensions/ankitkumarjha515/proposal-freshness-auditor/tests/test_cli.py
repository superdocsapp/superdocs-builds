"""What the command line must never do.

`audit` prints findings as [1], [2], [3]. If `review --approve 1` then
answers "unknown finding id '1'", the printed index is a lie and the
documented flow does not run. That is the bug this file pins shut.

The rule: anything the tool puts on screen next to a finding must be
accepted back as a way to name that finding. Display index, full id, or
an unambiguous id prefix — all three, or the screen is not telling the
truth.
"""

from __future__ import annotations

import pytest

from freshness_auditor.cli import AmbiguousIdError, _resolve_ids
from freshness_auditor.corpus import Corpus
from freshness_auditor.detect import Finding, detect_all
from freshness_auditor.ledger import FactLedger
from freshness_auditor.review import ReviewSession, UnknownFindingError

FACTS = "fixtures/facts.yaml"
CORPUS = "fixtures/corpus.yaml"


def real_findings() -> list[Finding]:
    ledger, corpus = FactLedger.load(FACTS), Corpus.load(CORPUS)
    out: list[Finding] = []
    for doc in corpus.documents():
        out.extend(detect_all(corpus.read_text(doc.id), doc.id, ledger))
    return out


@pytest.fixture
def session() -> ReviewSession:
    return ReviewSession.from_findings(real_findings())


def test_fixture_actually_produces_findings(session):
    # Every assertion below is worthless if the corpus is clean.
    assert len(session.items()) >= 3


def test_display_index_resolves_to_the_finding_it_was_printed_beside(session):
    ids = [i.finding.id for i in session.items()]

    assert _resolve_ids(session, ["1"]) == [ids[0]]
    assert _resolve_ids(session, ["3"]) == [ids[2]]


def test_indices_resolve_in_the_order_given_not_sorted(session):
    ids = [i.finding.id for i in session.items()]

    assert _resolve_ids(session, ["3", "1"]) == [ids[2], ids[0]]


def test_full_id_still_resolves(session):
    ids = [i.finding.id for i in session.items()]

    assert _resolve_ids(session, [ids[1]]) == [ids[1]]


def test_unambiguous_id_prefix_resolves(session):
    ids = [i.finding.id for i in session.items()]

    assert _resolve_ids(session, [ids[1][:8]]) == [ids[1]]


def test_id_prefix_is_case_insensitive(session):
    ids = [i.finding.id for i in session.items()]

    assert _resolve_ids(session, [ids[1][:8].upper()]) == [ids[1]]


def test_a_real_id_wins_over_the_same_string_read_as_an_index(session):
    """A hex id can be all digits. It must never be stolen by index lookup."""
    items = session.items()
    ids = [i.finding.id for i in items]
    # Force the collision the hash could produce on its own.
    object.__setattr__(items[-1].finding, "id", "1")
    session._index["1"] = len(items) - 1

    assert _resolve_ids(session, ["1"]) == ["1"]
    # and the genuine index 2 is untouched
    assert _resolve_ids(session, ["2"]) == [ids[1]]


def test_out_of_range_index_names_the_range(session):
    n = len(session.items())

    with pytest.raises(UnknownFindingError) as e:
        _resolve_ids(session, [str(n + 1)])

    assert str(n) in str(e.value)


def test_zero_is_rejected_because_the_display_starts_at_one(session):
    with pytest.raises(UnknownFindingError):
        _resolve_ids(session, ["0"])


def test_unknown_token_is_rejected(session):
    with pytest.raises(UnknownFindingError):
        _resolve_ids(session, ["nosuchthing"])


def test_ambiguous_prefix_is_refused_not_guessed(session):
    """Silently picking one of two would approve an edit nobody chose."""
    items = session.items()
    object.__setattr__(items[0].finding, "id", "abc111")
    object.__setattr__(items[1].finding, "id", "abc222")
    session._index.clear()
    session._index.update({i.finding.id: n for n, i in enumerate(items)})

    with pytest.raises(AmbiguousIdError) as e:
        _resolve_ids(session, ["abc"])

    assert "abc111" in str(e.value) and "abc222" in str(e.value)


def test_resolution_records_no_decision(session):
    """Naming a finding is not deciding it."""
    _resolve_ids(session, ["1", "2"])

    assert all(i.decision.value == "pending" for i in session.items())
