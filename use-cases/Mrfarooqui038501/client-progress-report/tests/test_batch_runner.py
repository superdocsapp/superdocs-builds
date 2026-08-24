from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from src.batch_runner import process_client, run_batch
from src.fixtures import make_synthetic_roster
from src.state_store import StateStore
from tests.fake_superdocs_client import FakeSuperDocsClient


def test_baseline_only_client_creates_plan_without_comparison(tmp_path):
    roster = make_synthetic_roster(
        n_clients=1,
        seed=1,
    )

    client = roster[0]

    # Force a true baseline-only client.
    client.assessments = client.assessments[:1]

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    result = process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    assert result.status == "baseline_created"

    assert len(sd.chat_calls) == 1
    assert len(sd.upload_calls) == 0
    assert len(sd.persist_calls) == 0
    assert len(sd.export_calls) == 0

    # Baseline chat must have created a document.
    session_id = state.session_id_for(
        client.client_id
    )

    assert session_id in sd.documents


def test_fresh_client_with_multiple_assessments_creates_baseline_then_report(
    tmp_path,
):
    """
    Critical regression test.

    A fresh synthetic roster already contains:
        baseline + follow-up 1 + follow-up 2

    There is no SuperDocs document yet.

    One process_client() call must therefore:
        1. create the baseline document
        2. create the progress report
        3. export the final document

    This is the bug the earlier implementation missed.
    """

    roster = make_synthetic_roster(
        n_clients=1,
        seed=1,
    )

    client = roster[0]

    # Do NOT reduce assessments to one.
    # This intentionally simulates the normal fresh roster.
    assert len(client.assessments) >= 3

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    result = process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    assert result.status == "report_appended"

    # First chat = baseline document.
    # Second chat = reassessment narrative.
    assert len(sd.chat_calls) == 2

    # One chart upload.
    assert len(sd.upload_calls) == 1

    # One deterministic document persistence.
    assert len(sd.persist_calls) == 1

    # One final export.
    assert len(sd.export_calls) == 1

    # The document exists.
    session_id = state.session_id_for(
        client.client_id
    )

    assert session_id in sd.documents

    # The report must have been persisted before the AI narrative.
    persist_position = sd.call_order.index(
        "persist"
    )

    narrative_chat_position = max(
        i
        for i, call in enumerate(sd.call_order)
        if call == "chat"
    )

    assert persist_position < narrative_chat_position

    # The final result should have an exported file.
    assert result.export_path is not None
    assert Path(result.export_path).exists()


def test_reassessment_persists_deterministic_content_before_calling_ai(
    tmp_path,
):
    roster = make_synthetic_roster(
        n_clients=1,
        seed=1,
    )

    client = roster[0]
    all_assessments = client.assessments

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    # First run: create baseline.
    client.assessments = all_assessments[:1]

    process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    # Second run: reassessment.
    client.assessments = all_assessments[:2]

    result = process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    assert result.status == "report_appended"

    assert len(sd.upload_calls) == 1
    assert len(sd.persist_calls) == 1
    assert len(sd.chat_calls) == 2
    assert len(sd.export_calls) == 1

    # The first chat is the baseline.
    # The second chat is the narrative.
    assert sd.call_order.count("chat") == 2

    persist_position = sd.call_order.index(
        "persist"
    )

    second_chat_position = [
        i
        for i, call in enumerate(sd.call_order)
        if call == "chat"
    ][1]

    assert persist_position < second_chat_position


def test_same_client_second_and_third_reports_extend_one_session(
    tmp_path,
):
    """
    The same client's second and third reports must extend the same
    SuperDocs session/document.
    """

    roster = make_synthetic_roster(
        n_clients=1,
        seed=1,
    )

    client = roster[0]
    all_assessments = client.assessments

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    # Baseline.
    client.assessments = all_assessments[:1]

    process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    # Second assessment.
    client.assessments = all_assessments[:2]

    process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    session_id = state.session_id_for(
        client.client_id
    )

    doc_after_run_2 = sd.documents[
        session_id
    ]

    # Third assessment arrives.
    third = client.assessments[-1]

    client.assessments.append(
        replace(
            third,
            assessment_date=(
                third.assessment_date
                + timedelta(days=56)
            ),
        )
    )

    process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    doc_after_run_3 = sd.documents[
        session_id
    ]

    # One baseline chat + two narrative chats.
    assert len(sd.chat_calls) == 3

    # Every chat uses the same session.
    assert all(
        call["session_id"] == session_id
        for call in sd.chat_calls
    )

    # The third report must extend the same document.
    assert (
        doc_after_run_2 in doc_after_run_3
        or len(doc_after_run_3) > len(doc_after_run_2)
    )


