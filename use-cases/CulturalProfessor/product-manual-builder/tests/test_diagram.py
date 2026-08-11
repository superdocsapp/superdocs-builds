"""The diagrams are a pure function of the parts graph.

That is the second grading criterion, and "we regenerate rather than redraw" is
only worth saying if regenerating an unchanged graph produces unchanged bytes.
Otherwise every edit shows a diff in every diagram and nobody can tell which
changes were meant.
"""
from __future__ import annotations

import subprocess
import sys

from manualbuilder import diagram
from manualbuilder.spec import load_spec

from .conftest import PROJECT_ROOT, SPEC_PATH


def test_the_same_graph_renders_the_same_bytes(spec):
    assert diagram.exploded(spec) == diagram.exploded(spec)
    step = spec.step("laser")
    assert diagram.for_step(spec, step) == diagram.for_step(spec, step)


def test_rendering_is_stable_across_processes():
    """In-process equality would still hold if the layout depended on set or
    dict ordering, because that ordering is fixed for the life of a process.
    Two interpreters with different hash seeds is the test that actually
    catches it -- and a diagram that changed between CI runs would look exactly
    like a diagram someone edited."""
    script = (
        "from manualbuilder.spec import load_spec;"
        "from manualbuilder import diagram;"
        f"print(diagram.exploded(load_spec({str(SPEC_PATH)!r})), end='')"
    )
    runs = []
    for seed in ("0", "1", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=PROJECT_ROOT, capture_output=True,
            text=True, timeout=120,
            env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(PROJECT_ROOT),
                 "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0, result.stderr
        runs.append(result.stdout)
    assert runs[0] == runs[1] == runs[2]


def test_a_change_to_the_graph_changes_the_drawing(spec, tmp_path):
    """The other half of determinism. Bytes that never change would also be
    "deterministic", and useless."""
    import yaml

    raw = yaml.safe_load(SPEC_PATH.read_text())
    raw["parts"].append({"id": "spare_lens", "label": "Spare lens",
                         "quantity": 2, "mounts_to": "laser_module"})
    path = tmp_path / "extra.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))

    changed = load_spec(path)
    assert diagram.exploded(changed) != diagram.exploded(spec)
    assert "Spare lens" in diagram.exploded(changed)


def test_a_step_diagram_highlights_exactly_the_steps_parts(spec):
    """A step's illustration must not show a part the step does not mention.
    There is no second input to the highlight set, so this is really a test that
    nobody has added one."""
    step = spec.step("laser")
    svg = diagram.for_step(spec, step)

    accent_boxes = svg.count(f'fill="{diagram.ACCENT_FILL}"')
    assert accent_boxes == len(step.parts) == 3

    for part_id in step.parts:
        label = spec.part(part_id).label
        assert label[:20] in svg


def test_every_step_gets_the_same_layout(spec):
    """The reader should recognise the machine from step to step. Same
    coordinates, different emphasis."""
    boxes = [line for line in diagram.exploded(spec).splitlines() if "<rect x=" in line]
    for step in spec.steps:
        step_boxes = [line for line in diagram.for_step(spec, step).splitlines()
                      if "<rect x=" in line]
        assert len(step_boxes) == len(boxes)
        for a, b in zip(boxes, step_boxes):
            assert _geometry(a) == _geometry(b)


def test_the_parts_list_is_keyed_to_the_drawing(spec):
    """Callout 7 in the table has to be callout 7 in the picture. They come from
    one traversal, and this is the test that keeps them coming from one."""
    rows = diagram.parts_list_rows(spec)
    assert [n for n, _, _, _ in rows] == list(range(1, len(spec.parts) + 1))

    svg = diagram.exploded(spec)
    for number, label, _, _ in rows:
        assert f">{number}</text>" in svg
        assert label[:20] in svg


def test_the_drawing_fits_a_page(spec):
    """A manual is read at page width. The first version of this layout gave
    each assembly level its own column and drew 1574px of mostly whitespace for
    a six-deep chain."""
    place = diagram.layout(spec)
    assert place.width <= 800, f"{place.width}px will not sit in a manual"


def test_the_band_label_does_not_print_underneath_a_part(spec):
    """It did. The "supplied, not mounted" caption sat on the same lines as the
    first loose part's box, which is faintly legible in English and unreadable
    the moment a locale makes either string longer. Geometry, so it is checked
    the way geometry is checked rather than by looking at it again."""
    place = diagram.layout(spec)
    assert place.band_y is not None, "the shipped spec has loose parts"

    baseline = place.band_y + 20                   # where `_render` puts the text
    for spot in place.placed:
        assert not (spot.y <= baseline <= spot.y + diagram.BOX_H), \
            f"the band label lands inside {spot.part.id}'s box"


def _geometry(rect_line: str) -> str:
    """The x/y/width/height of a rect, without its fill or stroke.

    The attribute name has to be anchored to a space. Without that, `width="…"`
    also matches inside `stroke-width="2"`, and the highlighted boxes use a
    thicker stroke -- so the test compared stroke weights and called it a layout
    difference.
    """
    import re

    return " ".join(m.group(2) for m in
                    re.finditer(r'(?:^|\s)(x|y|width|height)="(\d+)"', rect_line))
