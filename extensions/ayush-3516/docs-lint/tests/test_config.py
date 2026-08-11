"""Tests for configuration loading.

The theme is that configuration is data a team owns: a new banned term, a different severity, or
somebody else's house style should all be edits to a file, never edits to this codebase.
"""

from __future__ import annotations

import pytest

from docs_lint.config import Config, ConfigError, find_config_file, load_config, parse_config
from docs_lint.model import Severity


def write_config(tmp_path, body: str):
    (tmp_path / "docs-lint.toml").write_text(body)
    return tmp_path


# -- discovery ----------------------------------------------------------------------


def test_config_is_found_by_walking_up_like_git_does(tmp_path):
    write_config(tmp_path, "[docs-lint]\n")
    nested = tmp_path / "docs" / "deep" / "deeper"
    nested.mkdir(parents=True)

    assert find_config_file(nested) == tmp_path / "docs-lint.toml"
    assert load_config(nested).root == tmp_path


def test_running_without_a_config_file_is_legitimate(tmp_path):
    config = load_config(tmp_path)
    assert config.root == tmp_path
    assert config.include == ("**/*.md", "**/*.mdx")
    assert config.error_on == frozenset({Severity.ERROR})


# -- severity is per rule and owned by the team -------------------------------------


def test_severity_can_be_set_per_rule_including_for_model_driven_rules(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            """
            [rules.banned-terms]
            severity = "error"

            [rules.heading-case]
            severity = "warning"

            [rules.style-guide-voice]
            severity = "info"
            """,
        )
    )
    assert config.severity_for("banned-terms", Severity.INFO) is Severity.ERROR
    assert config.severity_for("heading-case", Severity.INFO) is Severity.WARNING
    assert config.severity_for("style-guide-voice", Severity.ERROR) is Severity.INFO


def test_a_rule_set_to_off_is_disabled(tmp_path):
    config = load_config(write_config(tmp_path, '[rules.passive-voice]\nseverity = "off"\n'))
    assert not config.is_enabled("passive-voice", Severity.WARNING)


def test_an_unconfigured_rule_keeps_its_built_in_default(tmp_path):
    config = load_config(write_config(tmp_path, "[docs-lint]\n"))
    assert config.severity_for("banned-terms", Severity.ERROR) is Severity.ERROR


def test_rule_options_are_data_so_a_team_supplies_its_own_terms(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            """
            [rules.banned-terms]
            severity = "error"
            terms = { utilise = "use", "in order to" = "to" }
            """,
        )
    )
    options = config.options_for("banned-terms")
    assert options["terms"] == {"utilise": "use", "in order to": "to"}


def test_error_on_controls_what_gates_the_build(tmp_path):
    config = load_config(write_config(tmp_path, '[docs-lint]\nerror_on = ["error", "warning"]\n'))
    assert config.error_on == frozenset({Severity.ERROR, Severity.WARNING})


# -- mistakes are reported, never silently ignored ----------------------------------


def test_a_misspelled_setting_is_an_error_not_a_shrug(tmp_path):
    """A typo that silently does nothing is how people stop trusting a linter."""
    with pytest.raises(ConfigError, match="unknown setting"):
        load_config(write_config(tmp_path, '[docs-lint]\nincldue = ["*.md"]\n'))


def test_an_invalid_severity_names_the_valid_ones(tmp_path):
    with pytest.raises(ConfigError, match="is not a severity"):
        load_config(write_config(tmp_path, '[rules.x]\nseverity = "critical"\n'))


def test_broken_toml_is_reported_with_the_file_name(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write_config(tmp_path, "[docs-lint\n"))


def test_a_negative_budget_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, "[superdocs]\nbudget_operations = -5\n"))


# -- the style guide is data, and the cache knows when it changed -------------------


def test_style_guide_is_a_file_reference_not_code(tmp_path):
    (tmp_path / "house-style.md").write_text("# House style\nUse plain words.\n")
    config = load_config(write_config(tmp_path, '[styleguide]\npath = "house-style.md"\n'))
    assert config.styleguide.read(tmp_path).startswith(b"# House style")


def test_editing_the_style_guide_makes_the_pinned_copy_stale(tmp_path):
    guide = tmp_path / "house-style.md"
    guide.write_text("# House style\nUse plain words.\n")
    root = write_config(tmp_path, '[styleguide]\npath = "house-style.md"\n')
    live_hash = load_config(root).styleguide.current_hash(tmp_path)

    pinned = parse_config(
        {"styleguide": {"path": "house-style.md", "content_sha256": live_hash}}, root=tmp_path
    )
    assert not pinned.styleguide.is_stale(tmp_path)

    guide.write_text("# House style\nUse plain words. Also, never use exclamation marks.\n")
    assert pinned.styleguide.is_stale(tmp_path), "an edited guide must invalidate the cache"


def test_a_missing_style_guide_says_how_to_fix_it(tmp_path):
    config = load_config(write_config(tmp_path, "[docs-lint]\n"))
    with pytest.raises(ConfigError, match="docs-lint init --styleguide"):
        config.styleguide.read(tmp_path)


# -- the cache key ------------------------------------------------------------------


def test_fingerprint_changes_when_any_verdict_affecting_setting_changes(tmp_path):
    def fingerprint(body: str) -> str:
        (tmp_path / "docs-lint.toml").write_text(body)
        return load_config(tmp_path).fingerprint()

    base = fingerprint('[rules.banned-terms]\nseverity = "error"\nterms = { utilise = "use" }\n')

    assert base == fingerprint(
        '[rules.banned-terms]\nseverity = "error"\nterms = { utilise = "use" }\n'
    ), "the same config must fingerprint identically"

    severity_changed = fingerprint(
        '[rules.banned-terms]\nseverity = "warning"\nterms = { utilise = "use" }\n'
    )
    terms_changed = fingerprint(
        '[rules.banned-terms]\nseverity = "error"\nterms = { leverage = "use" }\n'
    )
    assert len({base, severity_changed, terms_changed}) == 3


def test_fingerprint_tracks_the_style_guide_contents(tmp_path):
    a = parse_config({"styleguide": {"content_sha256": "aaa"}}, root=tmp_path).fingerprint()
    b = parse_config({"styleguide": {"content_sha256": "bbb"}}, root=tmp_path).fingerprint()
    assert a != b, "a document judged against new rules has not been judged against them"


def test_fingerprint_ignores_settings_that_cannot_change_a_verdict(tmp_path):
    """Poll interval is not a rule. Changing it must not throw away a valid cache."""
    fast = parse_config({"superdocs": {"poll_interval_seconds": 1.0}}, root=tmp_path)
    slow = parse_config({"superdocs": {"poll_interval_seconds": 5.0}}, root=tmp_path)
    assert fast.fingerprint() == slow.fingerprint()


def test_default_excludes_keep_the_linter_out_of_dependency_directories(tmp_path):
    config = Config(root=tmp_path)
    assert any("node_modules" in pattern for pattern in config.exclude)
    assert any(".venv" in pattern for pattern in config.exclude)
