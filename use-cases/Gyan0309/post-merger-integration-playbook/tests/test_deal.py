"""Deal loading, validation, and the edges a real deal file will hit.

A malformed spec must fail loudly at load time. The failure mode of a half-read spec is
a complete, polished, wrong document set — and nobody reading a well-formatted
integration charter thinks to doubt the input file.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from imo.conflicts import detect  # noqa: E402
from imo.deal import DealSpecError, load_deal  # noqa: E402

MINIMAL = """
deal:
  code_name: Test
  acquirer: A Ltd
  target: B Ltd
  announced: 2026-01-01
  expected_close: 2026-03-01
  deal_value_usd: 1000000
  synergy_target_usd: {target}
target_profile:
  headcount: 10
workstreams:
  - key: finance
    name: Finance
{extra}
"""


def _write(tmp_path: Path, *, target="1000000", extra="") -> Path:
    path = tmp_path / "deal.yaml"
    path.write_text(MINIMAL.format(target=target, extra=extra), encoding="utf-8")
    return path


class TestTheShippedDeal:
    def test_it_loads(self) -> None:
        deal = load_deal(ROOT / "deals" / "northstar.yaml")
        assert deal.code_name == "Northstar"
        assert len(deal.workstreams) == 4

    def test_every_comparator_fires_on_it(self) -> None:
        """The sample deal exists to exercise the detectors. A comparator with nothing
        to catch is a claimed capability nobody has seen work."""
        kinds = {c.kind for c in detect(load_deal(ROOT / "deals" / "northstar.yaml"))}
        assert kinds == {
            "duplicate_synergy",
            "contested_dependency",
            "synergy_over_commitment",
            "unmet_day_one",
        }


class TestValidation:
    def test_a_missing_required_field_names_itself(self, tmp_path) -> None:
        path = tmp_path / "deal.yaml"
        path.write_text(
            MINIMAL.format(target="1000000", extra="").replace("  acquirer: A Ltd\n", ""),
            encoding="utf-8",
        )
        with pytest.raises(DealSpecError, match="acquirer"):
            load_deal(path)

    def test_a_deal_with_no_workstreams_is_refused(self, tmp_path) -> None:
        path = tmp_path / "deal.yaml"
        path.write_text(
            MINIMAL.format(target="1000000", extra="").replace(
                "workstreams:\n  - key: finance\n    name: Finance\n", "workstreams: []\n"
            ),
            encoding="utf-8",
        )
        with pytest.raises(DealSpecError, match="at least one workstream"):
            load_deal(path)

    def test_duplicate_workstream_keys_are_refused(self, tmp_path) -> None:
        path = tmp_path / "deal.yaml"
        path.write_text(
            MINIMAL.format(target="1000000", extra="")
            + "  - key: finance\n    name: Finance Again\n",
            encoding="utf-8",
        )
        with pytest.raises(DealSpecError, match="duplicate workstream key"):
            load_deal(path)

    def test_a_close_before_the_announcement_is_refused(self, tmp_path) -> None:
        path = tmp_path / "deal.yaml"
        path.write_text(
            MINIMAL.format(target="1000000", extra="").replace(
                "expected_close: 2026-03-01", "expected_close: 2025-01-01"
            ),
            encoding="utf-8",
        )
        with pytest.raises(DealSpecError, match="before"):
            load_deal(path)

    def test_a_quoted_date_is_refused_rather_than_silently_wrong(self, tmp_path) -> None:
        """YAML turns an unquoted date into a `date` and a quoted one into a string.
        Accepting the string would put a value into date arithmetic that cannot do it."""
        path = tmp_path / "deal.yaml"
        path.write_text(
            MINIMAL.format(target="1000000", extra="").replace(
                "announced: 2026-01-01", "announced: '2026-01-01'"
            ),
            encoding="utf-8",
        )
        with pytest.raises(DealSpecError, match="expected a date"):
            load_deal(path)

    def test_a_day_one_item_citing_an_unknown_dependency_is_refused(self, tmp_path) -> None:
        """Referential integrity. Otherwise the checklist confidently lists an item
        whose stated blocker does not exist."""
        extra = (
            "    day_one:\n"
            "      - id: DAY-1\n"
            "        description: Something\n"
            "        depends_on: [DEP-NOPE]\n"
        )
        with pytest.raises(DealSpecError, match="DEP-NOPE"):
            load_deal(_write(tmp_path, extra=extra))

    def test_a_dependency_needed_by_an_unknown_workstream_is_refused(self, tmp_path) -> None:
        extra = (
            "    dependencies:\n"
            "      - id: DEP-1\n"
            "        description: Something\n"
            "        needed_by: [marketing]\n"
        )
        with pytest.raises(DealSpecError, match="marketing"):
            load_deal(_write(tmp_path, extra=extra))


class TestNumericEdges:
    def test_money_with_symbols_and_separators_parses(self, tmp_path) -> None:
        """A human editing a deal file will write $1,500,000. Refusing that is hostile."""
        deal = load_deal(_write(tmp_path, target="'$1,500,000'"))
        assert deal.synergy_target_usd == Decimal(1_500_000)

    def test_a_zero_synergy_target_does_not_crash_detection(self, tmp_path) -> None:
        """An early-stage deal legitimately has no target set yet. Percentage-of-target
        arithmetic must not divide by it."""
        extra = (
            "    synergies:\n"
            "      - id: SYN-1\n"
            "        description: A saving\n"
            "        annual_value_usd: 500000\n"
        )
        deal = load_deal(_write(tmp_path, target="0", extra=extra))
        conflicts = detect(deal)  # must not raise
        assert any(c.kind == "synergy_over_commitment" for c in conflicts)

    def test_a_deal_with_no_synergies_at_all_is_clean(self, tmp_path) -> None:
        deal = load_deal(_write(tmp_path, target="1000000"))
        assert deal.claimed_synergy_total == Decimal(0)
        assert detect(deal) == []
