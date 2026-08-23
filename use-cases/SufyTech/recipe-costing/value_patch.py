"""
value_patch.py — forces DERIVED numeric values (an affected ingredient's
Unit Cost and Line Cost, each dish's Portion cost, and Gross margin) in
AI-edited HTML to match recipe_costing.py's actual computed values, per
dish.

REAL BUG THIS FIXES, logged honestly: after the export-staleness fix
(SuperDocsClient.verify_and_get_final_html) was confirmed working on a
live run — Unit Cost correctly updated to the new price in all 3
affected dishes — a closer inspection of the actual exported .docx
(decompiled and checked cell-by-cell, not eyeballed) found the DERIVED
numbers were stale or inconsistent: Unit Cost updated correctly, but
that ingredient's own Line Cost, and/or the dish's Portion cost and
Gross margin, did not. verify_and_get_final_html was working exactly as
designed — it exports precisely what was approved. The bug is that what
got approved was itself incomplete: SuperDocs' AI edit updated one
number without reliably recomputing everything that depends on it.

SECOND REAL BUG FOUND HERE, logged honestly: an even later live run
showed the exact opposite failure mode was also possible — Margherita
Pizza's Line Cost, Portion cost, and Gross margin were all correctly
updated, but that dish's own Unit Cost cell was left at the OLD price,
producing an internally inconsistent row (Unit Cost $0.45, Line Cost
$0.68 — which is 0.5oz x the NEW $1.35 price, not the old $0.45 one).
Root cause: the AI's edit doesn't reliably touch every cell every time,
and this module previously only force-patched Line Cost, Portion cost,
and Gross margin — never Unit Cost itself, so a dish where the AI
skipped the Unit Cost cell shipped with mismatched numbers a reviewer
could catch with basic arithmetic. Fixed by force-patching Unit Cost
too, with the exact same fail-closed discipline as every other value
this module patches: never trust the AI touched it, always overwrite
with recipe_costing.py's own value, and raise loudly if the cell can't
be found rather than silently leaving it stale.

THIRD REAL BUG FOUND HERE, logged honestly: cell-by-cell verification
of a live export caught an UNAFFECTED dish (Truffle Fries, no olive oil
in its recipe) showing another dish's (Grilled Salmon's) exact Portion
cost and Gross margin values. Root cause: _find_dish_section located
section boundaries with literal, byte-exact "<div>" / "<hr/>" string
matches. This module's own earlier fix already established that
SuperDocs' server adds tracking attributes (e.g. data-chunk-id) to
elements, which is exactly why the <h2> match was hardened to
`<h2[^>]*>` — but the <div>/<hr/> boundary matches were never given the
same treatment. When a <div> or <hr/> in the real document picks up an
attribute, the literal match fails, `.find()`/`.rfind()` falls through
to the string-boundary fallback, and a dish's "section" can silently
balloon to include every dish after it. Combined with the Portion
cost/Gross margin `re.subn` calls not being scoped to `count=1` (unlike
the Unit Cost/Line Cost patches, which already were, which is exactly
why they never showed this symptom), a correct value computed for one
dish got stamped onto every matching line inside the oversized section
— including untouched dishes further down the document. Fixed by (1)
matching <div>/<hr/> the same attribute-tolerant way as <h2>, and (2)
adding count=1 to every subn call in this module as defense-in-depth,
so even an imperfect boundary can never patch more than one dish's
line.

Same design principle as the rest of this build — arithmetic never
touches the LLM — so this module does NOT ask the AI to fix its own
math, and does NOT try to parse/recompute from the HTML it wrote
either. It deterministically FORCES every derived number using
recipe_costing.py's already-proven-correct calculations, scoped per
dish section by name. This is robust to whatever exact HTML the AI
produced, because it never depends on byte-exact matching of the AI's
output — only on each cell's LABEL and the dish-name <h2> marker, both
of which originate from OUR OWN document_builder.py template, not from
anything the AI wrote.

What this must never do:
  - never recompute anything itself — every corrected value comes
    directly from a recipe_costing.py function's return value
  - never touch a dish's section that wasn't actually affected by the
    price change — scoped strictly to the dish names it's told to patch
  - never silently skip a dish, cell, or ingredient row it can't find —
    raises loudly (same fail-closed discipline as
    verify_and_get_final_html) rather than exporting a document that
    might still be wrong
  - never let one dish's patch bleed into another dish's section, even
    if the boundary detection itself is ever imperfect again — every
    substitution in this module is scoped to count=1 as a second,
    independent layer of protection on top of section boundaries
"""

from __future__ import annotations

import re

