from unittest.mock import MagicMock

import pytest

from winloss_superdocs.index import DebriefRecord, Index
from winloss_superdocs.redaction import RedactionBlockedExport
from winloss_superdocs.review import auto_approve_all
from winloss_superdocs.synthesis import create_quarterly_brief

VALID_BRIEF_HTML = """
<h1>Quarterly Competitive Brief -- 2025Q4</h1>
<h2>Overview &amp; Methodology</h2>
<p>2 debriefs. Customer identities removed.</p>
<h2>Patterns by Competitor</h2>
<table><tr><th>Competitor</th><th>Wins</th><th>Losses</th></tr>
<tr><td>Comp Corp</td><td>1</td><td>1</td></tr></table>
<h2>Patterns by Segment</h2>
<table><tr><th>Segment</th><th>Wins</th><th>Losses</th></tr>
<tr><td>Mid-Market</td><td>1</td><td>1</td></tr></table>
<h2>Wording That Worked</h2>
<p>Real-time throughput (DEAL-1).</p>
<h2>Losses Attributable to a Capability Gap</h2>
<p>DEAL-2 lost on missing SSO.</p>
"""

LEAKY_BRIEF_HTML = VALID_BRIEF_HTML.replace(
    "DEAL-2 lost on missing SSO.", "Acme Robotics Inc. lost on missing SSO."
)


def two_debrief_index(tmp_path) -> Index:
    idx = Index(tmp_path / "index.json")
    idx.upsert(
        DebriefRecord(
            deal_code="DEAL-1", quarter="2025Q4", segment="Mid-Market", outcome="win",
            competitors=["Comp Corp"], customer_name="Acme Robotics Inc.",
            evidence_snippets=["real-time throughput sealed it"],
            superdocs_document_id="doc_1",
        )
    )
    idx.upsert(
        DebriefRecord(
            deal_code="DEAL-2", quarter="2025Q4", segment="Mid-Market", outcome="loss",
            competitors=["Comp Corp"], customer_name="Beta Systems LLC",
            evidence_snippets=["we needed SSO and they didn't have it"],
            superdocs_document_id="doc_2",
        )
    )
    return idx


def make_fake_client(final_html):
    client = MagicMock()
    client.usage = MagicMock(ops_used=1)
    client.usage.check_budget = MagicMock()
    client.sessions_init.return_value = {"session_id": "brief-2025Q4"}
    client.chat_async.return_value = {"job_id": "job-1"}
    client.wait_for_job.return_value = {
        "status": "completed",
        "result": {"document_changes": {"updated_html": final_html}},
    }
    client.export.return_value = b"FAKE_EXPORT_BYTES"
    return client


def test_create_quarterly_brief_happy_path(tmp_path):
    client = make_fake_client(VALID_BRIEF_HTML)
    index = two_debrief_index(tmp_path)

    result = create_quarterly_brief(
        client, index, quarter="2025Q4", output_dir=tmp_path / "out",
        small_sample_threshold=3, approval_callback=auto_approve_all,
    )

    assert result.debrief_count == 2
    assert result.exported_docx_path.exists()
    assert result.exported_pdf_path.exists()
    assert client.export.call_count == 2  # docx + pdf
    # sessions.init opened both debrief Files.
    _, kwargs = client.sessions_init.call_args
    assert set(kwargs["document_ids"]) == {"doc_1", "doc_2"}


def test_create_quarterly_brief_redaction_gate_blocks_export(tmp_path):
    client = make_fake_client(LEAKY_BRIEF_HTML)
    index = two_debrief_index(tmp_path)

    with pytest.raises(RedactionBlockedExport):
        create_quarterly_brief(
            client, index, quarter="2025Q4", output_dir=tmp_path / "out",
            small_sample_threshold=3, approval_callback=auto_approve_all,
        )
    client.export.assert_not_called()  # nothing written on a leak


def test_create_quarterly_brief_no_debriefs_produces_honest_no_findings(tmp_path):
    client = make_fake_client(VALID_BRIEF_HTML)  # not used on this path
    index = Index(tmp_path / "index.json")  # empty

    result = create_quarterly_brief(
        client, index, quarter="2099Q1", output_dir=tmp_path / "out",
        small_sample_threshold=3, approval_callback=auto_approve_all,
    )

    assert result.debrief_count == 0
    assert result.exported_pdf_path is None
    client.chat_async.assert_not_called()  # no chat call spent for an empty quarter
    client.sessions_init.assert_not_called()
    exported_html_call = client.export.call_args
    assert "No win/loss debriefs were recorded" in exported_html_call.kwargs["html"]


def test_customer_names_never_appear_in_synthesis_prompt(tmp_path):
    client = make_fake_client(VALID_BRIEF_HTML)
    index = two_debrief_index(tmp_path)

    create_quarterly_brief(
        client, index, quarter="2025Q4", output_dir=tmp_path / "out",
        small_sample_threshold=3, approval_callback=auto_approve_all,
    )

    sent_message = client.chat_async.call_args[0][1]
    assert "Acme Robotics Inc." not in sent_message
    assert "Beta Systems LLC" not in sent_message
    assert "[CUSTOMER]" in sent_message  # redacted placeholder is present instead


def test_synthesis_uses_cross_session_flags(tmp_path):
    client = make_fake_client(VALID_BRIEF_HTML)
    index = two_debrief_index(tmp_path)

    create_quarterly_brief(
        client, index, quarter="2025Q4", output_dir=tmp_path / "out",
        small_sample_threshold=3, approval_callback=auto_approve_all,
    )

    _, kwargs = client.chat_async.call_args
    assert kwargs.get("cross_session_search") is True
    assert kwargs.get("cross_session_memory") is True
