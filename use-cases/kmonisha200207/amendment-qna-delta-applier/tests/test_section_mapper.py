from pathlib import Path

from delta_applier.models import AmendmentDelta, SourceRef
from delta_applier.section_mapper import SectionMapConfig, map_impacts, untouched_sections

CONFIG_PATH = Path(__file__).parent.parent / "config" / "section_map.yaml"


def _delta(rule_type, key, delta_id="d1", change_kind="modified"):
    return AmendmentDelta(
        delta_id=delta_id,
        rule_type=rule_type,
        key=key,
        old_value="old",
        new_value="new",
        change_kind=change_kind,
        source=SourceRef("amendment_0001.txt", "PARA 1", "text"),
    )


def test_direct_and_second_order_impacts():
    config = SectionMapConfig.load(str(CONFIG_PATH))
    deltas = [
        _delta("page_limit", "volume_I", "d-page"),
        _delta("requirement", "C.2", "d-c2", change_kind="deleted"),
    ]

    impacts = map_impacts(deltas, config)

    assert impacts["SEC-VOL1-TECH"].order == "direct"
    assert impacts["SEC-VOL1-DR-PLAN"].order == "direct"
    # SEC-COMPLIANCE-MATRIX depends on both SEC-VOL1-TECH and SEC-VOL1-DR-PLAN -> second-order
    assert impacts["SEC-COMPLIANCE-MATRIX"].order == "second_order"
    assert len(impacts["SEC-COMPLIANCE-MATRIX"].deltas) >= 1

    untouched = untouched_sections(config, impacts)
    assert "SEC-VOL2-PASTPERF" in untouched
    assert "SEC-EXEC-SUMMARY" in untouched
    assert "SEC-VOL1-TECH" not in untouched


def test_direct_impact_wins_over_second_order_when_a_section_is_both():
    config = SectionMapConfig.load(str(CONFIG_PATH))
    # SEC-VOL1-TECH is directly hit by page_limit; also declare requirement_added
    # (which also targets SEC-VOL1-TECH by "default") to make sure repeated
    # direct hits still merge cleanly rather than downgrading to second-order.
    deltas = [
        _delta("page_limit", "volume_I", "d1"),
        _delta("requirement", "C.5", "d2", change_kind="added"),
    ]
    impacts = map_impacts(deltas, config)
    assert impacts["SEC-VOL1-TECH"].order == "direct"
    assert len(impacts["SEC-VOL1-TECH"].deltas) == 2
