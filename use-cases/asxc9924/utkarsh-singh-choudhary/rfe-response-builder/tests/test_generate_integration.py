"""
Mocked end-to-end test for build_response_packet -- proves the full
notice -> match -> per-item chat turns -> checklist -> export flow works,
including the "cannot afford to silently pass a failed draft" behavior,
without any network access or SuperDocs operations spent.
"""
import json
from pathlib import Path

import pytest
import requests_mock

from rfe_response_builder.generate import build_response_packet, load_new_evidence_catalog, load_petition
from rfe_response_builder.superdocs_client import SuperDocsClient

DATA_DIR = Path(__file__).parent.parent / "data"
NOTICE_TEXT = (DATA_DIR / "sample_rfe_notice.txt").read_text()
_SUBSTANTIVE_REPLY = "Drafted response section addressing the officer concern with specific facts and citations."


@pytest.fixture
def client():
    # retry_backoff_s=0 keeps retry tests fast (no real sleeping).
    return SuperDocsClient(api_key="sk_test_fake_key_not_real", retry_backoff_s=0)


@pytest.fixture
def evidence_catalog():
    return load_new_evidence_catalog(DATA_DIR / "sample_new_evidence.json")


def _mock_chat_and_export(m, chat_json=None):
    m.post(
        "https://api.superdocs.app/v1/chat",
        json=chat_json or {"response": _SUBSTANTIVE_REPLY, "document_changes": {"updated_html": "<p>x</p>"}},
    )
    m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")


def test_build_response_packet_answers_all_three_items(client, evidence_catalog, tmp_path):
    petition = load_petition(DATA_DIR / "sample_petition_arguments.json")

    with requests_mock.Mocker() as m:
        _mock_chat_and_export(m)

        out_path, coverage = build_response_packet(
            client, "rfe-test-session", "CASE-2002", "Marco Alvarez",
            NOTICE_TEXT, petition, tmp_path, evidence_catalog=evidence_catalog,
        )

        assert out_path.exists()
        assert out_path.read_bytes() == b"FAKE_DOCX"
        assert len(coverage) == 3
        assert all(row.answered for row in coverage)

        # requests match to the prior petition arguments by keyword overlap
        matched_topics = {row.request_id: row.matched_prior_argument for row in coverage}
        assert matched_topics["1"] == "Petition Cover Letter, p. 3"
        assert matched_topics["2"] == "Exhibit C, Marriage Certificate"
        assert matched_topics["3"] == "Exhibit E, Employment Verification Letter"

        # every item picked up at least one exhibit from the evidence catalog
        assert all(row.exhibit_numbers for row in coverage)

        # exhibit manifest was written alongside the docx
        manifest_path = tmp_path / "CASE-2002-exhibit-manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) >= 3  # at least one exhibit per item

        # 1 intro turn + 3 per-item turns + 1 checklist turn + 1 exhibit-list turn = 6 chat calls
        chat_calls = [r for r in m.request_history if r.path == "/v1/chat"]
        assert len(chat_calls) == 6


def test_build_response_packet_raises_on_unparseable_notice(client, tmp_path):
    petition = load_petition(DATA_DIR / "sample_petition_arguments.json")
    with pytest.raises(ValueError, match="No RFE requests could be parsed"):
        build_response_packet(client, "s", "CASE-X", "Client", "   ", petition, tmp_path)


def test_build_response_packet_continues_after_one_item_persistently_fails(client, tmp_path):
    """A drafting turn that fails on every attempt (retries exhausted)
    must not abort the whole run -- the other items still get answered,
    and the failure surfaces in the coverage checklist as NOT ANSWERED
    rather than being silently hidden."""
    petition = load_petition(DATA_DIR / "sample_petition_arguments.json")

    def chat_callback(request, context):
        body = json.loads(request.text)
        # Persistently fail only the turn drafting item 2 (identified by
        # its request text appearing in the drafting instruction), so the
        # failure isn't tied to a brittle call-count that retries would shift.
        if "certified English translation" in body.get("message", ""):
            context.status_code = 500
            return {"detail": "simulated persistent failure"}
        return {"response": _SUBSTANTIVE_REPLY, "document_changes": {"updated_html": "<p>x</p>"}}

    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", json=chat_callback)
        m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")

        out_path, coverage = build_response_packet(
            client, "rfe-test-session-2", "CASE-2002", "Marco Alvarez",
            NOTICE_TEXT, petition, tmp_path,
        )

        unanswered = [row for row in coverage if not row.answered]
        assert len(unanswered) == 1
        assert unanswered[0].request_id == "2"
        # the export still happens -- a partial packet is still produced,
        # with the gap honestly reported, not silently dropped
        assert out_path.exists()


