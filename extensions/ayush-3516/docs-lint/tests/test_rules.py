"""Tests for parsing and the local rule set.

The recurring theme: an anchor is only useful if slicing the document with it returns exactly the
text the finding is about. Several tests assert that directly, because every downstream promise —
precise locations, applying only approved fixes, proving nothing else changed — rests on it.
"""

from __future__ import annotations

import pytest

from docs_lint.config import Config, parse_config
from docs_lint.model import Severity
from docs_lint.parser import SegmentKind, parse_document
from docs_lint.rules import all_rules, run_local_rules

SAMPLE = """# Getting started

We utilise the API in order to fetch results.

## Installing The Thing Quickly

```
pip install docs-lint
```

```python
value = utilise_this()  # code is not prose
```

Text after code.
"""


def doc(text: str = SAMPLE, path: str = "docs/guide.md"):
    return parse_document(path, text)


def findings_for(text: str, cfg: Config) -> list:
    return list(run_local_rules(doc(text), cfg))


def by_rule(findings, rule_id: str) -> list:
    return [f for f in findings if f.rule_id == rule_id]


# -- parsing ------------------------------------------------------------------------


def test_headings_carry_their_level_and_text():
    headings = [s for s in doc().segments if s.kind is SegmentKind.HEADING]
    assert [(h.level, h.content) for h in headings] == [
        (1, "Getting started"),
        (2, "Installing The Thing Quickly"),
    ]


def test_segments_track_the_heading_section_they_sit_under():
    paragraphs = [s for s in doc().segments if s.kind is SegmentKind.PARAGRAPH]
    assert paragraphs[0].heading_path == ("Getting started",)
    assert paragraphs[-1].heading_path == ("Getting started", "Installing The Thing Quickly")


def test_heading_path_pops_correctly_when_levels_go_back_up():
    document = doc("# One\n\ntext\n\n## Two\n\ntext\n\n### Three\n\ntext\n\n## Four\n\ntext\n")
    paths = [s.heading_path for s in document.segments if s.kind is SegmentKind.PARAGRAPH]
    assert paths == [
        ("One",),
        ("One", "Two"),
        ("One", "Two", "Three"),
        ("One", "Four"),
    ]


def test_code_blocks_are_not_prose():
    kinds = {s.kind for s in doc().prose_segments}
    assert SegmentKind.CODE not in kinds


def test_a_hash_inside_a_fence_is_code_not_a_heading():
    """The reason this is a real parser and not a set of regular expressions."""
    document = doc("# Real heading\n\n```bash\n# not a heading, a shell comment\n```\n")
    headings = [s for s in document.segments if s.kind is SegmentKind.HEADING]
    assert [h.content for h in headings] == ["Real heading"]


def test_an_anchor_slices_back_to_exactly_the_text_it_points_at():
    """The property everything downstream depends on."""
    document = doc()
    segment = document.prose_segments[0]
    anchor = document.anchor(segment)
    assert document.slice(anchor) == segment.raw


def test_line_numbers_are_one_based_and_land_on_the_right_line():
    document = doc("line one\n\n# heading on line three\n\nparagraph on line five\n")
    heading = next(s for s in document.segments if s.kind is SegmentKind.HEADING)
    assert heading.start_line == 3
    assert document.line_of(heading.start_offset) == 3


def test_an_empty_document_parses_to_nothing_rather_than_failing():
    assert doc("").segments == ()
    assert doc("\n\n\n").segments == ()


# -- banned terms -------------------------------------------------------------------


def test_banned_terms_flags_each_occurrence_with_an_exact_anchor(tmp_path):
    document = doc("We utilise the API in order to fetch results.\n")
    found = list(run_local_rules(document, Config(root=tmp_path)))
    hits = by_rule(found, "banned-terms")

    assert {f.original.lower() for f in hits} == {"utilise", "in order to"}
    for finding in hits:
        assert document.slice(finding.anchor) == finding.original


