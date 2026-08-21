"""The command line's own contract.

Small on purpose. What is worth pinning here is that the entry point exists,
that every registered command is reachable, and that running `rr` with nothing
is a help page and a non-zero exit rather than a traceback — the first thing a
stranger does is run it with no arguments, and that first impression is part of
the product.

The one test here that is about *money* rather than about ergonomics is
`test_propose_without_yes_spends_nothing`. `rr propose` is the only command in
this project that can be charged for, and the property that it does nothing
until it is asked twice is worth an assertion rather than a docstring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.cli import COMMANDS, build_parser, main


@pytest.fixture
def scratch_register(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A register per test. The project's own `register.db` is not a fixture."""
    path = tmp_path / "register.db"
    monkeypatch.setenv("RR_REGISTER", str(path))
    return path


def test_bare_invocation_prints_help_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1
    assert "COMMAND" in capsys.readouterr().out


#: Commands that take a required positional, so "parses with no arguments" is
#: the wrong question to ask of them.
_NEEDS_ARGUMENT = {"mute": ["some-finding-id"]}


def test_every_registered_command_parses() -> None:
    parser = build_parser()
    for name in COMMANDS:
        args = parser.parse_args([name, *_NEEDS_ARGUMENT.get(name, [])])
        assert callable(args.handler)


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    from reconciler import __version__

    assert main(["version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_check_finds_the_planted_drift_and_exits_non_zero(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-zero on drift is what lets CI gate on it."""
    assert main(["check"]) == 1
    out = capsys.readouterr().out

    assert "alerts" in out
    assert "paid operations" in out


def test_check_exit_zero_never_blocks(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The pre-commit nudge's whole contract: it reports and gets out of the way."""
    assert main(["check", "--exit-zero"]) == 0
    assert "findings" in capsys.readouterr().out


def test_status_on_an_empty_register_is_zeroes_not_a_traceback(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0
    out = capsys.readouterr().out

    assert "0 claims" in out
    assert "awaiting review" in out


def test_status_reports_what_a_sweep_left_behind(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check"])
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out

    assert "awaiting review" in out
    assert "recent runs:" in out
    assert "0 operation(s)" in out


def test_propose_without_yes_spends_nothing(
    scratch_register: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Priced, not spent — and proved by there being no client to spend with.

    `SUPERDOCS_API_KEY` is cleared, so any code path that actually reached the
    service would fail rather than quietly succeeding against a real key that
    happened to be in the environment.
    """
    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
    main(["check"])
    capsys.readouterr()

    assert main(["propose"]) == 0
    out = capsys.readouterr().out

    assert "this will spend" in out
    assert "nothing spent" in out


def test_propose_with_yes_and_no_key_refuses_rather_than_half_running(
    scratch_register: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
    main(["check"])
    capsys.readouterr()

    assert main(["propose", "--yes"]) == 2
    assert "SUPERDOCS_API_KEY is not set" in capsys.readouterr().err


def test_propose_on_a_clean_estate_says_so(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rule 5's shape at the command line: nothing found, nothing offered."""
    assert main(["propose"]) == 0
    assert "nothing to propose" in capsys.readouterr().out


def test_sweep_narrowed_to_pages_reports_no_coverage_number(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The six-false-dead-links bug, pinned at the level a user meets it."""
    assert main(["sweep", "--pages", "1008"]) in (0, 1)
    out = capsys.readouterr().out

    assert "coverage: not computed" in out
    assert "dead links" not in out


def test_review_with_auto_reject_writes_nothing(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check"])
    capsys.readouterr()

    assert main(["review", "--auto", "reject"]) == 0
    out = capsys.readouterr().out

    assert "0 passages updated" in out


# ------------------------------------------------------------------- mute --


def test_mute_writes_the_subject_into_config_and_keeps_the_comments(tmp_path: Path) -> None:
    """`config/mappings.yaml` is mostly comments — it is the file that explains
    to a platform team what each escape hatch is for. Round-tripping it through
    a YAML dumper would strip every one of them the first time somebody runs
    this, which is making the config worse to save the tool twenty lines."""
    from reconciler.config import CONFIG_DIR, Mappings, mute_subject

    target = tmp_path / "mappings.yaml"
    original = (CONFIG_DIR / "mappings.yaml").read_text(encoding="utf-8")
    target.write_text(original, encoding="utf-8")

    assert mute_subject("alert:X:threshold", target) is True
    assert mute_subject("alert:Y:threshold", target) is True
    assert mute_subject("alert:X:threshold", target) is False, "already muted"

    muted = Mappings.load(target).ignore_subjects
    assert set(muted) == {"alert:X:threshold", "alert:Y:threshold"}

    after = target.read_text(encoding="utf-8")
    assert after.count("#") == original.count("#"), "comments were lost"
    assert "aliases:" in after and "former_names:" in after


def test_mute_refuses_rather_than_guessing_at_an_unfamiliar_file(tmp_path: Path) -> None:
    """Returning False sends the operator a line to paste. Guessing at somebody's
    YAML would send them a corrupted config."""
    from reconciler.config import mute_subject

    odd = tmp_path / "mappings.yaml"
    odd.write_text("aliases: {}\n", encoding="utf-8")
    assert mute_subject("alert:X:threshold", odd) is False
    assert odd.read_text(encoding="utf-8") == "aliases: {}\n"


def test_muting_clears_the_findings_already_in_the_queue(tmp_path: Path) -> None:
    """Muting changes what future sweeps produce. The rows already in the
    register keep their ids and their `decision IS NULL`, so without this the
    reviewer who just said "stop asking me this" is asked it again every time
    they open the queue."""
    from reconciler.claims import Finding
    from reconciler.register import Register

    with Register(tmp_path / "register.db") as register:
        ids = [
            register.upsert_finding(
                Finding(
                    rule_id="ci-job",
                    kind="command",
                    subject="job:rollback-production",
                    verdict="contradicts",
                    evidence_file="fixtures/infra/service-repos/payments-api/.github/"
                    "workflows/deploy.yml",
                    page_id=page,
                )
            )
            for page in ("1001", "1007")
        ]
        assert len(register.review_queue()) == 2

        for finding in register.review_queue():
            if finding.subject == "job:rollback-production":
                register.decide(finding.finding_id, "rejected")

        assert register.review_queue() == []
        tally = {r["rule_id"]: r for r in register.decisions_by_rule()}
        assert tally["ci-job"]["rejected"] == 2
        assert tally["ci-job"]["rejection_rate"] == 1.0
        assert all(register.finding(i).decision == "rejected" for i in ids)


def test_the_rule_tally_separates_a_bad_rule_from_a_messy_page(tmp_path: Path) -> None:
    """The number is a prompt for a human, never an input to anything automatic.

    A rule can be rejected repeatedly for reasons that all belong to one page,
    which is why nothing here mutes anything on its own — it only counts.
    """
    from reconciler.claims import Finding
    from reconciler.register import Register

    with Register(tmp_path / "register.db") as register:
        for n, (rule, decision) in enumerate(
            [
                ("alert-threshold", "approved"),
                ("alert-threshold", "approved"),
                ("alert-threshold", "rejected"),
                ("resource-identifier", "rejected"),
                ("resource-identifier", "rejected"),
            ]
        ):
            finding_id = register.upsert_finding(
                Finding(
                    rule_id=rule,
                    kind="threshold",
                    subject=f"alert:A{n}:threshold",
                    verdict="contradicts",
                    evidence_file="fixtures/infra/platform-infra/monitoring/payments.rules.yml",
                    page_id=f"100{n}",
                )
            )
            register.decide(finding_id, decision)

        tally = {r["rule_id"]: r for r in register.decisions_by_rule()}
        assert tally["alert-threshold"]["rejection_rate"] < 0.5
        assert tally["resource-identifier"]["rejection_rate"] == 1.0
        # Sorted worst-first, so the rule worth looking at is the one you see.
        assert register.decisions_by_rule()[0]["rule_id"] == "resource-identifier"


def test_blame_names_the_commit_behind_a_finding(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The question a reader asks after "is this wrong" is "since when"."""
    assert main(["check", "--blame"]) == 1
    out = capsys.readouterr().out

    assert "drifted :" in out
    assert out.count("evidence:") >= out.count("drifted :")


def test_check_without_blame_runs_no_git_at_all(
    scratch_register: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One subprocess per finding is imperceptible on thirteen and is not on a
    first sweep finding four hundred. The free layer's claim is that it costs
    nothing, so attribution is asked for rather than assumed."""
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError(f"rr check ran a subprocess: {args!r}")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert main(["check"]) == 1


def test_a_finding_whose_evidence_is_a_page_is_not_blamed(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`confluence:page:1005` is not a path and has no history here. It prints
    without attribution rather than with a guess."""
    from reconciler.cli import _drifted_in

    class Fake:
        evidence_file = "confluence:page:1005"
        evidence_line = 1

    assert _drifted_in(Fake()) is None
