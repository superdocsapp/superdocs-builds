"""What the spec refuses to load, and why each refusal matters.

A spec that is wrong in these ways still renders. It produces two documents that
are each individually well-formed and jointly wrong -- a card citing a step the
manual does not have, a diagram highlighting nothing, a safety notice somebody
wrote that ships in no document at all. Those are the failures this project
exists to prevent, so they are refused at load time where one person reads one
error, rather than at render time in one of six locales.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from manualbuilder.spec import SpecError, load_spec

from .conftest import SPEC_PATH


def write(tmp_path, mutate):
    raw = yaml.safe_load(SPEC_PATH.read_text())
    mutate(raw)
    path = tmp_path / "mutated.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def refuses(tmp_path, mutate) -> str:
    with pytest.raises(SpecError) as caught:
        load_spec(write(tmp_path, mutate))
    return str(caught.value)


def test_the_shipped_spec_is_valid(spec):
    assert spec.name == "Halyard M1"
    assert len(spec.parts) == 12
    assert len(spec.steps) == 7


def test_a_step_naming_a_part_that_does_not_exist(tmp_path):
    """The step would render, and its diagram would highlight nothing. Silently:
    the drawing is still a valid drawing, just of no part in particular."""
    def mutate(raw):
        raw["setup_steps"][1]["parts"].append("flux_capacitor")
    assert "unknown part 'flux_capacitor'" in refuses(tmp_path, mutate)


def test_a_card_step_that_is_not_a_manual_step(tmp_path):
    """The whole consistency guarantee is that the card is a projection. A card
    step with no manual behind it is a second source of truth, which is the
    thing being ruled out."""
    def mutate(raw):
        raw["quick_start"]["steps"].append("calibrate_the_flux")
    message = refuses(tmp_path, mutate)
    assert "not a setup step" in message
    assert "never a source of its own" in message


def test_a_warning_nobody_references(tmp_path):
    """Someone wrote a safety notice believing it shipped. It does not appear in
    any document. That is a spec bug and not a stylistic one."""
    def mutate(raw):
        raw["warnings"].append({
            "id": "orphan", "severity": "danger", "title": "Unreferenced",
            "body": "This would never appear in any document.",
        })
    assert "would never appear in any document" in refuses(tmp_path, mutate)


def test_a_mounts_to_cycle(tmp_path):
    """The layout walks `mounts_to`. A cycle recurses until the stack runs out
    rather than drawing anything."""
    def mutate(raw):
        by_id = {p["id"]: p for p in raw["parts"]}
        by_id["base"]["mounts_to"] = "lid"  # lid already mounts to base
    assert "cycle" in refuses(tmp_path, mutate)


def test_a_duplicate_part_id(tmp_path):
    """Two parts with one id means a callout number pointing at two rows."""
    def mutate(raw):
        raw["parts"].append(copy.deepcopy(raw["parts"][0]))
    assert "duplicate part id 'base'" in refuses(tmp_path, mutate)


def test_an_unknown_severity(tmp_path):
    """Severity drives how a warning is labelled in both documents. An unknown
    one would render as itself, differently, in each."""
    def mutate(raw):
        raw["warnings"][0]["severity"] = "quite bad"
    assert "expected one of" in refuses(tmp_path, mutate)


def test_every_problem_is_reported_at_once(tmp_path):
    """Fixing a spec one error per run is how someone gives up halfway and
    hand-edits the output instead."""
    def mutate(raw):
        raw["setup_steps"][0]["parts"].append("nope")
        raw["quick_start"]["steps"].append("also_nope")
    message = refuses(tmp_path, mutate)
    assert "nope" in message and "also_nope" in message
    assert message.count("\n  - ") >= 2
