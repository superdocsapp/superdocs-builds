"""The paths a real user hits: typos, malformed files, no API key, and re-runs.

None of these need a key or a network. They exist because the first thing a stranger
does with a tool is get the arguments slightly wrong, and what happens then decides
whether they try again.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from imo.cli import main  # noqa: E402
from imo.deal import load_deal  # noqa: E402
from imo.documents import CONFLICT_HEADING, conflict_instruction, plan_fan_out, render_all  # noqa: E402
from imo.conflicts import detect  # noqa: E402

DEAL = ROOT / "deals" / "northstar.yaml"


class TestCliErrorPaths:
    def test_a_missing_deal_file_gives_a_message_not_a_traceback(self, tmp_path, capsys) -> None:
        """A mistyped filename is the single most common first interaction. A stack
        trace tells the user the tool is broken; a sentence tells them they typoed."""
        code = main([str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "out"), "--offline"])
        captured = capsys.readouterr()

        assert code != 0
        assert "Traceback" not in captured.err
        assert "nope.yaml" in captured.err

    def test_malformed_yaml_gives_a_message_not_a_traceback(self, tmp_path, capsys) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("deal: [unclosed\n", encoding="utf-8")

        code = main([str(bad), "--out", str(tmp_path / "out"), "--offline"])
        captured = capsys.readouterr()

        assert code != 0
        assert "Traceback" not in captured.err

    def test_an_invalid_spec_names_the_problem(self, tmp_path, capsys) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("deal:\n  code_name: X\ntarget_profile:\n  headcount: 1\nworkstreams: []\n", encoding="utf-8")

        code = main([str(bad), "--out", str(tmp_path / "out"), "--offline"])
        assert code != 0
        assert "workstream" in capsys.readouterr().err

    def test_offline_needs_no_api_key(self, tmp_path, monkeypatch) -> None:
        """The claim in the README. Verified by removing the key entirely."""
        monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
        assert main([str(DEAL), "--out", str(tmp_path / "out"), "--offline"]) == 0

    def test_without_offline_and_without_a_key_it_says_so(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
        code = main([str(DEAL), "--out", str(tmp_path / "out")])
        captured = capsys.readouterr()

        assert code != 0
        assert "SUPERDOCS_API_KEY" in captured.err
        assert "--offline" in captured.err, "tell the user what they can still do"


class TestRendering:
    def test_the_full_set_is_produced(self, tmp_path) -> None:
        deal = load_deal(DEAL)
        documents = render_all(deal)

        keys = {d.key for d in documents}
        assert "charter" in keys
        assert "day-one" in keys
        assert "synergy-tracker" in keys
        assert "comms-pack" in keys
        assert sum(1 for k in keys if k.startswith("workstream-")) == len(deal.workstreams)

    def test_rendering_is_deterministic(self, tmp_path) -> None:
        """Two runs over an unchanged deal must produce identical bytes, or every
        regeneration shows a diff that means nothing."""
        deal = load_deal(DEAL)
        first = {d.filename: d.body for d in render_all(deal)}
        second = {d.filename: d.body for d in render_all(load_deal(DEAL))}
        assert first == second

    def test_every_document_has_the_conflicts_section_it_will_need(self) -> None:
        """The flagging instruction edits a section by name. If a document does not
        have that heading, the edit silently has nowhere to go."""
        deal = load_deal(DEAL)
        documents = {d.key: d for d in render_all(deal)}
        plan = plan_fan_out(deal, detect(deal))

        for key in plan:
            assert CONFLICT_HEADING in documents[key].body, (
                f"{key} is due to receive conflict flags but has no "
                f"'{CONFLICT_HEADING}' section for them to land in"
            )

    def test_the_day_one_checklist_is_specific_to_this_deal(self) -> None:
        """The card asks for a checklist specific to this deal rather than a generic
        list. The test of that is whether it names this deal's actual items and the
        actual dependencies putting them at risk."""
        body = next(d for d in render_all(load_deal(DEAL)) if d.key == "day-one").body

        assert "DAY-HR-2" in body
        assert "Items at Risk" in body
        assert "DEP-PAY" in body, "the blocking dependency must be named, not just the item"

    def test_numbers_in_the_tracker_come_from_the_spec(self) -> None:
        deal = load_deal(DEAL)
        body = next(d for d in render_all(deal) if d.key == "synergy-tracker").body

        assert f"{deal.synergy_target_usd:,.0f}" in body
        assert f"{deal.claimed_synergy_total:,.0f}" in body


class TestFlaggingInstruction:
    def test_it_names_the_section_and_forbids_everything_else(self) -> None:
        """A vague instruction gets a helpfully rewritten document, and 'helpfully
        rewritten' is indistinguishable from 'silently damaged' three documents in."""
        deal = load_deal(DEAL)
        conflict = detect(deal)[0]
        instruction = conflict_instruction(conflict, audience=conflict.affects[0])

        assert CONFLICT_HEADING in instruction
        assert "Change nothing else" in instruction
        assert conflict.summary in instruction

    def test_it_carries_this_document_s_own_stake(self) -> None:
        """The same conflict reads differently in each charter — each lead needs to see
        their own claim, not just the abstract clash."""
        deal = load_deal(DEAL)
        duplicate = next(c for c in detect(deal) if c.kind == "duplicate_synergy")

        first, second = duplicate.affects[0], duplicate.affects[1]
        assert conflict_instruction(duplicate, audience=first) != conflict_instruction(
            duplicate, audience=second
        )
