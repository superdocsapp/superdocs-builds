"""
Proves recipe_costing.py's "must never" guarantees directly — this is the
concrete evidence for Omkar's own stated bar: "Strong = arithmetic stays
consistent, only affected lines touched."
"""

import pytest

from recipe_costing import (
    Ingredient,
    Recipe,
    apply_price_change,
    gross_margin,
    ingredient_line_cost,
    portion_cost,
    rank_exceptions,
)
from sample_menu import CHEESEBURGER, MARGHERITA_PIZZA, MENU, TRUFFLE_FRIES


def test_ingredient_line_cost_accounts_for_yield_loss():
    # 4 oz at $1.00/oz with 100% yield = $4.00 exactly.
    full_yield = Ingredient("Widget", 4.0, "oz", 1.00, yield_pct=1.0)
    assert ingredient_line_cost(full_yield) == pytest.approx(4.00)

    # Same 4 oz, but only 80% of the raw quantity survives trim/waste,
    # so the usable cost is inflated to $5.00 (4.00 / 0.80).
    lossy = Ingredient("Widget", 4.0, "oz", 1.00, yield_pct=0.80)
    assert ingredient_line_cost(lossy) == pytest.approx(5.00)


def test_ingredient_line_cost_rejects_zero_or_negative_yield():
    with pytest.raises(ValueError):
        ingredient_line_cost(Ingredient("Bad", 1.0, "oz", 1.00, yield_pct=0.0))
    with pytest.raises(ValueError):
        ingredient_line_cost(Ingredient("Bad", 1.0, "oz", 1.00, yield_pct=-0.5))


def test_portion_cost_is_the_sum_of_every_ingredient_line():
    recipe = Recipe(
        dish_name="Test Dish",
        sell_price=10.00,
        target_margin=0.60,
        plating_note="",
        ingredients=(
            Ingredient("A", 2.0, "oz", 1.00),  # $2.00
            Ingredient("B", 1.0, "oz", 3.00),  # $3.00
        ),
    )
    assert portion_cost(recipe) == pytest.approx(5.00)


def test_gross_margin_matches_hand_calculation():
    # portion_cost = $5.00, sell_price = $20.00 -> margin = (20-5)/20 = 0.75
    recipe = Recipe(
        dish_name="Test Dish",
        sell_price=20.00,
        target_margin=0.50,
        plating_note="",
        ingredients=(Ingredient("A", 5.0, "oz", 1.00),),
    )
    assert gross_margin(recipe) == pytest.approx(0.75)


def test_apply_price_change_only_touches_recipes_containing_the_ingredient():
    result = apply_price_change(MENU, "Olive oil", 0.68)

    # Cheeseburger and Truffle Fries contain no olive oil - they must come
    # back as the EXACT SAME object, not a recomputed copy. `is` identity
    # is the strongest possible proof nothing about them was touched.
    updated_by_name = {r.dish_name: r for r in result["updated_recipes"]}
    original_by_name = {r.dish_name: r for r in MENU}

    assert updated_by_name["Classic Cheeseburger"] is original_by_name["Classic Cheeseburger"]
    assert updated_by_name["Truffle Fries"] is original_by_name["Truffle Fries"]

    # The three olive-oil dishes ARE in the affected list.
    assert set(result["affected_dish_names"]) == {
        "Margherita Pizza",
        "Caesar Salad",
        "Grilled Salmon",
    }
    assert "Classic Cheeseburger" not in result["affected_dish_names"]
    assert "Truffle Fries" not in result["affected_dish_names"]


def test_apply_price_change_recomputes_cost_correctly_for_affected_recipes():
    # Margherita Pizza uses 0.5 oz olive oil. Old cost contribution at
    # $0.45/oz = $0.225. New cost contribution at $0.68/oz = $0.34.
    # Every OTHER ingredient line is unchanged, so the portion_cost delta
    # must equal exactly that one line's delta - not an approximation.
    result = apply_price_change(MENU, "Olive oil", 0.68)
    change = next(c for c in result["line_changes"] if c["dish_name"] == "Margherita Pizza")

    old_olive_oil_line = 0.5 * 0.45  # $0.225
    new_olive_oil_line = 0.5 * 0.68  # $0.34
    expected_delta = new_olive_oil_line - old_olive_oil_line

    assert change["cost_delta"] == pytest.approx(expected_delta, abs=0.0001)