def test_build_response_packet_retries_transient_failure_and_recovers(client, tmp_path):
    """A failure that clears on retry (transient 500) should NOT show up
    as NOT ANSWERED -- the retry logic in SuperDocsClient.chat should
    absorb it before it ever reaches build_response_packet."""
    petition = load_petition(DATA_DIR / "sample_petition_arguments.json")

    attempts_for_item_2 = {"n": 0}

    def chat_callback(request, context):
        body = json.loads(request.text)
        if "certified English translation" in body.get("message", ""):
            attempts_for_item_2["n"] += 1
            if attempts_for_item_2["n"] == 1:
                context.status_code = 500
                return {"detail": "simulated one-off transient failure"}
        return {"response": _SUBSTANTIVE_REPLY, "document_changes": {"updated_html": "<p>x</p>"}}

    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", json=chat_callback)
        m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")

        out_path, coverage = build_response_packet(
            client, "rfe-test-session-3", "CASE-2002", "Marco Alvarez",
            NOTICE_TEXT, petition, tmp_path,
        )

        assert all(row.answered for row in coverage)
        assert attempts_for_item_2["n"] == 2  # 1 failure + 1 successful retry
        assert out_path.exists()


def test_non_substantive_reply_marked_not_answered_despite_200(client, tmp_path):
    """A 200 response whose text is a hedge/refusal must NOT count as
    answered -- this is the fix for the reviewer-flagged gap where a
    successful HTTP call was being treated as a substantive answer."""
    petition = load_petition(DATA_DIR / "sample_petition_arguments.json")

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": "I don't have enough information to address this request.",
                  "document_changes": {}},
        )
        m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")

        out_path, coverage = build_response_packet(
            client, "rfe-test-session-4", "CASE-2002", "Marco Alvarez",
            NOTICE_TEXT, petition, tmp_path,
        )

    assert not any(row.answered for row in coverage)
    assert all(row.response_section == "(not answered)" for row in coverage)
    assert out_path.exists()


def test_cli_review_flag_prompts_and_only_exports_approved_items(tmp_path, monkeypatch, capsys):
    """End-to-end CLI test of --review: mocks the terminal input (approve
    item 1, reject item 2 with feedback, reject item 3 by leaving it
    unanswered/default) and a mocked SuperDocs API, then checks the real
    main() entry point produces the right coverage outcome."""

    from rfe_response_builder.generate import main

    notice_path = tmp_path / "notice.txt"
    notice_path.write_text(NOTICE_TEXT)
    petition_path = DATA_DIR / "sample_petition_arguments.json"
    out_dir = tmp_path / "out"

    answers = iter(["y", "n", "reason for rejecting", "n", ""])

    def fake_input(prompt=""):
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_fake")

    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", json={"response": "ok", "document_changes": {}})
        m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": "job-1"})
        m.get(
            "https://api.superdocs.app/v1/jobs/job-1",
            json={
                "status": "awaiting_approval",
                "pending_changes": [{"chunk_id": "chunk-1",
                                      "proposed_text": "Drafted section addressing the concern with citations."}],
            },
        )
        import re as _re
        m.post(_re.compile(r"https://api\.superdocs\.app/v1/chat/.+/approve"), json={"status": "ok"})
        m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")

        exit_code = main([
            "--notice", str(notice_path),
            "--petition", str(petition_path),
            "--case-id", "CASE-2002",
            "--client-name", "Marco Alvarez",
            "--out", str(out_dir),
            "--review",
        ])

    # 1 of 3 approved -> 2 unanswered -> non-zero exit, by the same
    # convention as the non-interactive path.
    assert exit_code == 1
    assert list(out_dir.glob("*.docx"))
