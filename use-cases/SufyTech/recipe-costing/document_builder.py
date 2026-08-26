"""
document_builder.py — turns Recipe objects and costing results into the
HTML SuperDocs expects (send HTML in, get edited HTML back — see
docs.superdocs.app/concepts/documents).

This module is pure, deterministic, and fully testable without touching
the live API: given the same recipes, it always produces the same HTML.
All the NUMBERS in the output come straight from recipe_costing.py — this
module only formats them, it never computes anything itself.

What this must never do:
  - never invent or reformat a dollar figure — every number here is
    passed in from a recipe_costing.py function's return value, verbatim
    (rounded for display only, never recalculated a different way)
  - never silently drop an ingredient line — every ingredient in a
    Recipe appears as its own table row
"""

from __future__ import annotations

from recipe_costing import (
    gross_margin,
    ingredient_line_cost,
    portion_cost,
)


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_costed_recipe_html(recipe) -> str:
    """One dish's costed recipe card as HTML: ingredient lines with unit
    cost and yield, portion cost, sell price, gross margin, plating note."""
    rows = "\n".join(
        f"<tr>"
        f"<td>{ing.name}</td>"
        f"<td>{ing.quantity:g} {ing.unit}</td>"
        f"<td>{_money(ing.unit_cost)}</td>"
        f"<td>{_pct(ing.yield_pct)}</td>"
        f"<td>{_money(ingredient_line_cost(ing))}</td>"
        f"</tr>"
        for ing in recipe.ingredients
    )

    return f"""<div>
<h2>{recipe.dish_name}</h2>
<table>
<thead>
<tr><th>Ingredient</th><th>Qty</th><th>Unit Cost</th><th>Yield</th><th>Line Cost</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<p><strong>Portion cost:</strong> {_money(portion_cost(recipe))}</p>
<p><strong>Sell price:</strong> {_money(recipe.sell_price)}</p>
<p><strong>Gross margin:</strong> {_pct(gross_margin(recipe))} (target: {_pct(recipe.target_margin)})</p>
<p><strong>Plating note:</strong> {recipe.plating_note}</p>
</div>"""


def build_menu_costing_document_html(recipes, title: str = "Menu Costing Sheet") -> str:
    """Full costed-recipe document covering every dish on the menu, one
    section per dish, in menu order."""
    sections = "\n<hr/>\n".join(build_costed_recipe_html(r) for r in recipes)
    return f"<div>\n<h1>{title}</h1>\n{sections}\n</div>"


def build_exceptions_report_html(exceptions: list[dict], ingredient_changed: str, new_unit_cost: float) -> str:
    """
    Exceptions report: dishes below target margin after a price change,
    ranked by money at risk (already sorted by rank_exceptions), with a
    suggested new sell price for each.
    """
    if not exceptions:
        body = "<p>No dishes fell below their target margin after this price change.</p>"
    else:
        rows = "\n".join(
            f"<tr>"
            f"<td>{e['dish_name']}</td>"
            f"<td>{_money(e['portion_cost'])}</td>"
            f"<td>{_money(e['sell_price'])}</td>"
            f"<td>{_pct(e['current_margin'])}</td>"
            f"<td>{_pct(e['target_margin'])}</td>"
            f"<td>{_money(e['money_at_risk_per_portion'])}</td>"
            f"<td>{_money(e['suggested_price_to_hit_target'])}</td>"
            f"</tr>"
            for e in exceptions
        )
        body = f"""<table>
<thead>
<tr><th>Dish</th><th>New Portion Cost</th><th>Current Sell Price</th><th>Current Margin</th>
<th>Target Margin</th><th>Money at Risk / Portion</th><th>Suggested New Price</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>"""

    return f"""<div>
<h1>Re-Cost Exceptions Report</h1>
<p><strong>Trigger:</strong> {ingredient_changed} supplier price changed to {_money(new_unit_cost)}.</p>
<p>Dishes below target margin, ranked by dollar amount at risk per portion (highest first):</p>
{body}
</div>"""
