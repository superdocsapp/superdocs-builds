"""Half two, and the ways a readiness report lies.

A report like this fails in one direction that matters. It does not usually
crash or produce nonsense — it produces a plausible page that says everything is
fine. Three tests here exist because of that specific failure:

- `test_a_service_with_drift_is_never_reported_as_verified` is a regression
  test. The first version joined findings to services by subject alone, and the
  drift on `payments-api`'s runbook is filed under
  `alert:PaymentsApiHighLatency:threshold` — a subject containing the service's
  name nowhere. So the table reported `payments-api` as verified while its
  runbook carried a live contradiction.
- `test_unverifiable_is_visible_in_both_documents` keeps the count that makes
  the rest honest.
- `test_neither_document_claims_a_certification` holds the non-goal rail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.check.vertical import check_page
from reconciler.claims import Anchor, Claim
from reconciler.config import Config
from reconciler.confluence.local import LocalSource
from reconciler.estate import Estate
from reconciler.extract.patterns import extract_claims
from reconciler.pack import (
    FORBIDDEN_CLAIMS,
    build_dr_evidence,
    build_readiness,
    divergences,
    export_pack,
    service_rows,
)
from reconciler.register import Register
from reconciler.superdocs import SuperDocs
from tests.stub_superdocs import Stub


@pytest.fixture
def swept(tmp_path: Path, runbooks_dir: Path) -> Register:
    """A register holding a full sweep of the corpus, the way `rr check` leaves it."""
    estate = Estate.load(Config.load())
    with Register(tmp_path / "register.db") as register:
        source = LocalSource(runbooks_dir)
        for page in source.pages():
            document = source.read(page.page_id)
            claims = extract_claims(document)
            register.upsert_claims(claims)
            register.upsert_findings(check_page(page.page_id, claims, estate))
        yield register


@pytest.fixture
def estate() -> Estate:
    return Estate.load(Config.load())


# ------------------------------------------------------------ the join --


def test_every_catalogued_service_gets_a_row(swept: Register, estate: Estate) -> None:
    rows = service_rows(swept, estate)

    assert {row.service for row in rows} == {c.name for c in estate.components}


def test_a_service_with_drift_is_never_reported_as_verified(
    swept: Register, estate: Estate
) -> None:
    """The regression that matters. See the module docstring.

    `payments-api`'s runbook carries a threshold contradiction, and the row for
    it must say so — whatever the finding's subject happens to be called.
    """
    rows = {row.service: row for row in service_rows(swept, estate)}
    payments = rows["payments-api"]

    assert payments.contradicted > 0, "the drift on pages 1001/1002 was not attributed"
    assert payments.status == "drift"
    assert "1001" in payments.runbook_pages


def test_a_service_with_no_runbook_says_no_runbook_not_verified(estate: Estate) -> None:
    """An empty register must not read as a clean bill of health."""
    from reconciler.pack import ServiceRow

    row = ServiceRow(service="unwatched")

    assert row.status == "no runbook"


def test_a_service_whose_claims_were_all_unverifiable_is_unknown() -> None:
    from reconciler.pack import ServiceRow

    row = ServiceRow(service="s", runbook_pages=("1",), unverifiable=3)

    assert row.status == "unknown", "nothing checked must not read as verified"


# ------------------------------------------------- multi-document consistency --


def test_the_corpus_documents_the_same_facts_consistently(swept: Register) -> None:
    """The good case, which the report has to be able to show.

    Ten subjects in this corpus appear on two pages each and agree everywhere.
    A consistency check that can only report disagreement cannot demonstrate
    that, and the whole multi-document claim rests on being able to.
    """
    shared = swept.multi_page_subjects()

    assert len(shared) >= 5
    assert all(spellings == 1 for spellings in shared.values())
    assert divergences(swept) == []


def test_two_pages_disagreeing_is_reported(tmp_path: Path) -> None:
    """The failure the vertical checker structurally cannot see.

    Neither page is checked against the estate here — the point is that they
    contradict each other, which is worth surfacing on its own.
    """

    def claim(page_id: str, asserted: str) -> Claim:
        return Claim(
            page_id=page_id,
            kind="threshold",
            subject="alert:CheckoutLatency:threshold",
            asserted=asserted,
            excerpt=f"Page when latency passes {asserted}.",
            anchor=Anchor(
                heading_path=("Thresholds",),
                node_index=0,
                content_hash=f"hash-{page_id}",
                char_start=0,
                char_end=len(asserted),
            ),
        )

    with Register(tmp_path / "register.db") as register:
        register.upsert_claims([claim("2001", "800ms"), claim("2002", "1.2s")])

        found = divergences(register)

    assert len(found) == 1
    assert found[0].subject == "alert:CheckoutLatency:threshold"
    assert set(found[0].pages) == {"2001", "2002"}
    assert {value for _, value in found[0].spellings} == {"800ms", "1.2s"}


# ------------------------------------------------------------- the documents --


def test_the_readiness_report_names_every_service_and_its_evidence(
    swept: Register, estate: Estate
) -> None:
    pack = build_readiness(swept, estate)

    for component in estate.components:
        assert component.name in pack.html
    assert "claim register" in pack.html
    assert pack.generated_at


def test_unverifiable_is_visible_in_both_documents(swept: Register, estate: Estate) -> None:
    """Rule 4's shape in half two: what nobody checked is in the document."""
    readiness = build_readiness(swept, estate)
    evidence = build_dr_evidence(swept, estate)

    assert "could not be checked" in readiness.html
    assert "unverifiable" in evidence.html
    assert "does not cover" in evidence.html


