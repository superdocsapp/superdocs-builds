import json
import os

import pytest

from winloss_superdocs.cli import main


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    """Every test in this file runs with NO SUPERDOCS_API_KEY set, proving --dry-run
    truly needs no credentials."""
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_debrief_create_dry_run_needs_no_api_key(tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hello")
    rc = main([
        "debrief", "create",
        "--transcript", str(transcript),
        "--deal-code", "DEAL-1",
        "--quarter", "2025Q4",
        "--segment", "Mid-Market",
        "--outcome", "win",
        "--customer-name", "Acme",
        "--dry-run",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["session_id"] == "debrief-DEAL-1"
    assert "instruction" in out


def test_debrief_create_missing_transcript_errors_cleanly(capsys):
    rc = main([
        "debrief", "create",
        "--transcript", "/nonexistent/path.txt",
        "--deal-code", "DEAL-1",
        "--quarter", "2025Q4",
        "--segment", "Mid-Market",
        "--outcome", "win",
        "--customer-name", "Acme",
        "--dry-run",
    ])
    assert rc == 2


def test_debrief_create_without_dry_run_and_without_key_fails_clearly(tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hello")
    rc = main([
        "debrief", "create",
        "--transcript", str(transcript),
        "--deal-code", "DEAL-1",
        "--quarter", "2025Q4",
        "--segment", "Mid-Market",
        "--outcome", "win",
        "--customer-name", "Acme",
    ])
    assert rc == 2
    assert "SUPERDOCS_API_KEY" in capsys.readouterr().err


def test_brief_quarterly_dry_run_needs_no_api_key(capsys):
    rc = main(["brief", "quarterly", "--quarter", "2025Q4", "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quarter"] == "2025Q4"
    assert out["debrief_count"] == 0  # empty index in isolated tmp cwd


def test_search_with_empty_index(capsys):
    rc = main(["search", "--competitor", "Comp Corp"])
    assert rc == 0
    assert "no matches" in capsys.readouterr().out


def test_redact_check_clean_file(tmp_path, capsys):
    f = tmp_path / "clean.html"
    f.write_text("<p>No customer names here.</p>")
    rc = main(["redact-check", str(f)])
    assert rc == 0
    assert "clean" in capsys.readouterr().out


def test_debrief_create_attachment_processing_failed_prints_cleanly_not_a_traceback(
    tmp_path, capsys, monkeypatch
):
    """cli.py must catch AttachmentProcessingFailed and print a clean, actionable
    error -- not let it propagate as a raw Python traceback. This is a real,
    expected outcome (the hard stop from progress.md Entry 6 working as designed),
    not a crash, and should read like one."""
    import winloss_superdocs.cli as cli_module
    from winloss_superdocs.debrief import AttachmentProcessingFailed

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_fake_for_this_test_only")

    def fake_create_debrief(*args, **kwargs):
        raise AttachmentProcessingFailed(
            deal_code="DEAL-1", session_id="debrief-DEAL-1", job_id="job-xyz",
            status="failed", job={"status": "failed", "error": "extraction_error"},
        )

    monkeypatch.setattr(cli_module, "create_debrief", fake_create_debrief)

    transcript = tmp_path / "t.txt"
    transcript.write_text("hello")
    rc = main([
        "debrief", "create",
        "--transcript", str(transcript),
        "--deal-code", "DEAL-1",
        "--quarter", "2025Q4",
        "--segment", "Mid-Market",
        "--outcome", "win",
        "--customer-name", "Acme",
        "--auto-approve",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "DEAL-1" in err
    assert "No chat call was made" in err
    assert "Traceback" not in err  # the whole point of this test