def test_banned_terms_proposes_the_preferred_word(tmp_path):
    hits = by_rule(findings_for("We utilise it.\n", Config(root=tmp_path)), "banned-terms")
    assert hits[0].replacement == "use"
    assert hits[0].is_fixable


def test_a_fix_preserves_the_original_capitalisation(tmp_path):
    """Otherwise fixing 'Utilise the API' introduces a lowercase sentence start."""
    hits = by_rule(findings_for("Utilise the API.\n", Config(root=tmp_path)), "banned-terms")
    assert hits[0].original == "Utilise"
    assert hits[0].replacement == "Use"


def test_applying_a_banned_term_fix_produces_the_expected_document(tmp_path):
    text = "We utilise the API.\n"
    document = doc(text)
    finding = by_rule(list(run_local_rules(document, Config(root=tmp_path))), "banned-terms")[0]
    anchor = finding.anchor

    patched = text[: anchor.start_char] + finding.replacement + text[anchor.end_char :]
    assert patched == "We use the API.\n"


def test_banned_terms_ignores_code(tmp_path):
    text = "```python\nvalue = utilise_this()\n```\n"
    assert by_rule(findings_for(text, Config(root=tmp_path)), "banned-terms") == []


def test_a_team_supplies_its_own_banned_terms(tmp_path):
    """Configuration over code: new house rules are a TOML edit."""
    cfg = parse_config(
        {"rules": {"banned-terms": {"severity": "error", "terms": {"synergy": "teamwork"}}}},
        root=tmp_path,
    )
    hits = by_rule(findings_for("We need synergy and to utilise things.\n", cfg), "banned-terms")
    assert [f.original for f in hits] == ["synergy"], "custom terms replace the defaults entirely"
    assert hits[0].replacement == "teamwork"


def test_multi_word_terms_match_across_line_breaks(tmp_path):
    hits = by_rule(
        findings_for("We did it in order\nto win.\n", Config(root=tmp_path)), "banned-terms"
    )
    assert len(hits) == 1


# -- heading rules ------------------------------------------------------------------


def test_title_case_headings_are_flagged_with_a_sentence_case_fix(tmp_path):
    hits = by_rule(findings_for("## Installing The Thing\n", Config(root=tmp_path)), "heading-case")
    assert len(hits) == 1
    assert hits[0].replacement == "Installing the thing"


def test_sentence_case_headings_pass(tmp_path):
    assert (
        by_rule(findings_for("## Installing the thing\n", Config(root=tmp_path)), "heading-case")
        == []
    )


def test_known_proper_nouns_do_not_trip_the_heading_rule(tmp_path):
    text = "## Using the GitHub API with Python\n"
    assert by_rule(findings_for(text, Config(root=tmp_path)), "heading-case") == []


def test_a_single_stray_capital_is_tolerated(tmp_path):
    """One capital is usually a proper noun we do not know; two is Title Case."""
    assert (
        by_rule(findings_for("## Deploying to Vercel\n", Config(root=tmp_path)), "heading-case")
        == []
    )


def test_a_team_can_add_its_own_proper_nouns(tmp_path):
    cfg = parse_config(
        {"rules": {"heading-case": {"severity": "warning", "proper_nouns": ["Acme", "Widgets"]}}},
        root=tmp_path,
    )
    assert by_rule(findings_for("## Installing Acme Widgets\n", cfg), "heading-case") == []


def test_trailing_punctuation_on_a_heading_is_flagged_and_fixable(tmp_path):
    hits = by_rule(
        findings_for("## Getting started.\n", Config(root=tmp_path)), "heading-punctuation"
    )
    assert hits[0].replacement == "Getting started"


def test_a_question_mark_heading_is_allowed(tmp_path):
    text = "## What is this?\n"
    assert by_rule(findings_for(text, Config(root=tmp_path)), "heading-punctuation") == []


# -- fence language -----------------------------------------------------------------


def test_a_fence_without_a_language_is_flagged_but_not_fixed(tmp_path):
    """The rule knows the language is missing; it does not know which one. So it does not guess."""
    hits = by_rule(
        findings_for("```\npip install x\n```\n", Config(root=tmp_path)), "fence-language"
    )
    assert len(hits) == 1
    assert not hits[0].is_fixable


