"""
recipe_costing.py — deterministic cost/margin arithmetic for Build 1
(Recipe Costing & Re-Cost Pass).

Every number a human or SuperDocs document will ever display comes from
THIS module, never from an LLM. Omkar's own spec for this build says
"Strong = arithmetic stays consistent, only affected lines touched" —
that's a claim about code correctness, not writing quality, so the math
lives here where it can be pinned down with real tests
(tests/test_recipe_costing.py), and SuperDocs is used only for what it's
actually good at: turning these numbers into a formatted, editable
document and making targeted edits to it.

What this must never do:
  - never divide by a zero or negative yield percentage (a bad yield
    number should raise loudly, not silently produce inf/nan that looks
    like a real cost on a document)
  - never let a price change touch a recipe that doesn't contain the
    changed ingredient — the whole point of "only affected lines
    touched"
  - never rank the exceptions report by margin PERCENTAGE — Omkar's
    spec explicitly asks for ranking by money at risk (dollars), since
    a high-volume dish 2 points under target margin can matter far more
    than a low-volume dish 20 points under
  - never mutate a Recipe/Ingredient in place — apply_price_change
    returns NEW objects, so the caller always has an unambiguous
    "before" snapshot to diff against, which is what proves isolation
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class Ingredient:
    name: str
    quantity: float          # amount used in this recipe, in `unit`
    unit: str                # "oz", "each", "lb", etc. — for the document only
    unit_cost: float         # cost per `unit` of the RAW ingredient, before yield loss
    yield_pct: float = 1.0   # e.g. 0.90 = 10% trim/waste loss between raw and usable


@dataclass(frozen=True)
class Recipe:
    dish_name: str
    ingredients: tuple[Ingredient, ...]
    sell_price: float
    target_margin: float     # e.g. 0.65 = 65% target gross margin
    plating_note: str


def ingredient_line_cost(ingredient: Ingredient) -> float:
    """
    Cost contribution of one ingredient line, accounting for yield/waste:
    raw cost of the quantity used, inflated by how much of the raw
    quantity is actually usable after trim/waste.
    """
    if ingredient.yield_pct <= 0:
        raise ValueError(
            f"yield_pct must be > 0 for '{ingredient.name}', got {ingredient.yield_pct}"
        )
    return (ingredient.quantity * ingredient.unit_cost) / ingredient.yield_pct


def portion_cost(recipe: Recipe) -> float:
    """Total ingredient cost for one plated portion of this dish."""
    return sum(ingredient_line_cost(i) for i in recipe.ingredients)


def gross_margin(recipe: Recipe) -> float:
    """
    Gross margin as a fraction (0.65 = 65%), computed from sell_price and
    the current portion_cost.
    """
    if recipe.sell_price <= 0:
        raise ValueError(f"sell_price must be > 0 for '{recipe.dish_name}'")
    return (recipe.sell_price - portion_cost(recipe)) / recipe.sell_price


def money_at_risk(recipe: Recipe) -> float:
    """
    Dollar shortfall PER PORTION versus this recipe's own target margin —
    0.0 if the recipe is already at or above target. This is what the
    exceptions report ranks by (see rank_exceptions below), per Omkar's
    explicit instruction to rank by money at risk, not percentage.
    """
    cost_ceiling_for_target = recipe.sell_price * (1 - recipe.target_margin)
    shortfall = portion_cost(recipe) - cost_ceiling_for_target
    return max(0.0, shortfall)


def is_below_target(recipe: Recipe) -> bool:
    return gross_margin(recipe) < recipe.target_margin


def apply_price_change(
    recipes: tuple[Recipe, ...], ingredient_name: str, new_unit_cost: float
) -> dict:
    """
    Simulates a bulk supplier price change for one ingredient across every
    recipe in `recipes`. Returns brand-NEW Recipe objects (originals are
    never mutated — Recipe/Ingredient are frozen dataclasses, so mutation
    isn't even possible by accident).

    Returns:
      {
        "updated_recipes": tuple[Recipe, ...],   # new objects, same order as input
        "affected_dish_names": list[str],        # recipes that contained the ingredient
        "line_changes": list[dict],               # one entry per changed ingredient line
      }

    A recipe that doesn't contain `ingredient_name` comes back as the
    EXACT SAME Recipe object (not a copy) — proven directly in
    test_recipe_costing.py via `is` identity, the strongest possible
    proof that an unaffected recipe was never touched.
    """
    updated_recipes = []
    affected_dish_names = []
    line_changes = []

    for recipe in recipes:
        contains_ingredient = any(i.name == ingredient_name for i in recipe.ingredients)

        if not contains_ingredient:
            updated_recipes.append(recipe)  # same object, untouched
            continue

        old_portion_cost = portion_cost(recipe)
        old_margin = gross_margin(recipe)

        new_ingredients = tuple(
            replace(ing, unit_cost=new_unit_cost) if ing.name == ingredient_name else ing
            for ing in recipe.ingredients
        )
        new_recipe = replace(recipe, ingredients=new_ingredients)

        new_portion_cost = portion_cost(new_recipe)
        new_margin = gross_margin(new_recipe)

        updated_recipes.append(new_recipe)
        affected_dish_names.append(recipe.dish_name)
        line_changes.append(
            {
                "dish_name": recipe.dish_name,
                "ingredient": ingredient_name,
                "old_portion_cost": round(old_portion_cost, 4),
                "new_portion_cost": round(new_portion_cost, 4),
                "cost_delta": round(new_portion_cost - old_portion_cost, 4),
                "old_margin": round(old_margin, 4),
                "new_margin": round(new_margin, 4),
                "margin_delta": round(new_margin - old_margin, 4),
            }
        )

    return {
        "updated_recipes": tuple(updated_recipes),
        "affected_dish_names": affected_dish_names,
        "line_changes": line_changes,
    }


def rank_exceptions(recipes: tuple[Recipe, ...]) -> list[dict]:
    """
    Every recipe currently below its own target margin, ranked by MONEY
    AT RISK (dollars per portion short of target), highest risk first —
    per Omkar's spec: "ranked by money at risk not percentage". A recipe
    at or above its target margin never appears in this list.

    BUG FIXED, logged honestly: this previously stored "portion_cost"
    and "current_margin" pre-rounded to 4 decimal places. build_exceptions_
    report_html then rounds those already-rounded values again to 2
    decimals for display (_money/_pct). Because portion_cost's raw float
    can land right on a rounding boundary (e.g. 3.6449999999999996),
    rounding it to 4dp first (3.645) and then to 2dp again (3.65) can
    disagree with rounding the raw value directly to 2dp (3.64) — a
    double-rounding bug that showed up as the menu document and the
    exceptions report disagreeing on the same dish's Portion cost by a
    cent, even though both ultimately call portion_cost() on the same
    Recipe. Fixed by storing the RAW (unrounded) float here and letting
    the single _money()/_pct() call at display time do the only
    rounding — same "round exactly once, at display time" discipline
    document_builder.py already follows.
    """
    exceptions = []
    for recipe in recipes:
        risk = money_at_risk(recipe)
        if risk > 0:
            exceptions.append(
                {
                    "dish_name": recipe.dish_name,
                    "portion_cost": portion_cost(recipe),
                    "sell_price": recipe.sell_price,
                    "current_margin": gross_margin(recipe),
                    "target_margin": recipe.target_margin,
                    "money_at_risk_per_portion": round(risk, 4),
                    "suggested_price_to_hit_target": round(
                        portion_cost(recipe) / (1 - recipe.target_margin), 2
                    ),
                }
            )
    exceptions.sort(key=lambda e: e["money_at_risk_per_portion"], reverse=True)
    return exceptions