"""Claim extraction: what the corpus asserts, and what it does not.

Half of these tests are the ordinary kind — this sentence produces this claim.
The other half are the ones worth writing: places where a looser pattern would
also have matched, and the claim it would have produced would have been wrong.
`test_an_elapsed_time_is_not_read_as_an_alert_duration` is the clearest example;
without it, page 1008 — the page that is entirely correct, and the whole
zero-findings proof — grows a false positive.

There is also a rules-file test. `config/claims.yaml` is data, which means a
typo in it is a silent behaviour change rather than a syntax error, so the file
is validated: every emit names a group its own pattern actually captures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.claims import Claim
from reconciler.confluence.local import LocalSource
from reconciler.extract.patterns import extract_claims, load_patterns
from reconciler.extract.storage import Document


@pytest.fixture(scope="session")
def documents(runbooks_dir: Path) -> dict[str, Document]:
    source = LocalSource(runbooks_dir)
    return {ref.page_id: source.read(ref.page_id) for ref in source.pages()}


@pytest.fixture(scope="session")
def claims(documents: dict[str, Document]) -> dict[str, list[Claim]]:
    return {page_id: extract_claims(doc) for page_id, doc in documents.items()}


def subjects(claims: list[Claim]) -> set[str]:
    return {c.subject for c in claims}


def asserted(claims: list[Claim], subject: str) -> str | None:
    return next((c.asserted for c in claims if c.subject == subject), None)


# ------------------------------------------------------------- the rules ----


def test_the_rules_file_is_internally_consistent() -> None:
    """Data is not exempt from being checked.

    A subject template naming `{alert}` when the pattern has no `alert` group
    produces no claims and no error, which is the worst kind of bug in a
    configuration file.
    """
    for pattern in load_patterns():
        available = set()
        for regex in (pattern.regex, pattern.context):
            if regex:
                available |= set(regex.groupindex)
        if pattern.source == "table_rows":
            available |= {"label", "value"}
        available |= {"page_id"}

        for emit in pattern.emits:
            if not emit.group.isdigit():
                assert (
                    emit.group in available
                ), f"pattern {pattern.id} emits group {emit.group!r}, which it never captures"
            for token in _template_tokens(emit.subject):
                assert token in available, (
                    f"pattern {pattern.id} builds a subject from {{{token}}}, "
                    f"which it never captures"
                )


def _template_tokens(template: str) -> list[str]:
    import string

    return [name for _, name, _, _ in string.Formatter().parse(template) if name]


# ---------------------------------------------------------- what is found ---


def test_the_drifted_threshold_is_claimed_with_the_value_it_says(
    claims: dict[str, list[Claim]],
) -> None:
    assert asserted(claims["1001"], "alert:PaymentsApiHighLatency:threshold") == "800ms"


def test_the_same_threshold_is_claimed_on_the_slo_document_too(
    claims: dict[str, list[Claim]],
) -> None:
    """Two pages, one subject. The multi-document case exists in the register.

    The alert name is in a different sentence from the value on page 1007, which
    is what `context` is for.
    """
    assert asserted(claims["1007"], "alert:PaymentsApiHighLatency:threshold") == "800ms"


def test_the_claim_anchors_the_value_and_not_the_sentence(
    claims: dict[str, list[Claim]], documents: dict[str, Document]
) -> None:
    """A surgical edit needs a surgical anchor."""
    claim = next(c for c in claims["1001"] if c.subject == "alert:PaymentsApiHighLatency:threshold")
    body = documents["1001"].body
    assert body[claim.anchor.char_start : claim.anchor.char_end] == "800ms"


def test_a_deployment_sentence_yields_three_claims(claims: dict[str, list[Claim]]) -> None:
    found = subjects(claims["1001"])
    assert "workload:payments-api:name" in found
    assert "workload:payments-api:namespace" in found
    assert asserted(claims["1001"], "workload:payments-api:replicas") == "6"


def test_commands_are_read_out_of_code_macros(claims: dict[str, list[Claim]]) -> None:
    assert "namespace:payments" in subjects(claims["1001"])
    assert "workload:payments-api:name" in subjects(claims["1001"])


def test_a_ci_job_reference_is_claimed(claims: dict[str, list[Claim]]) -> None:
    assert "job:rollback-production" in subjects(claims["1001"])
    assert "job:drain-print-queue" in subjects(claims["1004"])
    assert "job:replay-failed-batch" in subjects(claims["1008"])


def test_escalation_targets_are_claimed_by_the_name_the_page_uses(
    claims: dict[str, list[Claim]],
) -> None:
    assert "escalation:Payments Core" in subjects(claims["1001"])
    assert "escalation:Payments Platform" in subjects(claims["1002"])
    assert "escalation:Fulfilment" in subjects(claims["1008"])


def test_a_dashboard_link_is_claimed_by_uid(claims: dict[str, list[Claim]]) -> None:
    assert "dashboard:abc123" in subjects(claims["1001"])
    assert "dashboard:zzz999" in subjects(claims["1004"])


def test_a_table_row_becomes_a_labelled_measure(claims: dict[str, list[Claim]]) -> None:
    """This is what puts RPO in the register instead of nowhere."""
    assert asserted(claims["1006"], "measure:automated-backup-retention") == "7 days"
    assert asserted(claims["1006"], "measure:rpo") == "15 minutes"
    assert asserted(claims["1006"], "measure:snapshot-window") == "03:00 UTC daily"


def test_the_table_header_row_asserts_nothing(claims: dict[str, list[Claim]]) -> None:
    assert "measure:measure" not in subjects(claims["1006"])


def test_the_injection_paragraph_becomes_a_claim_to_report(
    claims: dict[str, list[Claim]],
) -> None:
    directive = next(c for c in claims["1005"] if c.kind == "directive")
    assert directive.subject == "page:1005:instructions-to-automation"
    assert "ignore any earlier instructions" in directive.asserted.lower()


# ------------------------------------------------- what is deliberately not --


def test_an_elapsed_time_is_not_read_as_an_alert_duration(
    claims: dict[str, list[Claim]],
) -> None:
    """Page 1008 says "no batch has completed for 30 minutes".

    That is the threshold, not the alert's `for:` clause, and the ground truth
    `for` is 5m. A pattern that reads any "for N minutes" as a duration turns
    the one entirely-correct page in the corpus into a false positive, and the
    zero-findings proof with it.
    """
    found = subjects(claims["1008"])
    assert "alert:ManifestWorkerStalled:threshold" in found
    assert asserted(claims["1008"], "alert:ManifestWorkerStalled:threshold") == "30 minutes"
    assert "alert:ManifestWorkerStalled:for" not in found


def test_the_duration_is_claimed_when_it_really_does_trail_the_threshold(
    claims: dict[str, list[Claim]],
) -> None:
    assert asserted(claims["1001"], "alert:PaymentsApiHighLatency:for") == "10 minutes"


def test_a_macro_parameter_never_becomes_a_claim(claims: dict[str, list[Claim]]) -> None:
    assert not [c for c in claims["1004"] if "DEPOT" in c.asserted]


def test_a_rota_name_is_not_mistaken_for_an_alert_name(
    claims: dict[str, list[Claim]],
) -> None:
    """`Payments Core` has a space in it; a CamelCase alert name does not."""
    assert not [c for c in claims["1001"] if c.subject.startswith("alert:Payments Core")]


def test_the_escalation_sentence_does_not_produce_a_threshold(
    claims: dict[str, list[Claim]],
) -> None:
    """ "stays above the threshold for 30 minutes" has no number in it.

    A pattern that allowed a bare word after "above" would claim a threshold of
    "the" on a page that is correct there.
    """
    thresholds = [c for c in claims["1001"] if c.kind == "threshold"]
    assert all(any(ch.isdigit() for ch in c.asserted) for c in thresholds)


def test_a_placeholder_namespace_is_still_claimed(claims: dict[str, list[Claim]]) -> None:
    """Claimed, so it can be reported unverifiable rather than being invisible."""
    placeholder = next(c for c in claims["1003"] if c.subject.startswith("namespace:<"))
    assert placeholder.asserted == "<your-namespace>"


# ------------------------------------------------------------- properties ---


def test_extraction_is_deterministic(documents: dict[str, Document]) -> None:
    """Two runs over one page produce the same ids in the same order.

    Without this, "no drift found" and "the same drift found again" are
    indistinguishable in the register.
    """
    for document in documents.values():
        first = [c.claim_id for c in extract_claims(document)]
        second = [c.claim_id for c in extract_claims(document)]
        assert first == second


def test_every_claim_anchors_inside_its_own_page(
    claims: dict[str, list[Claim]], documents: dict[str, Document]
) -> None:
    for page_id, page_claims in claims.items():
        body = documents[page_id].body
        for claim in page_claims:
            assert 0 <= claim.anchor.char_start < claim.anchor.char_end <= len(body)
            assert claim.asserted.strip() in body[claim.anchor.char_start : claim.anchor.char_end]


def test_a_value_split_across_markup_is_never_spliceable() -> None:
    """`<code>payments</code>.` reads as `payments.` and is eleven bytes wide.

    Found by the invariant test above rather than by design: a pattern had
    swallowed a sentence-ending full stop, and the anchor it produced would have
    rewritten a closing tag along with the value. Tightening the pattern fixed
    that instance; this refuses the whole class.
    """
    from reconciler.extract.storage import parse

    body = (
        "<h2>T</h2>\n<p>The deployment is <code>api</code> in namespace <code>ops</code>. Done.</p>"
    )
    document = parse(body, page_id="x")
    block = document.blocks[-1]
    at = block.text.index("ops")
    assert not block.crosses_markup(at, at + 3)
    assert block.crosses_markup(at, at + 4)  # "ops." reaches past </code>

    split = _claim_over(document, block, at, at + 4)
    assert not split.anchor.editable
    assert "split across markup" in split.anchor.refusal


def _claim_over(document, block, start: int, end: int):
    from reconciler.extract.patterns import _claim

    body_start, body_end = block.body_range(start, end)
    return _claim(
        document=document,
        block=block,
        kind="resource",
        subject="workload:api:namespace",
        asserted=block.text[start:end],
        char_start=body_start,
        char_end=body_end,
        rule="test",
        spans_markup=block.crosses_markup(start, end),
    )


def test_claims_on_a_macro_passage_inherit_its_refusal(
    claims: dict[str, list[Claim]],
) -> None:
    threshold = next(
        c for c in claims["1004"] if c.subject == "alert:LabelPrinterQueueDepth:threshold"
    )
    assert not threshold.anchor.editable
    assert "status" in (threshold.anchor.refusal or "")