def test_a_fence_with_a_language_passes(tmp_path):
    assert (
        by_rule(
            findings_for("```bash\npip install x\n```\n", Config(root=tmp_path)), "fence-language"
        )
        == []
    )


# -- prose heuristics ---------------------------------------------------------------


def test_long_sentences_are_reported_without_a_rewrite(tmp_path):
    long = "word " * 50 + "end."
    hits = by_rule(findings_for(long + "\n", Config(root=tmp_path)), "long-sentence")
    assert len(hits) == 1
    assert not hits[0].is_fixable


def test_the_sentence_limit_is_configurable(tmp_path):
    cfg = parse_config(
        {"rules": {"long-sentence": {"severity": "warning", "max_words": 5}}}, root=tmp_path
    )
    assert (
        len(by_rule(findings_for("one two three four five six seven.\n", cfg), "long-sentence"))
        == 1
    )


def test_passive_voice_is_flagged_as_a_candidate_not_a_defect(tmp_path):
    hits = by_rule(
        findings_for("The file was deleted by the script.\n", Config(root=tmp_path)),
        "passive-voice",
    )
    assert len(hits) == 1
    assert not hits[0].is_fixable
    assert "Heuristic" in (hits[0].explanation or "")


def test_common_adjective_false_friends_are_not_flagged_as_passive(tmp_path):
    text = "The config is based on TOML and the file is called docs-lint.toml.\n"
    assert by_rule(findings_for(text, Config(root=tmp_path)), "passive-voice") == []


# -- severity comes from configuration ----------------------------------------------


def test_config_severity_overrides_the_rules_default(tmp_path):
    cfg = parse_config({"rules": {"banned-terms": {"severity": "info"}}}, root=tmp_path)
    hits = by_rule(findings_for("We utilise it.\n", cfg), "banned-terms")
    assert hits[0].severity is Severity.INFO


def test_a_rule_turned_off_produces_nothing(tmp_path):
    cfg = parse_config({"rules": {"banned-terms": {"severity": "off"}}}, root=tmp_path)
    assert by_rule(findings_for("We utilise it.\n", cfg), "banned-terms") == []


def test_every_registered_rule_declares_an_id_and_a_description():
    for rule in all_rules():
        assert rule.rule_id, f"{rule} has no id"
        assert rule.description, f"{rule.rule_id} has no description"


def test_rules_run_in_a_stable_order_so_output_is_reproducible(tmp_path):
    cfg = Config(root=tmp_path)
    first = [f.finding_id for f in findings_for(SAMPLE, cfg)]
    second = [f.finding_id for f in findings_for(SAMPLE, cfg)]
    assert first == second


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n\n",
        "# heading only\n",
        "| a | b |\n| - | - |\n| 1 | 2 |\n",
        "<div>raw html</div>\n",
        "- list item\n- another\n",
        "> quoted text\n",
    ],
)
def test_the_rule_set_survives_unusual_documents(text, tmp_path):
    """No rule may crash on valid Markdown, however odd."""
    list(run_local_rules(doc(text), Config(root=tmp_path)))


def test_a_headings_own_path_excludes_its_preceding_sibling():
    """ "Configuring" sits under the h1, not inside "Installing"."""
    document = doc("# Top\n\n## Installing\n\ntext\n\n## Configuring\n\ntext\n")
    headings = {
        s.content: s.heading_path for s in document.segments if s.kind is SegmentKind.HEADING
    }

    assert headings["Top"] == ()
    assert headings["Installing"] == ("Top",)
    assert headings["Configuring"] == ("Top",), "a sibling must not appear in its sibling's path"


def test_body_text_still_reports_the_section_it_belongs_to():
    document = doc("# Top\n\n## Installing\n\nbody text here\n")
    body = [s for s in document.segments if s.kind is SegmentKind.PARAGRAPH][0]
    assert body.heading_path == ("Top", "Installing")