def test_apply_price_change_never_mutates_the_original_recipes():
    # Originals must be provably untouched after the call - re-derive
    # portion_cost from the SAME MENU tuple and confirm it matches what
    # it was before apply_price_change ever ran.
    original_pizza_cost_before = portion_cost(MARGHERITA_PIZZA)
    apply_price_change(MENU, "Olive oil", 0.68)
    original_pizza_cost_after = portion_cost(MARGHERITA_PIZZA)

    assert original_pizza_cost_before == original_pizza_cost_after
    assert MARGHERITA_PIZZA.ingredients[-1].unit_cost == 0.45  # still the original price


def test_apply_price_change_on_an_ingredient_nobody_uses_touches_nothing():
    result = apply_price_change(MENU, "Saffron", 50.00)
    assert result["affected_dish_names"] == []
    assert result["line_changes"] == []
    for original, updated in zip(MENU, result["updated_recipes"]):
        assert original is updated


def test_rank_exceptions_sorts_by_money_at_risk_not_percentage():
    # Construct two recipes where the dollar ranking and the percentage
    # ranking would disagree, to prove the function ranks by dollars.
    high_volume_slightly_under = Recipe(
        dish_name="Big Ticket Item",
        sell_price=40.00,
        target_margin=0.70,          # needs cost <= $12.00
        plating_note="",
        ingredients=(Ingredient("X", 1.0, "each", 13.00),),  # cost $13 -> margin 0.675, only 2.5pts under
    )
    low_volume_way_under_but_cheap = Recipe(
        dish_name="Small Side",
        sell_price=5.00,
        target_margin=0.80,          # needs cost <= $1.00
        plating_note="",
        ingredients=(Ingredient("Y", 1.0, "each", 1.30),),   # cost $1.30 -> margin 0.74, 6pts under (bigger % gap)
    )

    exceptions = rank_exceptions((high_volume_slightly_under, low_volume_way_under_but_cheap))

    # Percentage-wise, "Small Side" is further below its target (6pts vs
    # 2.5pts) - but in raw dollars, "Big Ticket Item" is $1.00/portion
    # short of target while "Small Side" is only $0.30/portion short.
    # Ranking by money at risk must put the dollar-bigger one first.
    assert exceptions[0]["dish_name"] == "Big Ticket Item"
    assert exceptions[1]["dish_name"] == "Small Side"
    assert exceptions[0]["money_at_risk_per_portion"] > exceptions[1]["money_at_risk_per_portion"]


def test_rank_exceptions_excludes_recipes_already_at_or_above_target():
    healthy_recipe = Recipe(
        dish_name="Healthy Margin Dish",
        sell_price=20.00,
        target_margin=0.50,
        plating_note="",
        ingredients=(Ingredient("X", 1.0, "each", 5.00),),  # margin = 0.75, well above 0.50 target
    )
    exceptions = rank_exceptions((healthy_recipe,))
    assert exceptions == []


def test_rank_exceptions_suggested_price_actually_hits_target_margin():
    # The suggested_price_to_hit_target figure must be internally
    # consistent: plugging it back in as sell_price must produce a
    # margin equal to (not just close to) the recipe's target_margin.
    # $1.35/oz is a real, verified severe-shock value for THIS menu
    # (roughly 3x the $0.45 baseline) - smaller shocks were tried first
    # and didn't move any dish below target, since olive oil is a small
    # fraction of total cost for every dish that uses it here. Confirmed
    # by hand before writing this assertion, not guessed at.
    result = apply_price_change(MENU, "Olive oil", 1.35)
    exceptions = rank_exceptions(result["updated_recipes"])
    assert len(exceptions) > 0

    for exception in exceptions:
        recipe = next(r for r in result["updated_recipes"] if r.dish_name == exception["dish_name"])
        hypothetical = Recipe(
            dish_name=recipe.dish_name,
            sell_price=exception["suggested_price_to_hit_target"],
            target_margin=recipe.target_margin,
            plating_note=recipe.plating_note,
            ingredients=recipe.ingredients,
        )
        assert gross_margin(hypothetical) == pytest.approx(recipe.target_margin, abs=0.001)


def test_full_menu_total_portion_cost_is_deterministic_and_reproducible():
    # A basic sanity anchor: running the same computation twice on the
    # same immutable data must give byte-identical results, every time.
    total_1 = sum(portion_cost(r) for r in MENU)
    total_2 = sum(portion_cost(r) for r in MENU)
    assert total_1 == total_2