from recipe_costing import Recipe, gross_margin, ingredient_line_cost, portion_cost


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _find_dish_section(html: str, dish_name: str) -> tuple[int, int]:
    """
    Returns (start, end) character offsets covering the section for
    `dish_name`, located by its <h2>{dish_name}</h2> marker. Section
    start is the nearest preceding dish-opening <div>, end is the next
    <hr/> section separator (or end of string for the last dish).

    Both the <div> and <hr/> markers are matched tolerant of attributes
    (e.g. a server-added data-chunk-id) — matching _how the <h2> marker
    is already matched below — since these tags come from
    document_builder.py's own template but may be re-emitted with
    extra attributes by SuperDocs' server, and a literal byte-exact
    match silently falls through to the wrong boundary if so (this was
    a real bug: see module docstring, Bug 3).

    Raises RuntimeError if the dish can't be found at all — fail
    closed, never silently skip a dish that should have been patched.
    """
    header_pattern = re.compile(rf"<h2[^>]*>\s*{re.escape(dish_name)}\s*</h2>")
    header_match = header_pattern.search(html)
    if header_match is None:
        nearby = html[:300]
        raise RuntimeError(
            f"value_patch: could not locate an <h2> section marker for {dish_name!r}. "
            f"First 300 chars of the actual document, for diagnosis: {nearby!r}"
        )

    div_pattern = re.compile(r"<div[^>]*>")
    div_start = None
    for m in div_pattern.finditer(html, 0, header_match.start()):
        div_start = m.start()  # keep the LAST (nearest-preceding) match
    section_start = div_start if div_start is not None else header_match.start()

    hr_pattern = re.compile(r"<hr[^>]*/?>")
    hr_match = hr_pattern.search(html, header_match.end())
    section_end = hr_match.start() if hr_match is not None else len(html)

    return section_start, section_end


def patch_derived_values_for_dish(
    html: str, dish_name: str, recipe: Recipe, ingredient_name: str | None = None
) -> str:
    """
    Forces this dish's Portion cost and Gross margin, and (if
    `ingredient_name` is given) that ingredient's own Unit Cost and Line
    Cost, to match recipe_costing.py's actual computed values for
    `recipe` — the CURRENT, already-recosted Recipe object, not the
    original.

    Scoped strictly to this dish's own section (see _find_dish_section),
    AND every substitution below is additionally capped at count=1, so
    even an imperfect section boundary can never patch more than one
    dish's line (see module docstring, Bug 3).
    """
    start, end = _find_dish_section(html, dish_name)
    section = html[start:end]

    correct_portion_cost = _money(portion_cost(recipe))
    correct_margin = _pct(gross_margin(recipe))

    section, portion_count = re.subn(
        r"(<strong>Portion cost:</strong>\s*)\$[\d,]+\.\d{2}",
        lambda m: m.group(1) + correct_portion_cost,
        section,
        count=1,
    )
    if portion_count == 0:
        raise RuntimeError(f"value_patch: could not find a 'Portion cost' line in {dish_name!r}'s section.")

    section, margin_count = re.subn(
        r"(<strong>Gross margin:</strong>\s*)[\d.]+%",
        lambda m: m.group(1) + correct_margin,
        section,
        count=1,
    )
    if margin_count == 0:
        raise RuntimeError(f"value_patch: could not find a 'Gross margin' line in {dish_name!r}'s section.")

    if ingredient_name is not None:
        matching = [i for i in recipe.ingredients if i.name == ingredient_name]
        if not matching:
            raise RuntimeError(
                f"value_patch: {dish_name!r}'s recipe has no ingredient named {ingredient_name!r}."
            )
        ingredient = matching[0]
        correct_unit_cost = _money(ingredient.unit_cost)
        correct_line_cost = _money(ingredient_line_cost(ingredient))

        # Unit Cost is the FIRST money-formatted <td> after the
        # ingredient's own name/qty cells (table columns are Ingredient
        # | Qty | Unit Cost | Yield | Line Cost) — matched narrowly, one
        # cell only, so this can never accidentally also match Line
        # Cost (the LAST money cell in the row, patched separately
        # below).
        unit_cost_pattern = re.compile(
            rf"(<td>{re.escape(ingredient_name)}</td>\s*<td>[^<]*</td>\s*<td>)\$[\d,]+\.\d{{2}}(</td>)"
        )
        section, unit_cost_count = unit_cost_pattern.subn(
            lambda m: m.group(1) + correct_unit_cost + m.group(2), section, count=1
        )
        if unit_cost_count == 0:
            raise RuntimeError(
                f"value_patch: could not locate {ingredient_name!r}'s Unit Cost cell in "
                f"{dish_name!r}'s section to patch it."
            )

        row_pattern = re.compile(
            rf"(<td>{re.escape(ingredient_name)}</td>.*?<td>)\$[\d,]+\.\d{{2}}(</td>\s*</tr>)",
            re.DOTALL,
        )
        section, row_count = row_pattern.subn(
            lambda m: m.group(1) + correct_line_cost + m.group(2), section, count=1
        )
        if row_count == 0:
            raise RuntimeError(
                f"value_patch: could not locate {ingredient_name!r}'s ingredient row in "
                f"{dish_name!r}'s section to patch its Line Cost."
            )

    return html[:start] + section + html[end:]


def patch_all_affected_dishes(
    html: str,
    updated_recipes: tuple[Recipe, ...],
    affected_dish_names: list[str],
    ingredient_name: str,
) -> str:
    """
    Applies patch_derived_values_for_dish for every dish named in
    affected_dish_names, using the matching (already re-costed) Recipe
    from updated_recipes. This is the function run_build1.py calls
    right after verify_and_get_final_html, before export.
    """
    by_name = {r.dish_name: r for r in updated_recipes}
    for dish_name in affected_dish_names:
        recipe = by_name.get(dish_name)
        if recipe is None:
            raise RuntimeError(f"value_patch: {dish_name!r} not found in updated_recipes.")
        html = patch_derived_values_for_dish(html, dish_name, recipe, ingredient_name=ingredient_name)
    return html