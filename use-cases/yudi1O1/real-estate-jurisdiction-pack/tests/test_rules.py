"""Rule loading, citation enforcement, staleness, and the federal merge.

The loader is the place where "every disclosure is cited and dated" stops being
a promise and becomes impossible to violate: a rule without a citation does not
load at all.
"""
from __future__ import annotations

from datetime import date

import pytest

from real_estate_pack.rules import (
    FEDERAL_CODE,
    RuleFileError,
    available_jurisdictions,
    load_jurisdiction_file,
    load_ruleset,
    stale_rules,
)

MINIMAL_CITATION = """
      authority: Test Code § 1
      source_url: https://example.invalid/1
      verified_on: 2025-01-01
      review_by: 2030-01-01
"""


def write_jurisdiction(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_rule_without_a_citation_cannot_be_loaded(tmp_path):
    """The structural guarantee behind the card's 'correct and dated' bar."""
    path = write_jurisdiction(tmp_path, "us_zz.yaml", """
code: US-ZZ
name: Nowhere
rules:
  - id: zz_uncited
    kind: disclosure
    title: An uncited disclosure
    body: Something a tenant is told.
""")
    with pytest.raises(RuleFileError, match="missing required field 'citation'"):
        load_jurisdiction_file(path)


@pytest.mark.parametrize("omit", ["authority", "source_url", "verified_on", "review_by"])
def test_every_citation_component_is_mandatory(tmp_path, omit):
    citation_lines = {
        "authority": "      authority: Test Code § 1",
        "source_url": "      source_url: https://example.invalid/1",
        "verified_on": "      verified_on: 2025-01-01",
        "review_by": "      review_by: 2030-01-01",
    }
    kept = "\n".join(v for k, v in citation_lines.items() if k != omit)
    path = write_jurisdiction(tmp_path, "us_zz.yaml", f"""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_rule
    kind: disclosure
    title: A disclosure
    body: Text.
    citation:
{kept}
""")
    with pytest.raises(RuleFileError, match=f"missing required field '{omit}'"):
        load_jurisdiction_file(path)


def test_review_by_before_verified_on_is_rejected(tmp_path):
    path = write_jurisdiction(tmp_path, "us_zz.yaml", """
code: US-ZZ
name: Nowhere
rules:
  - id: zz_rule
    kind: disclosure
    title: A disclosure
    body: Text.
    citation:
      authority: Test Code § 1
      source_url: https://example.invalid/1
      verified_on: 2025-06-01
      review_by: 2025-01-01
""")
    with pytest.raises(RuleFileError, match="is before 'verified_on'"):
        load_jurisdiction_file(path)


def test_a_disclosure_without_a_body_is_rejected(tmp_path):
    """A disclosure with nothing to hand the tenant is not a disclosure."""
    path = write_jurisdiction(tmp_path, "us_zz.yaml", f"""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_rule
    kind: disclosure
    title: An empty disclosure
    citation:
{MINIMAL_CITATION}
""")
    with pytest.raises(RuleFileError, match="needs a 'body'"):
        load_jurisdiction_file(path)


def test_unknown_kind_is_rejected(tmp_path):
    path = write_jurisdiction(tmp_path, "us_zz.yaml", f"""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_rule
    kind: suggestion
    title: Something
    body: Text.
    citation:
{MINIMAL_CITATION}
""")
    with pytest.raises(RuleFileError, match="is not one of"):
        load_jurisdiction_file(path)


def test_limit_kind_requires_a_limit_block(tmp_path):
    path = write_jurisdiction(tmp_path, "us_zz.yaml", f"""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_cap
    kind: limit
    title: A cap with no arithmetic
    citation:
{MINIMAL_CITATION}
""")
    with pytest.raises(RuleFileError, match="requires a 'limit' mapping"):
        load_jurisdiction_file(path)


def test_duplicate_rule_ids_are_rejected(tmp_path):
    path = write_jurisdiction(tmp_path, "us_zz.yaml", f"""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_rule
    kind: disclosure
    title: First
    body: Text.
    citation:
{MINIMAL_CITATION}
  - id: zz_rule
    kind: disclosure
    title: Second
    body: Text.
    citation:
{MINIMAL_CITATION}
""")
    with pytest.raises(RuleFileError, match="duplicate rule id"):
        load_jurisdiction_file(path)


def test_malformed_yaml_names_the_file(tmp_path):
    path = write_jurisdiction(tmp_path, "us_zz.yaml", "code: [unclosed\n")
    with pytest.raises(RuleFileError, match="not valid YAML"):
        load_jurisdiction_file(path)


def test_missing_jurisdiction_lists_the_ones_that_exist():
    with pytest.raises(RuleFileError, match="Known:"):
        load_ruleset("US-ZZ")


@pytest.mark.parametrize(
    "hostile",
    ["../../../etc/passwd", "..", "../us_ca", "/etc/passwd", "us_ca/../../secret"],
)
def test_a_jurisdiction_code_cannot_escape_the_rules_directory(hostile):
    """The code arrives from hand-written YAML or `--jurisdiction`, so it is
    untrusted input, not a label. Left raw it resolves to an arbitrary path."""
    with pytest.raises(RuleFileError):
        load_ruleset(hostile)


def test_a_normal_code_still_resolves_after_the_hardening():
    """The traversal guard must not break the ordinary path."""
    assert load_ruleset("US-CA").code == "US-CA"
    assert load_ruleset("us-ca").code == "US-CA"


# --------------------------------------------------------------- federal merge


def test_state_rulesets_carry_the_federal_layer_underneath():
    california = load_ruleset("US-CA")
    ids = {r.id for r in california.rules}
    assert "fed_lead_paint_disclosure" in ids, "federal rules must be merged into every state"
    assert "ca_megans_law" in ids


def test_federal_rules_come_first_so_lead_paint_is_not_buried():
    california = load_ruleset("US-CA")
    federal_positions = [i for i, r in enumerate(california.rules) if r.jurisdiction_code == FEDERAL_CODE]
    state_positions = [i for i, r in enumerate(california.rules) if r.jurisdiction_code != FEDERAL_CODE]
    assert max(federal_positions) < min(state_positions)


def test_loading_the_federal_ruleset_does_not_merge_itself_twice():
    federal = load_ruleset(FEDERAL_CODE)
    ids = [r.id for r in federal.rules]
    assert len(ids) == len(set(ids))


def test_a_state_rule_colliding_with_a_federal_id_is_rejected(tmp_path):
    write_jurisdiction(tmp_path, "us_fed.yaml", f"""
code: US-FED
name: Federal
rules:
  - id: shared_id
    kind: disclosure
    title: Federal rule
    body: Text.
    citation:
{MINIMAL_CITATION}
""")
    write_jurisdiction(tmp_path, "us_zz.yaml", f"""
code: US-ZZ
name: Nowhere
rules:
  - id: shared_id
    kind: disclosure
    title: State rule
    body: Text.
    citation:
{MINIMAL_CITATION}
""")
    with pytest.raises(RuleFileError, match="defined in both"):
        load_ruleset("US-ZZ", tmp_path)


# ------------------------------------------------------------------- staleness


def test_staleness_is_decided_by_the_review_date():
    california = load_ruleset("US-CA")
    cap = next(r for r in california.rules if r.id == "ca_security_deposit_cap")
    assert cap.citation.is_stale(date(2099, 1, 1)) is True
    assert cap.citation.is_stale(cap.citation.review_by) is False, "the review date itself is still current"
    assert cap.citation.is_stale(date(2025, 1, 1)) is False


def test_stale_rules_helper_reports_only_expired_ones():
    texas = load_ruleset("US-TX")
    assert stale_rules(texas, date(2025, 1, 1)) == []
    assert len(stale_rules(texas, date(2099, 1, 1))) == len(texas.rules)


def test_citation_render_carries_both_dates():
    """The index's audit value depends on both dates surviving to the page."""
    rendered = load_ruleset("US-FL").rules[0].citation.render()
    assert "verified" in rendered and "review by" in rendered


def test_available_jurisdictions_finds_everything_shipped():
    codes = set(available_jurisdictions())
    assert {"US-FED", "US-CA", "US-TX", "US-NY", "US-FL"} <= codes
