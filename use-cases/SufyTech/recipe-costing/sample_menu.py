"""
sample_menu.py — a realistic small-bistro menu used to demonstrate Build 1.

Deliberately built so a single-ingredient price shock (olive oil) hits SOME
dishes and not others: Margherita Pizza, Caesar Salad, and Grilled Salmon
use it; the Cheeseburger and Truffle Fries do not. This is what lets the
re-cost pass prove "only affected lines touched" against a real,
non-trivial menu rather than a toy example.

Truffle Fries is deliberately costed close to its target margin so it can
plausibly land in the exceptions report on its own, independent of the
olive oil scenario — a realistic exceptions report should already have at
least one entry before any price shock, not only after one.
"""

from recipe_costing import Ingredient, Recipe

CHEESEBURGER = Recipe(
    dish_name="Classic Cheeseburger",
    sell_price=14.00,
    target_margin=0.68,
    plating_note="Toasted brioche bun, sauce on both halves, patty cut on the diagonal, pickle spear on the side.",
    ingredients=(
        Ingredient("Ground beef patty", 6.0, "oz", 0.28, yield_pct=0.97),
        Ingredient("Brioche bun", 1.0, "each", 0.45),
        Ingredient("Cheddar cheese", 1.0, "oz", 0.35),
        Ingredient("Lettuce", 0.5, "oz", 0.08, yield_pct=0.85),
        Ingredient("Tomato", 1.0, "oz", 0.12, yield_pct=0.90),
        Ingredient("Special sauce", 0.5, "oz", 0.20),
    ),
)

MARGHERITA_PIZZA = Recipe(
    dish_name="Margherita Pizza",
    sell_price=16.00,
    target_margin=0.70,
    plating_note="Basil leaves placed after the bake, drizzle of olive oil, flaky salt, sliced tableside.",
    ingredients=(
        Ingredient("Pizza dough", 8.0, "oz", 0.09),
        Ingredient("San Marzano tomato sauce", 3.0, "oz", 0.15),
        Ingredient("Fresh mozzarella", 4.0, "oz", 0.32, yield_pct=0.95),
        Ingredient("Fresh basil", 0.25, "oz", 1.20, yield_pct=0.90),
        Ingredient("Olive oil", 0.5, "oz", 0.45),
    ),
)

CAESAR_SALAD = Recipe(
    dish_name="Caesar Salad",
    sell_price=12.00,
    target_margin=0.72,
    plating_note="Whole leaves stacked, not chopped; shaved parmesan over the top; croutons scattered last so they stay crisp.",
    ingredients=(
        Ingredient("Romaine lettuce", 5.0, "oz", 0.18, yield_pct=0.80),
        Ingredient("Parmesan cheese", 1.0, "oz", 0.55),
        Ingredient("Croutons", 1.0, "oz", 0.20),
        Ingredient("Olive oil", 1.0, "oz", 0.45),
        Ingredient("Anchovy paste", 0.15, "oz", 1.80),
        Ingredient("Garlic", 0.10, "oz", 0.30),
        Ingredient("Lemon juice", 0.30, "oz", 0.25),
        Ingredient("Egg yolk", 0.30, "oz", 0.15),
    ),
)

GRILLED_SALMON = Recipe(
    dish_name="Grilled Salmon",
    sell_price=24.00,
    target_margin=0.65,
    plating_note="Skin-side up, asparagus fanned to the left, herb butter melting on top at pass.",
    ingredients=(
        Ingredient("Salmon fillet", 7.0, "oz", 0.85, yield_pct=0.95),
        Ingredient("Olive oil", 0.4, "oz", 0.45),
        Ingredient("Asparagus", 4.0, "oz", 0.22, yield_pct=0.88),
        Ingredient("Lemon", 0.5, "each", 0.40),
        Ingredient("Herb butter", 0.5, "oz", 0.60),
    ),
)

TRUFFLE_FRIES = Recipe(
    dish_name="Truffle Fries",
    sell_price=9.00,
    target_margin=0.65,
    plating_note="Tossed tableside in truffle oil and parmesan, parsley last so it doesn't wilt in the heat.",
    ingredients=(
        Ingredient("Potatoes", 8.0, "oz", 0.06, yield_pct=0.90),
        Ingredient("Truffle oil", 0.3, "oz", 2.50),
        Ingredient("Parmesan cheese", 0.5, "oz", 0.55),
        Ingredient("Parsley", 0.1, "oz", 0.90, yield_pct=0.85),
    ),
)

MENU = (CHEESEBURGER, MARGHERITA_PIZZA, CAESAR_SALAD, GRILLED_SALMON, TRUFFLE_FRIES)