def test_idempotent_rerun_skips_already_committed_assessment(
    tmp_path,
):
    roster = make_synthetic_roster(
        n_clients=1,
        seed=1,
    )

    client = roster[0]
    all_assessments = client.assessments

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    # Baseline.
    client.assessments = all_assessments[:1]

    process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    # Reassessment.
    client.assessments = all_assessments[:2]

    first = process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    assert first.status == "report_appended"

    chat_count_before_rerun = len(
        sd.chat_calls
    )

    upload_count_before_rerun = len(
        sd.upload_calls
    )

    persist_count_before_rerun = len(
        sd.persist_calls
    )

    export_count_before_rerun = len(
        sd.export_calls
    )

    # Same assessment again.
    second = process_client(
        client,
        sd,
        state,
        tmp_path / "out",
    )

    assert second.status == "skipped_already_run"

    # No additional operations.
    assert len(sd.chat_calls) == chat_count_before_rerun
    assert len(sd.upload_calls) == upload_count_before_rerun
    assert len(sd.persist_calls) == persist_count_before_rerun
    assert len(sd.export_calls) == export_count_before_rerun


def _run_baseline_then_full(
    roster,
    sd,
    state,
    output_dir,
    limit=None,
):
    """
    Test helper for the historical two-pass workflow.

    Kept because it is still useful for proving that a baseline can be
    created first and a later reassessment can extend it.
    """

    full_assessments = {
        client.client_id: client.assessments
        for client in roster
    }

    for client in roster:
        client.assessments = (
            client.assessments[:1]
        )

    run_batch(
        roster,
        sd,
        state,
        output_dir,
        limit=limit,
    )

    for client in roster:
        client.assessments = full_assessments[
            client.client_id
        ]

    return run_batch(
        roster,
        sd,
        state,
        output_dir,
        limit=limit,
    )


def test_run_batch_produces_individual_output_per_client(
    tmp_path,
):
    roster = make_synthetic_roster(
        n_clients=6,
        seed=7,
    )

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    results = _run_baseline_then_full(
        roster,
        sd,
        state,
        tmp_path / "out",
    )

    assert len(results) == 6

    statuses = {
        result.status
        for result in results
    }

    assert statuses <= {
        "baseline_created",
        "report_appended",
        "error",
    }

    # Documents should not all be identical.
    document_lengths = [
        len(html)
        for html in sd.documents.values()
    ]

    assert len(
        set(document_lengths)
    ) > 1


def test_run_batch_respects_limit_for_small_sample_mode(
    tmp_path,
):
    roster = make_synthetic_roster(
        n_clients=8,
        seed=7,
    )

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    results = _run_baseline_then_full(
        roster,
        sd,
        state,
        tmp_path / "out",
        limit=3,
    )

    assert len(results) == 3


def test_run_batch_continues_after_one_client_errors(
    tmp_path,
    monkeypatch,
):
    roster = make_synthetic_roster(
        n_clients=3,
        seed=7,
    )

    sd = FakeSuperDocsClient()
    state = StateStore(
        tmp_path / "state.json"
    )

    # First create baseline documents.
    full_assessments = {
        client.client_id: client.assessments
        for client in roster
    }

    for client in roster:
        client.assessments = (
            client.assessments[:1]
        )

    run_batch(
        roster,
        sd,
        state,
        tmp_path / "out",
    )

    for client in roster:
        client.assessments = full_assessments[
            client.client_id
        ]

    original_upload = sd.upload_image

    call_count = {
        "n": 0
    }

    def flaky_upload(
        png_bytes,
        filename="chart.png",
    ):
        call_count["n"] += 1

        if call_count["n"] == 1:
            raise RuntimeError(
                "simulated transient failure"
            )

        return original_upload(
            png_bytes,
            filename,
        )

    sd.upload_image = flaky_upload

    results = run_batch(
        roster,
        sd,
        state,
        tmp_path / "out",
    )

    assert len(results) == 3

    assert any(
        result.status == "error"
        for result in results
    )

    assert sum(
        1
        for result in results
        if result.status != "error"
    ) == 2


def test_run_batch_40_clients_produces_distinct_reports(tmp_path):
    """
    Verifies that a full 40-client roster runs cleanly end-to-end,
    produces 40 distinct exported reports, and maintains individual client trajectories.
    """
    roster = make_synthetic_roster(n_clients=40, seed=42)
    assert len(roster) == 40

    sd = FakeSuperDocsClient()
    state = StateStore(tmp_path / "state.json")

    results = run_batch(
        roster,
        sd,
        state,
        tmp_path / "out",
    )

    assert len(results) == 40
    assert all(r.status == "report_appended" for r in results)

    # All 40 documents were saved in the mock server
    assert len(sd.documents) == 40

    # Ensure document lengths and contents vary significantly across clients
    doc_lengths = [len(html) for html in sd.documents.values()]
    assert len(set(doc_lengths)) > 10

    # All exported files exist on disk
    for r in results:
        assert r.export_path is not None
        assert Path(r.export_path).exists()