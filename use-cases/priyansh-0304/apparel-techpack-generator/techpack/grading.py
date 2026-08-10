"""Deterministic size grading — the AI never touches these numbers."""

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]


def grade_measurement(base_value: float, grade_rule: float, base_size: str, target_size: str) -> float:
    steps = SIZE_ORDER.index(target_size) - SIZE_ORDER.index(base_size)
    return round(base_value + (grade_rule * steps), 3)


def build_graded_spec(style: dict) -> dict:
    """Returns {point_name: {size: value}} for every measurement point in the style."""
    base_size = style["base_size"]
    table = {}
    for point in style["measurement_points"]:
        table[point["point_name"]] = {
            size: grade_measurement(point["base_value"], point["grade_rule"], base_size, size)
            for size in style["size_range"]
        }
    return table