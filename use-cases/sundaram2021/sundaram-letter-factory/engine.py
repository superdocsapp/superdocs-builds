"""Deterministic core of the letter factory.

Nothing in this module talks to a network or to a model. Figures are computed
from data/rules.json, records are checked against the check definitions in that
same file, and letters are assembled by literal placeholder substitution into
approved wording blocks. Everything here is reproducible from the data files.
"""

import json
import os
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

PLACEHOLDER_RE = re.compile(r"\{\{([a-z_]+)\}\}")

# Only names, digits, decimal points, arithmetic operators and parentheses are
# allowed through to eval, so a formula in the data file can never smuggle code in.
SAFE_EXPRESSION_RE = re.compile(r"^[a-z_0-9\s\.\+\-\*/\(\)]+$")


class DataError(Exception):
    pass


def load_data(data_dir=DATA_DIR):
    with open(os.path.join(data_dir, "rules.json")) as fh:
        rules = json.load(fh)
    with open(os.path.join(data_dir, "wording_blocks.json")) as fh:
        blocks = json.load(fh)["blocks"]
    with open(os.path.join(data_dir, "customers.json")) as fh:
        records = json.load(fh)["records"]
    return rules, blocks, records


def format_money(cents, rules, language):
    fmt = rules["formats"].get(language) or rules["formats"]["en"]
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    grouped = "{:,}".format(whole).replace(",", fmt["thousands_separator"])
    body = grouped + fmt["decimal_separator"] + "{:02d}".format(frac)
    return sign + fmt["money"].format(symbol=rules["currency"]["symbol"], grouped=body)


def format_date(iso_date, rules, language):
    if not iso_date:
        return ""
    fmt = rules["formats"].get(language) or rules["formats"]["en"]
    parsed = date.fromisoformat(iso_date)
    return fmt["date"].format(
        month_name=fmt["months"][parsed.month - 1],
        day=parsed.day,
        year=parsed.year,
    )


def format_percent(basis_points):
    value = Decimal(basis_points) / Decimal(100)
    text = str(value.normalize())
    if "E" in text:
        text = str(value.quantize(Decimal("1")))
    return text + "%"


def _round(value, mode):
    if mode == "half_up_to_cent":
        return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return Decimal(value)


def compute_figures(record, rules):
    """Run the formula in rules.json step by step.

    Returns (values, trail). The trail is the audit line for every step, so the
    arithmetic behind any number in a letter can be replayed by hand.
    """
    juris = rules["jurisdictions"][record["jurisdiction"]]
    values = {}
    trail = []

    for step in rules["formula"]["steps"]:
        name = step["name"]
        kind = step["kind"]

        if kind == "field":
            values[name] = Decimal(record[step["field"]])
            trail.append("{0} = {1} cents, taken from record field '{2}' ({3})".format(
                name, values[name], step["field"], step["label"]))

        elif kind == "days_between":
            start = date.fromisoformat(record[step["from_field"]])
            end = date.fromisoformat(record[step["to_field"]])
            values[name] = Decimal((end - start).days)
            trail.append("{0} = {1} ({2} to {3}, {4})".format(
                name, values[name], start.isoformat(), end.isoformat(), step["label"]))

        elif kind == "jurisdiction_param":
            values[name] = Decimal(juris[step["param"]])
            trail.append("{0} = {1}, from jurisdiction '{2}' ({3})".format(
                name, values[name], record["jurisdiction"], step["label"]))

        elif kind == "arithmetic":
            expression = step["expression"]
            if not SAFE_EXPRESSION_RE.match(expression):
                raise DataError("unsafe formula expression: " + expression)
            unknown = [token for token in re.findall(r"[a-z_][a-z_0-9]*", expression)
                       if token not in values]
            if unknown:
                raise DataError("formula step '{0}' uses undefined names: {1}".format(
                    name, ", ".join(unknown)))
            raw = eval(expression, {"__builtins__": {}}, dict(values))
            values[name] = _round(raw, step.get("round"))
            substituted = expression
            for token in sorted(values, key=len, reverse=True):
                if token != name:
                    substituted = re.sub(r"\b" + token + r"\b", str(values[token]), substituted)
            trail.append("{0} = {1} = {2} = {3} cents ({4})".format(
                name, expression, substituted, values[name], step["label"]))

        else:
            raise DataError("unknown formula step kind: " + kind)

    return values, trail


def _reason_context(record, rules, values, check):
    language = record.get("language") or "en"
    ctx = {}
    for key, value in record.items():
        ctx[key] = "(missing)" if value is None else value
        if key.endswith("_cents") and isinstance(value, int):
            ctx[key + "_money"] = format_money(value, rules, "en")
    for key, value in (values or {}).items():
        ctx[key] = value
        if key.endswith("_cents"):
            ctx[key + "_money"] = format_money(int(value), rules, "en")
    if isinstance(check.get("right"), int):
        ctx["right_money"] = format_money(check["right"], rules, "en")
    ctx["language"] = language
    return ctx


class _Blanks(dict):
    def __missing__(self, key):
        return "(unknown)"


