"""Tests for the review interface.

Driven over real HTTP with a client rather than a browser, which is the point of building the UI
as a thin layer over the machine path: the gate can be verified without automating a browser, and
the browser cannot do anything the API does not already allow.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from docs_lint.model import (
    Anchor,
    FileResult,
    Finding,
    RunSummary,
    Severity,
    Source,
    Verdict,
)
from docs_lint.review.server import ReviewOutcome, build_app, findings_payload

TOKEN = "test-token-value"


def finding(rule="banned-terms", fixable=True, source=Source.LOCAL, change_id=None) -> Finding:
    return Finding(
        rule_id=rule,
        severity=Severity.ERROR,
        message="Avoid 'utilise'",
        anchor=Anchor(path="a.md", start_line=3, end_line=3, start_char=3, end_char=10),
        source=source,
        original="utilise",
        replacement="use" if fixable else None,
        change_id=change_id,
    )


def summary_with(*findings) -> RunSummary:
    return RunSummary(
        run_id="r1",
        results=(
            FileResult(
                path="a.md",
                verdict=Verdict.findings(checks_run=("local",)),
                findings=tuple(findings),
            ),
        ),
    )


@pytest.fixture
def review():
    outcome = ReviewOutcome()
    summary = summary_with(finding(), finding(rule="heading-case"))
    return TestClient(build_app(summary, outcome, TOKEN)), outcome, summary


# -- the token is the only thing protecting the page --------------------------------


def test_the_page_requires_the_token(review):
    client, _, _ = review
    assert client.get("/").status_code == 403
    assert client.get("/?token=wrong").status_code == 403
    assert client.get(f"/?token={TOKEN}").status_code == 200


def test_the_api_requires_the_token(review):
    client, _, _ = review
    assert client.get("/api/run").status_code == 403
    assert client.get(f"/api/run?token={TOKEN}").status_code == 200


def test_submitting_decisions_requires_the_token(review):
    client, outcome, _ = review
    response = client.post("/api/decisions", json={"token": "wrong", "decisions": []})
    assert response.status_code == 403
    assert outcome.decisions is None, "a bad token must not record anything"


# -- the review queue ---------------------------------------------------------------


def test_only_fixable_findings_reach_the_review_queue():
    """A finding with no proposed correction has nothing for a reviewer to decide."""
    summary = summary_with(finding(), finding(rule="fence-language", fixable=False))
    payload = findings_payload(summary)
    assert [f["rule"] for f in payload[0]["findings"]] == ["banned-terms"]


def test_each_card_carries_the_before_and_after_a_reviewer_needs(review):
    client, _, _ = review
    data = client.get(f"/api/run?token={TOKEN}").json()
    card = data["files"][0]["findings"][0]

    assert card["before"] == "utilise"
    assert card["after"] == "use"
    assert card["line"] == 3
    assert card["source"] == "rule"


def test_model_findings_are_labelled_so_a_reviewer_knows_what_they_are_judging():
    summary = summary_with(finding(rule="style-guide", source=Source.SUPERDOCS, change_id="ch_1"))
    card = findings_payload(summary)[0]["findings"][0]
    assert card["source"] == "ai"
    assert card["id"] == "ch_1", "a model finding is decided by the id the approval API expects"


def test_a_degraded_run_is_surfaced_to_the_reviewer(review):
    client, outcome, _ = review
    degraded = RunSummary(
        run_id="r1",
        results=(FileResult(path="a.md", verdict=Verdict.clean(checks_run=("local",))),),
        degraded=("SuperDocs unreachable; local rules only",),
    )
    other = TestClient(build_app(degraded, ReviewOutcome(), TOKEN))
    data = other.get(f"/api/run?token={TOKEN}").json()
    assert data["degraded"] == ["SuperDocs unreachable; local rules only"]


# -- submitting is the same gate the file path uses ---------------------------------


def test_submitting_produces_the_same_decisions_structure_as_a_decisions_file(review):
    client, outcome, summary = review
    ids = [f.finding_id for f in summary.all_findings]

    response = client.post(
        "/api/decisions",
        json={
            "token": TOKEN,
            "decisions": [
                {"finding_id": ids[0], "approved": True},
                {"finding_id": ids[1], "approved": False},
            ],
        },
    )

    assert response.json() == {"ok": True, "approved": 1, "rejected": 1}
    assert outcome.decisions is not None
    assert outcome.decisions.run_id == "r1"
    assert outcome.decisions.approved_ids() == frozenset({ids[0]})
    assert outcome.done.is_set()


def test_a_finding_omitted_from_the_submission_is_not_approved(review):
    """The browser cannot approve by silence any more than a decisions file can."""
    client, outcome, summary = review
    ids = [f.finding_id for f in summary.all_findings]

    client.post(
        "/api/decisions",
        json={"token": TOKEN, "decisions": [{"finding_id": ids[0], "approved": True}]},
    )
    assert not outcome.decisions.is_approved(ids[1])


def test_cancelling_records_a_cancellation_not_an_empty_approval(review):
    """An abandoned review must not look like "the reviewer approved nothing on purpose"."""
    client, outcome, _ = review
    client.post("/api/cancel", json={"token": TOKEN})

    assert outcome.cancelled
    assert outcome.decisions is None
    assert outcome.done.is_set()


def test_a_malformed_submission_is_rejected(review):
    client, outcome, _ = review
    assert (
        client.post("/api/decisions", json={"token": TOKEN, "decisions": "yes"}).status_code == 422
    )
    assert outcome.decisions is None


# -- the page itself ----------------------------------------------------------------


def test_the_page_is_self_contained_with_no_external_requests(review):
    """It runs on a developer machine behind whatever network policy they have."""
    client, _, _ = review
    page = client.get(f"/?token={TOKEN}").text

    assert "<script" in page and "</script>" in page
    for scheme in ("http://", "https://"):
        assert f'src="{scheme}' not in page
        assert f'href="{scheme}' not in page


def test_the_page_escapes_document_content_it_renders(review):
    """Findings contain arbitrary document text, including text that looks like markup."""
    client, _, _ = review
    page = client.get(f"/?token={TOKEN}").text
    assert "function esc(" in page, "the page must escape the content it injects"