def test_the_dr_document_lists_its_own_gaps_in_full(swept: Register, estate: Estate) -> None:
    evidence = build_dr_evidence(swept, estate)

    # The corpus plants RPO and RTO claims that nothing in the estate settles.
    assert "measure:rpo" in evidence.html
    assert "measure:rto" in evidence.html


def test_neither_document_claims_a_certification(swept: Register, estate: Estate) -> None:
    """The non-goal, as a test rather than as good intentions.

    SOC 2 and ISO are the buyer's motivation for wanting this. They are never
    something this tool asserts, and the failure mode is a well-meant sentence
    in a template that an auditor later reads as a claim.
    """
    for pack in (build_readiness(swept, estate), build_dr_evidence(swept, estate)):
        lowered = pack.html.lower()
        for phrase in FORBIDDEN_CLAIMS:
            assert phrase.lower() not in lowered, f"{pack.title} claims {phrase!r}"


def test_both_documents_carry_their_own_limitations(swept: Register, estate: Estate) -> None:
    """Printed, forwarded, read a year later by somebody who never saw the README."""
    for pack in (build_readiness(swept, estate), build_dr_evidence(swept, estate)):
        assert "not the live state of any cloud account" in pack.html
        assert "never as correct" in pack.html


def test_a_document_is_written_where_it_was_asked_for(
    swept: Register, estate: Estate, tmp_path: Path
) -> None:
    pack = build_readiness(swept, estate)

    path = pack.write(tmp_path / "out", "on-call-readiness")

    assert path.read_text(encoding="utf-8") == pack.html
    assert path.name == "on-call-readiness.html"


def test_page_content_is_escaped_into_the_report(tmp_path: Path, estate: Estate) -> None:
    """A runbook containing markup must not become markup in the report."""
    with Register(tmp_path / "register.db") as register:
        register.upsert_claims(
            [
                Claim(
                    page_id="3001",
                    kind="threshold",
                    subject="alert:X:threshold",
                    asserted="<script>alert(1)</script>",
                    excerpt="hostile",
                    anchor=Anchor(("H",), 0, "h", 0, 5),
                ),
                Claim(
                    page_id="3002",
                    kind="threshold",
                    subject="alert:X:threshold",
                    asserted="500ms",
                    excerpt="benign",
                    anchor=Anchor(("H",), 0, "h2", 0, 5),
                ),
            ]
        )
        pack = build_readiness(register, estate)

    assert "<script>" not in pack.html
    assert "&lt;script&gt;" in pack.html


# ---------------------------------------------------------------- exporting --


def test_export_goes_through_superdocs_and_spends_nothing(swept: Register, estate: Estate) -> None:
    """`export` and `upload` are free, which is the whole reason the pack uses them."""
    stub = Stub(poll_delay=0.0)
    try:
        with SuperDocs(api_key="test-key", base_url=stub.base_url) as client:
            pack = build_readiness(swept, estate)
            blob = export_pack(client, pack, fmt="pdf")

        assert blob.startswith(b"%PDF"), "the export did not return a file"
        assert stub.exports == [{"session_id": "sess_1", "format": "pdf"}]
        assert stub.chat_calls == [], (
            "the pack opened a chat turn — that is the call that costs, and the "
            "whole claim about half two is that it does not"
        )
    finally:
        stub.stop()


def test_the_offline_document_needs_no_key(swept: Register, estate: Estate) -> None:
    """A readiness report that needs credentials to be read is one nobody reads."""
    pack = build_readiness(swept, estate)

    assert pack.html.startswith("<!DOCTYPE html>")
    assert "<table>" in pack.html


def test_a_finding_on_a_page_belongs_to_that_pages_service(swept: Register, estate: Estate) -> None:
    """The join that fixed the regression, asserted directly."""
    rows = {row.service: row for row in service_rows(swept, estate)}

    for row in rows.values():
        if not row.runbook_pages:
            continue
        page_findings = [f for p in row.runbook_pages for f in swept.findings(page_id=p)]
        assert row.verified + row.contradicted + row.unverifiable >= len(page_findings)
