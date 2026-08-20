"""Regression coverage for a real bug found while building the second
demo batch (see README "what broke"): the classifier used
`"contract" in lowered`, a substring check, so any word merely
containing the keyword -- "contracts", "subcontractor", plural forms,
disclaimer boilerplate mentioning the word in passing -- tripped
classification the same as an actual standalone use. Fixed by switching
to word-boundary regex matching in app/clients/fake_superdocs_client._classify.

These cases are siblings of the bug, not the exact failing sentence, to
prove the fix generalized (word-boundary matching) rather than
patching around one specific phrase."""
from __future__ import annotations

from app.clients.fake_superdocs_client import _classify


def test_plural_form_does_not_trigger_contract_classification():
    doc_class, _ = _classify(
        "This appendix lists prior contracts for reference purposes only."
    )
    assert doc_class == "unknown"


def test_word_containing_keyword_as_substring_does_not_trigger_amendment():
    doc_class, _ = _classify(
        "The commendable results this quarter warrant no further comment."
    )
    assert doc_class == "unknown"


def test_standalone_keyword_still_classifies_correctly():
    doc_class, _ = _classify("This Agreement is entered into between the parties.")
    assert doc_class == "contract"


def test_policyholder_does_not_falsely_trigger_policy_branch_ahead_of_invoice():
    # "policyholder" contains "policy" as a substring; make sure an
    # actual invoice (checked first) still wins when both words are
    # genuinely present, and a bare mention of "policyholder" alone
    # doesn't get miscounted as a standalone "policy".
    doc_class, _ = _classify("Invoice for the policyholder's Q1 premium. Amount Due: $500")
    assert doc_class == "invoice"


def test_bare_policyholder_mention_does_not_trigger_policy_classification():
    doc_class, _ = _classify("Please update the policyholder's mailing address on file.")
    assert doc_class == "unknown"
