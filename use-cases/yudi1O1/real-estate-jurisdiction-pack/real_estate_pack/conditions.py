"""Applicability predicates for disclosure rules — evaluated in three states.

A disclosure rule usually applies only to some properties: lead paint to pre-1978
housing, sprinkler notices to New York leases, radon to Florida rentals over 45
days. Each rule carries an `applies_when` condition expressed in YAML, and this
module decides whether it fires.

**The one rule this module exists to enforce:**

    An applicability question that cannot be answered is UNDETERMINED,
    never False.

Two-state logic would be a compliance bug wearing the costume of a default. If
`year_built` is missing and the engine quietly answers "no", the federal
lead-paint disclosure silently drops out of the pack and the landlord ships a
lease that omits a federally mandated disclosure. Nothing in the output would
look wrong. So a missing fact propagates as UNDETERMINED, `validate.py` turns
that into a blocking finding naming the exact fact, and the pack refuses to
assemble until a human answers.

There is no `eval` here and there never will be — conditions are data from a
YAML file, and data does not get to execute. The operator set is closed and
explicit; an unknown operator raises rather than being skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import UNSET


class Tri:
    """Three-valued logic. `UNDETERMINED` is the whole point of this module."""

    TRUE = "true"
    FALSE = "false"
    UNDETERMINED = "undetermined"


class ConditionError(ValueError):
    """A malformed condition in a jurisdiction file. Raised loudly at load time
    rather than silently treated as "does not apply" — a typo in a rule must
    never quietly remove a required disclosure."""


@dataclass
class Evaluation:
    state: str
    missing_facts: tuple[str, ...] = ()
    """Facts that would have to be answered to settle an UNDETERMINED result.
    Carried up so the validator can name them precisely instead of saying
    "something is missing"."""

    @property
    def applies(self) -> bool:
        return self.state == Tri.TRUE

    @property
    def undetermined(self) -> bool:
        return self.state == Tri.UNDETERMINED


_TRUE = Evaluation(Tri.TRUE)
_FALSE = Evaluation(Tri.FALSE)


def _compare(op: str, actual: Any, expected: Any) -> bool:
    if op == "eq":
        return _coerce(actual) == _coerce(expected)
    if op == "ne":
        return _coerce(actual) != _coerce(expected)
    if op == "lt":
        return _as_number(actual) < _as_number(expected)
    if op == "lte":
        return _as_number(actual) <= _as_number(expected)
    if op == "gt":
        return _as_number(actual) > _as_number(expected)
    if op == "gte":
        return _as_number(actual) >= _as_number(expected)
    if op == "in":
        return _coerce(actual) in [_coerce(v) for v in _as_list(expected)]
    if op == "not_in":
        return _coerce(actual) not in [_coerce(v) for v in _as_list(expected)]
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    raise ConditionError(
        f"Unknown operator '{op}'. Supported: eq, ne, lt, lte, gt, gte, in, not_in, "
        f"is_true, is_false, is_set."
    )


def _coerce(value: Any) -> Any:
    """Case-insensitive string comparison; everything else compared as-is.
    Keeps `state: ca` in a hand-written example matching `value: CA` in a rule."""
    return value.strip().lower() if isinstance(value, str) else value


def _as_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ConditionError(f"Cannot compare {value!r} numerically.") from e


def _as_list(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    raise ConditionError(f"Operator expects a list, got {value!r}.")


def evaluate(condition: Any, facts) -> Evaluation:
    """Evaluate a condition against a fact source exposing `lookup_fact(name)`.

    `None`/absent condition means the rule always applies — a disclosure with no
    stated precondition is unconditional, which is the safe reading.
    """
    if condition is None:
        return _TRUE
    if not isinstance(condition, dict):
        raise ConditionError(f"Condition must be a mapping, got {type(condition).__name__}.")

    if "all" in condition:
        return _combine_all(condition["all"], facts)
    if "any" in condition:
        return _combine_any(condition["any"], facts)
    if "not" in condition:
        inner = evaluate(condition["not"], facts)
        if inner.state == Tri.TRUE:
            return _FALSE
        if inner.state == Tri.FALSE:
            return _TRUE
        return inner  # UNDETERMINED stays undetermined, carrying its missing facts

    return _leaf(condition, facts)


def _combine_all(clauses: Any, facts) -> Evaluation:
    """AND. A definite FALSE wins immediately, *even if* a sibling clause is
    unanswerable — this is what stops the engine demanding a bed-bug history for
    a Texas property just because a California rule mentions one."""
    if not isinstance(clauses, list):
        raise ConditionError("'all' expects a list of conditions.")
    missing: list[str] = []
    for clause in clauses:
        result = evaluate(clause, facts)
        if result.state == Tri.FALSE:
            return _FALSE
        if result.state == Tri.UNDETERMINED:
            missing.extend(result.missing_facts)
    if missing:
        return Evaluation(Tri.UNDETERMINED, tuple(dict.fromkeys(missing)))
    return _TRUE


def _combine_any(clauses: Any, facts) -> Evaluation:
    """OR. A definite TRUE wins immediately — no need to answer the rest."""
    if not isinstance(clauses, list):
        raise ConditionError("'any' expects a list of conditions.")
    missing: list[str] = []
    for clause in clauses:
        result = evaluate(clause, facts)
        if result.state == Tri.TRUE:
            return _TRUE
        if result.state == Tri.UNDETERMINED:
            missing.extend(result.missing_facts)
    if missing:
        return Evaluation(Tri.UNDETERMINED, tuple(dict.fromkeys(missing)))
    return _FALSE


def _leaf(condition: dict, facts) -> Evaluation:
    field_name = condition.get("field")
    if not field_name:
        raise ConditionError(f"Condition is missing a 'field': {condition!r}")
    op = condition.get("op")
    if not op:
        raise ConditionError(f"Condition on '{field_name}' is missing an 'op'.")

    value = facts.lookup_fact(field_name)

    # `is_set` is the one operator that can answer without the fact being known —
    # asking "was this supplied?" is always answerable.
    if op == "is_set":
        return _TRUE if value is not UNSET else _FALSE

    if value is UNSET:
        return Evaluation(Tri.UNDETERMINED, (field_name,))

    return _TRUE if _compare(op, value, condition.get("value")) else _FALSE


def referenced_fields(condition: Any) -> list[str]:
    """Every fact name a condition could ask about. Used by `pack facts` to tell
    a user what to fill in *before* they hit the blocking gate."""
    if condition is None or not isinstance(condition, dict):
        return []
    for key in ("all", "any"):
        if key in condition:
            names: list[str] = []
            for clause in condition[key] or []:
                names.extend(referenced_fields(clause))
            return list(dict.fromkeys(names))
    if "not" in condition:
        return referenced_fields(condition["not"])
    name = condition.get("field")
    return [name] if name else []
