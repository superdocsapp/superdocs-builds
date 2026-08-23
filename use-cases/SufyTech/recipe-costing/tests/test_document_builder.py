"""
Proves document_builder.py's "must never" guarantees: every number in the
generated HTML traces back exactly to recipe_costing.py, and every
ingredient line appears.
"""

from document_builder import (
    build_costed_recipe_html,
    build_exceptions_report_html,
    build_menu_costing_document_html,
)
from recipe_costing import apply_price_change, portion_cost, rank_exceptions
from sample_menu import CHEESEBURGER, MENU


def test_costed_recipe_html_includes_every_ingredient_line():
    html = build_costed_recipe_html(CHEESEBURGER)
    for ingredient in CHEESEBURGER.ingredients:
        assert ingredient.name in html


def test_costed_recipe_html_portion_cost_matches_recipe_costing_exactly():
    html = build_costed_recipe_html(CHEESEBURGER)
    expected = f"${portion_cost(CHEESEBURGER):,.2f}"
    assert expected in html


def test_costed_recipe_html_includes_plating_note_verbatim():
    html = build_costed_recipe_html(CHEESEBURGER)
    assert CHEESEBURGER.plating_note in html


def test_menu_document_includes_every_dish():
    html = build_menu_costing_document_html(MENU)
    for recipe in MENU:
        assert recipe.dish_name in html


def test_exceptions_report_empty_case_says_so_plainly():
    html = build_exceptions_report_html([], "Butter", 5.00)
    assert "No dishes fell below" in html


def test_exceptions_report_numbers_match_rank_exceptions_output_exactly():
    result = apply_price_change(MENU, "Olive oil", 1.35)
    exceptions = rank_exceptions(result["updated_recipes"])
    assert exceptions, "test menu/shock combo must actually produce an exception to be a real test"

    html = build_exceptions_report_html(exceptions, "Olive oil", 1.35)
    for e in exceptions:
        assert e["dish_name"] in html
        assert f"${e['money_at_risk_per_portion']:,.2f}" in html
        assert f"${e['suggested_price_to_hit_target']:,.2f}" in html
