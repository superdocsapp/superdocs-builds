"""The extractors: what they find, and what they refuse to guess at."""

from __future__ import annotations

import pytest

from docsync.extract import (
    ExtractError,
    extract,
    is_list_kind,
    parse_extractor,
    render,
    render_scalar,
)

PY = """
from __future__ import annotations

MAX_ATTEMPTS = 3
TIMEOUT: int = 30
NAME = "provisioning.dead-letter"
ENABLED = True
RATIO = 99.95
ROUND = 30.0
COMPUTED = 2 * 3
TABLE = {"a": 1}

def f():
    INSIDE = 99
"""


class TestParseExtractor:
    def test_splits_on_the_first_colon_only(self):
        # A regex full of colons is the normal case, and a naive split would
        # truncate it into something that still compiles and matches the wrong
        # thing — a silent corruption rather than an error.
        kind, argument = parse_extractor(r"regex:^time: (\d+):(\d+)$")
        assert kind == "regex"
        assert argument == r"^time: (\d+):(\d+)$"

    @pytest.mark.parametrize("spec", ["", "nocolon", "bogus:x", "regex:", 42, None])
    def test_rejects_nonsense(self, spec):
        with pytest.raises(ExtractError):
            parse_extractor(spec)

    def test_knows_which_kinds_are_lists(self):
        assert is_list_kind("regex_list")
        assert not is_list_kind("regex")


class TestPythonConstant:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("MAX_ATTEMPTS", 3),
            ("TIMEOUT", 30),
            ("NAME", "provisioning.dead-letter"),
            ("ENABLED", True),
            ("RATIO", 99.95),
        ],
    )
    def test_reads_literals_including_annotated(self, name, expected):
        assert extract("python_constant", name, PY) == expected

    def test_refuses_a_computed_value(self):
        with pytest.raises(ExtractError, match="not a literal"):
            extract("python_constant", "COMPUTED", PY)

    def test_refuses_a_container(self):
        with pytest.raises(ExtractError, match="only strings, numbers and booleans"):
            extract("python_constant", "TABLE", PY)

    def test_ignores_names_nested_inside_a_function(self):
        # Only the top level is read. A constant defined inside a function is
        # not a module fact, and pretending otherwise would let the value drift
        # from what actually runs.
        with pytest.raises(ExtractError, match="no module-level assignment"):
            extract("python_constant", "INSIDE", PY)

    def test_missing_name_is_an_error_not_a_none(self):
        with pytest.raises(ExtractError, match="no module-level assignment"):
            extract("python_constant", "NOPE", PY, source="config.py")

    def test_last_assignment_wins(self):
        text = "X = 1\nX = 2\n"
        assert extract("python_constant", "X", text) == 2

    def test_syntax_error_names_the_line(self):
        with pytest.raises(ExtractError, match="not valid Python"):
            extract("python_constant", "X", "def (:\n")


class TestJsonAndYaml:
    JSON = '{"sla": {"uptime": "99.95%", "tiers": [{"name": "p1", "minutes": 15}]}}'
    YAML = "sla:\n  uptime: 99.95%\n  tiers:\n    - name: p1\n      minutes: 15\n"

    def test_walks_a_dotted_path(self):
        assert extract("json_path", "sla.uptime", self.JSON) == "99.95%"
        assert extract("yaml_path", "sla.uptime", self.YAML) == "99.95%"

    def test_indexes_into_a_list(self):
        assert extract("json_path", "sla.tiers.0.minutes", self.JSON) == 15
        assert extract("yaml_path", "sla.tiers.0.name", self.YAML) == "p1"

    def test_negative_index(self):
        assert extract("json_path", "sla.tiers.-1.minutes", self.JSON) == 15

    def test_out_of_range_index_is_an_error(self):
        with pytest.raises(ExtractError, match="out of range"):
            extract("json_path", "sla.tiers.7.minutes", self.JSON)

    def test_missing_key_lists_what_is_available(self):
        with pytest.raises(ExtractError, match="available at sla"):
            extract("json_path", "sla.downtime", self.JSON, source="service.json")

    def test_a_non_scalar_target_is_refused(self):
        with pytest.raises(ExtractError, match="only\n?\\s*scalars|only scalars"):
            extract("json_path", "sla.tiers", self.JSON)

    def test_index_into_a_mapping_is_an_error(self):
        with pytest.raises(ExtractError, match="not found"):
            extract("json_path", "sla.0", self.JSON)

    def test_malformed_input(self):
        with pytest.raises(ExtractError, match="not valid JSON"):
            extract("json_path", "a", "{oops")


class TestRegex:
    TEXT = "GET /a\nPOST /b\nGET /c\nGET /a\n"

    def test_first_capture(self):
        assert extract("regex", r"^POST (/\w+)$", self.TEXT) == "/b"

    def test_named_group_wins(self):
        assert extract("regex", r"^POST (?P<value>/\w+)$", self.TEXT) == "/b"

    def test_no_capture_group_is_an_error_with_a_fix(self):
        with pytest.raises(ExtractError, match="no capture group"):
            extract("regex", r"^POST /\w+$", self.TEXT)

    def test_no_match_is_an_error_not_an_empty_string(self):
        with pytest.raises(ExtractError, match="matched nothing"):
            extract("regex", r"^DELETE (/\w+)$", self.TEXT)

    def test_bad_pattern(self):
        with pytest.raises(ExtractError, match="does not compile"):
            extract("regex", r"(unclosed", self.TEXT)

    def test_list_is_deduplicated_and_sorted(self):
        # Sorted so that moving a route within a file is not a documentation
        # change; deduplicated so a repeated declaration is not two entries.
        assert extract("regex_list", r"^GET (/\w+)$", self.TEXT) == ["/a", "/c"]

    def test_an_empty_list_is_allowed(self):
        # A set that legitimately becomes empty is a real state, and the diff
        # reports it as a removal rather than as a broken extractor.
        assert extract("regex_list", r"^PATCH (/\w+)$", self.TEXT) == []


class TestRendering:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (3, "3"),
            (True, "true"),
            (False, "false"),
            (30.0, "30"),  # a document says "30", never "30.0"
            (99.95, "99.95"),
            ("99.95%", "99.95%"),
        ],
    )
    def test_one_canonical_spelling_per_value(self, value, expected):
        assert render_scalar(value) == expected

    def test_bool_is_checked_before_int(self):
        # bool subclasses int, so the order of the isinstance checks decides
        # whether True renders as "true" or as "1".
        assert render_scalar(True) == "true"

    def test_format_supplies_the_context_that_makes_an_anchor_safe(self):
        assert render(30, "{value} seconds") == "30 seconds"

    def test_format_applies_to_every_item_of_a_list(self):
        assert render(["a", "b"], "`{value}`") == ["`a`", "`b`"]

    def test_a_broken_format_is_an_error(self):
        with pytest.raises(ExtractError, match="could not be applied"):
            render(30, "{nope}")
