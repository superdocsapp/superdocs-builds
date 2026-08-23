"""
Proves value_patch.py fixes the real bug found on a live run: after the
export-staleness fix (verify_and_get_final_html) was confirmed working -
Unit Cost genuinely updated to the new price in all 3 affected dishes -
a closer inspection of the actual exported .docx found the DERIVED
numbers (an affected ingredient's Line Cost, each dish's Portion cost,
Gross margin) were stale or inconsistent in the AI's own approved edit.

test_patch_derived_values_for_dish_fixes_the_exact_live_bug_scenario IS
the regression test - it reproduces the exact shape of the bug found
(Unit Cost correct, everything derived from it still showing the OLD
values) and proves the fix forces every derived number to the correct,
recipe_costing.py-computed value.

All pure-Python, zero network, zero LLM calls.
"""

from __future__ import annotations

import pytest

from document_builder import build_menu_costing_document_html
from recipe_costing import apply_price_change, gross_margin, ingredient_line_cost, portion_cost
from sample_menu import MENU
from value_patch import patch_all_affected_dishes, patch_derived_values_for_dish


def test_patch_derived_values_for_dish_fixes_the_exact_live_bug_scenario():
    """
    THE REGRESSION TEST. Builds html the same way the ORIGINAL (pre-
    price-change) document was built, then - exactly like the live bug -
    only patches the Unit Cost cell for Olive oil in Caesar Salad's
    section to the new price, leaving Portion cost, Gross margin, and
    Olive oil's own Line Cost all still showing the OLD values. Proves
    patch_derived_values_for_dish forces all three to the correct,
    freshly-computed values.
    """
    original_html = build_menu_costing_document_html(MENU, title="Bistro Menu Costing Sheet")

    # Simulate exactly what the live bug looked like: only the Unit Cost
    # cell got updated by the AI's edit, nothing derived from it did.
    stale_html = original_html.replace(
        "<td>Olive oil</td><td>1 oz</td><td>$0.45</td><td>100.0%</td><td>$0.45</td>",
        "<td>Olive oil</td><td>1 oz</td><td>$1.35</td><td>100.0%</td><td>$0.45</td>",
        1,
    )
    assert stale_html != original_html, "test setup sanity check: the replace must have actually matched"

    recost_result = apply_price_change(MENU, "Olive oil", 1.35)
    caesar_updated = next(r for r in recost_result["updated_recipes"] if r.dish_name == "Caesar Salad")

    patched_html = patch_derived_values_for_dish(
        stale_html, "Caesar Salad", caesar_updated, ingredient_name="Olive oil"
    )

    correct_portion_cost_text = f"${portion_cost(caesar_updated):,.2f}"
    correct_margin_text = f"{gross_margin(caesar_updated) * 100:.1f}%"
    olive_oil_ing = next(i for i in caesar_updated.ingredients if i.name == "Olive oil")
    correct_line_cost_text = f"${ingredient_line_cost(olive_oil_ing):,.2f}"

    assert f"<strong>Portion cost:</strong> {correct_portion_cost_text}" in patched_html
    assert f"<strong>Gross margin:</strong> {correct_margin_text}" in patched_html
    # The Olive oil row's Line Cost (last <td> in that row) must now be correct.
    assert (
        f"<td>Olive oil</td><td>1 oz</td><td>$1.35</td><td>100.0%</td><td>{correct_line_cost_text}</td>"
        in patched_html
    )


def test_patch_derived_values_for_dish_never_touches_other_dishes_sections():
    original_html = build_menu_costing_document_html(MENU, title="Bistro Menu Costing Sheet")
    recost_result = apply_price_change(MENU, "Olive oil", 1.35)
    caesar_updated = next(r for r in recost_result["updated_recipes"] if r.dish_name == "Caesar Salad")

    patched_html = patch_derived_values_for_dish(
        original_html, "Caesar Salad", caesar_updated, ingredient_name="Olive oil"
    )

    # An unaffected dish's section (no olive oil) must be byte-identical
    # before and after - scoped patching, never a global find/replace.
    cheeseburger_section_before = original_html[
        original_html.index("<h2>Classic Cheeseburger</h2>") : original_html.index("<hr/>")
    ]
    cheeseburger_section_after = patched_html[
        patched_html.index("<h2>Classic Cheeseburger</h2>") : patched_html.index("<hr/>")
    ]
    assert cheeseburger_section_before == cheeseburger_section_after


def test_patch_derived_values_for_dish_raises_loudly_when_dish_not_found():
    html = "<div><h2>Some Other Dish</h2></div>"
    recost_result = apply_price_change(MENU, "Olive oil", 1.35)
    caesar_updated = next(r for r in recost_result["updated_recipes"] if r.dish_name == "Caesar Salad")

    with pytest.raises(RuntimeError, match="Caesar Salad"):
        patch_derived_values_for_dish(html, "Caesar Salad", caesar_updated, ingredient_name="Olive oil")


def test_patch_derived_values_for_dish_raises_loudly_when_portion_cost_line_missing():
    html = "<div><h2>Caesar Salad</h2><p>No portion cost line here.</p></div>"
    recost_result = apply_price_change(MENU, "Olive oil", 1.35)
    caesar_updated = next(r for r in recost_result["updated_recipes"] if r.dish_name == "Caesar Salad")

    with pytest.raises(RuntimeError, match="Portion cost"):
        patch_derived_values_for_dish(html, "Caesar Salad", caesar_updated, ingredient_name="Olive oil")


def test_patch_derived_values_for_dish_raises_loudly_when_ingredient_row_missing():
    html = (
        "<div><h2>Caesar Salad</h2>"
        "<p><strong>Portion cost:</strong> $2.74</p>"
        "<p><strong>Gross margin:</strong> 77.1%</p>"
        "</div>"
    )
    recost_result = apply_price_change(MENU, "Olive oil", 1.35)
    caesar_updated = next(r for r in recost_result["updated_recipes"] if r.dish_name == "Caesar Salad")

    with pytest.raises(RuntimeError, match="Olive oil"):
        patch_derived_values_for_dish(html, "Caesar Salad", caesar_updated, ingredient_name="Olive oil")


def test_patch_all_affected_dishes_patches_every_affected_dish():
    original_html = build_menu_costing_document_html(MENU, title="Bistro Menu Costing Sheet")
    recost_result = apply_price_change(MENU, "Olive oil", 1.35)

    patched_html = patch_all_affected_dishes(
        original_html,
        updated_recipes=recost_result["updated_recipes"],
        affected_dish_names=recost_result["affected_dish_names"],
        ingredient_name="Olive oil",
    )

    for dish_name in recost_result["affected_dish_names"]:
        recipe = next(r for r in recost_result["updated_recipes"] if r.dish_name == dish_name)
        correct_margin_text = f"{gross_margin(recipe) * 100:.1f}%"
        assert correct_margin_text in patched_html


def test_patch_all_affected_dishes_raises_if_a_named_dish_is_missing_from_updated_recipes():
    original_html = build_menu_costing_document_html(MENU, title="Bistro Menu Costing Sheet")
    recost_result = apply_price_change(MENU, "Olive oil", 1.35)

    with pytest.raises(RuntimeError, match="Nonexistent Dish"):
        patch_all_affected_dishes(
            original_html,
            updated_recipes=recost_result["updated_recipes"],
            affected_dish_names=["Nonexistent Dish"],
            ingredient_name="Olive oil",
        )