def _fill_reason(check, record, rules, values):
    ctx = _Blanks(_reason_context(record, rules, values, check))
    if check["kind"] == "formula_match" and values:
        stated = record.get(check["field"])
        computed = int(values[check["computed"]])
        if isinstance(stated, int):
            ctx["formula_difference_money"] = format_money(abs(stated - computed), rules, "en")
    return check["reason"].format_map(ctx)


def find_block(blocks, jurisdiction, stage, language):
    for block in blocks:
        if (block["jurisdiction"] == jurisdiction
                and block["stage"] == stage
                and block["language"] == language):
            return block
    return None


def run_checks(record, rules, blocks, values, stage):
    """Evaluate every check defined for this stage. Returns a list of failures."""
    failures = []
    for check in rules["checks"]:
        if check["stage"] != stage:
            continue
        kind = check["kind"]
        failed = False

        if kind == "required":
            value = record.get(check["field"])
            failed = value is None or (isinstance(value, str) and not value.strip())

        elif kind == "in_config":
            failed = record.get(check["field"]) not in rules[check["config"]]

        elif kind == "compare":
            left = record.get(check["left"])
            if left is None and values:
                left = values.get(check["left"])
            if left is None:
                failed = False
            else:
                left = Decimal(left)
                right = Decimal(check["right"])
                ops = {">": left > right, ">=": left >= right, "<": left < right,
                       "<=": left <= right, "==": left == right}
                if check["op"] not in ops:
                    raise DataError("unknown compare op: " + check["op"])
                failed = not ops[check["op"]]

        elif kind == "date_order":
            earlier = record.get(check["earlier_field"])
            later = record.get(check["later_field"])
            if earlier and later:
                failed = date.fromisoformat(earlier) > date.fromisoformat(later)

        elif kind == "formula_match":
            stated = record.get(check["field"])
            if stated is None:
                failed = True
            else:
                failed = Decimal(stated) != values[check["computed"]]

        elif kind == "wording_block_exists":
            failed = find_block(blocks, record.get("jurisdiction"),
                                record.get("stage"), record.get("language")) is None

        else:
            raise DataError("unknown check kind: " + kind)

        if failed:
            failures.append({
                "check_id": check["id"],
                "reason": _fill_reason(check, record, rules, values),
            })
    return failures


def placeholder_values(record, rules, values):
    language = record["language"]
    juris = rules["jurisdictions"][record["jurisdiction"]]
    return {
        "customer_name": record["customer_name"],
        "account_number": record["account_number"],
        "notice_date": format_date(record["notice_date"], rules, language),
        "overcharge_start_date": format_date(record["overcharge_start_date"], rules, language),
        "overcharge_amount": format_money(int(values["overcharge_cents"]), rules, language),
        "interest_amount": format_money(int(values["interest_cents"]), rules, language),
        "refund_amount": format_money(int(values["refund_cents"]), rules, language),
        "accrual_days": str(int(values["accrual_days"])),
        "annual_rate_percent": format_percent(juris["interest_rate_bps"]),
        "response_window_days": str(juris["response_window_days"]),
        "regulator": juris["regulator"],
    }


def assemble(block, fills):
    """Substitute placeholders into approved wording. Wording itself is untouched."""
    sections = []
    for section in block["sections"]:
        approved = section["text"]
        needed = PLACEHOLDER_RE.findall(approved)
        missing = [name for name in needed if fills.get(name) in (None, "")]
        if missing:
            raise DataError("no value for placeholders {0} in section '{1}'".format(
                ", ".join(missing), section["id"]))
        filled = PLACEHOLDER_RE.sub(lambda m: str(fills[m.group(1)]), approved)
        sections.append({
            "id": section["id"],
            "tag": section["tag"],
            "approved_text": approved,
            "text": filled,
            "has_placeholders": bool(needed),
            "placeholders": needed,
        })
    return sections


def prepare(record, rules, blocks):
    """Take one raw record to either a ready letter or a held record with reasons.

    Pre-calculation checks run before any arithmetic, so a record with a missing
    date or an unknown jurisdiction is held rather than crashing the formula.
    """
    failures = run_checks(record, rules, blocks, None, "pre_calculation")
    if failures:
        return {"status": "held", "record": record, "failures": failures, "values": None}

    values, trail = compute_figures(record, rules)
    failures = run_checks(record, rules, blocks, values, "post_calculation")
    if failures:
        return {"status": "held", "record": record, "failures": failures,
                "values": values, "trail": trail}

    block = find_block(blocks, record["jurisdiction"], record["stage"], record["language"])
    fills = placeholder_values(record, rules, values)
    sections = assemble(block, fills)
    return {
        "status": "ready",
        "record": record,
        "values": values,
        "trail": trail,
        "block": block,
        "fills": fills,
        "sections": sections,
        "variant": variant_key(record),
    }


def variant_key(record):
    return "{0}_{1}_{2}".format(record["jurisdiction"], record["stage"], record["language"])


def prepare_all(records, rules, blocks, sample=None):
    """Prepare records in file order, skipping any customer_id already seen."""
    prepared = []
    seen = set()
    for record in records:
        if record["customer_id"] in seen:
            continue
        seen.add(record["customer_id"])
        prepared.append(prepare(record, rules, blocks))
        if sample and len(prepared) >= sample:
            break
    return prepared
