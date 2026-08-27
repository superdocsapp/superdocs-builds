"""The claim side of Plumbline: what the documentation asserts about the code.

A claim is a typed, checkable statement extracted from prose -- "the default
timeout is 30 seconds", "this returns a list of strings", "it raises ValueError".
Extracting them from English is a language job, so a model does it. Deciding
whether they are true is a code job, so `codefacts` does that, with no model
anywhere near it.

Drift is where the two disagree, and every drift carries both sides: the
sentence that claims it and the file and line that contradict it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from codefacts import CodeFacts

# The kinds of claim this tool is willing to check. Anything a model extracts
# outside this set is discarded rather than half-checked -- a claim type with no
# verifier is an opinion, and opinions do not belong in a drift report.
CLAIM_KINDS = [
    "parameter_exists",     # symbol has a parameter named X
    "parameter_default",    # parameter X of symbol defaults to V
    "return_type",          # symbol returns T
    "raises",               # symbol raises E
    "constant_value",       # constant C is V
]

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": CLAIM_KINDS},
                    "symbol": {
                        "type": "string",
                        "description": "The code symbol, e.g. Client.request or DEFAULT_TIMEOUT",
                    },
                    "parameter": {"type": "string", "description": "Parameter name, or empty"},
                    "value": {
                        "type": "string",
                        "description": "The value, type or exception the document states",
                    },
                    "quote": {
                        "type": "string",
                        "description": (
                            "The exact sentence from the document that makes this "
                            "claim, copied character for character. Checked against "
                            "the document; a claim whose quote is not found verbatim "
                            "is discarded."
                        ),
                    },
                },
                "required": ["kind", "symbol", "value", "quote"],
            },
        }
    },
    "required": ["claims"],
}


@dataclass
class Claim:
    kind: str
    symbol: str
    value: str
    quote: str
    parameter: str = ""

    def describe(self) -> str:
        if self.kind == "parameter_exists":
            return f"{self.symbol} takes a parameter named {self.parameter or self.value}"
        if self.kind == "parameter_default":
            return f"{self.symbol}({self.parameter}=...) defaults to {self.value}"
        if self.kind == "return_type":
            return f"{self.symbol} returns {self.value}"
        if self.kind == "raises":
            return f"{self.symbol} raises {self.value}"
        return f"{self.symbol} is {self.value}"


@dataclass
class Drift:
    claim: Claim
    truth: str              # what the code actually says
    where: str              # file:line
    severity: str           # breaking | stale | unverifiable
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.claim.kind,
            "symbol": self.claim.symbol,
            "parameter": self.claim.parameter,
            "claimed": self.claim.value,
            "actual": self.truth,
            "quote": self.claim.quote,
            "where": self.where,
            "severity": self.severity,
            "detail": self.detail,
        }


def parse_claims(payload: dict, document_text: str) -> tuple[list[Claim], list[str]]:
    """Turn model output into claims, discarding anything not grounded in the doc.

    A claim whose quote does not appear in the document is dropped, for the same
    reason a fact without a source is dropped elsewhere in this repo: if the tool
    cannot point at the sentence, it has no business reporting on it.
    """
    kept: list[Claim] = []
    dropped: list[str] = []
    for raw in payload.get("claims", []) or []:
        quote = (raw.get("quote") or "").strip()
        if not quote or _normalise(quote) not in _normalise(document_text):
            dropped.append(f"{raw.get('symbol', '?')}: quote not found in the document")
            continue
        if raw.get("kind") not in CLAIM_KINDS:
            dropped.append(f"{raw.get('symbol', '?')}: unknown claim kind {raw.get('kind')!r}")
            continue
        kept.append(Claim(
            kind=raw["kind"],
            symbol=(raw.get("symbol") or "").strip(),
            value=(raw.get("value") or "").strip(),
            quote=quote,
            parameter=(raw.get("parameter") or "").strip(),
        ))
    return kept, dropped


_WS = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?)\]])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[])\s+")


def _normalise(s: str) -> str:
    """Compare prose forgivingly enough to survive a round trip through export.

    Exporting to Markdown turns `<code>region</code>, ` into `region , `, so a
    strict comparison would discard quotes that are genuinely present in the
    document. The check still has teeth -- the words and their order must match
    exactly -- it just does not fail over spacing the exporter introduced.
    """
    s = _WS.sub(" ", s).strip().lower()
    s = _SPACE_BEFORE_PUNCT.sub(r"\1", s)
    s = _SPACE_AFTER_OPEN.sub(r"\1", s)
    return s


def _same_value(claimed: str, actual: str) -> bool:
    """Compare a documented value with a source-code value, forgivingly.

    Documentation writes `30 seconds` where code writes `30`, and `"json"` where
    code writes `'json'`. Being strict here would report drift on documents that
    are perfectly correct, which is the fastest way to make a tool like this get
    switched off.
    """
    c, a = _normalise(claimed), _normalise(actual)
    if c == a:
        return True
    strip = str.maketrans("", "", "\"'`")
    c2, a2 = c.translate(strip), a.translate(strip)
    if c2 == a2:
        return True
    # numeric comparison, ignoring trailing units in the prose
    cn = re.match(r"^-?\d+(?:\.\d+)?", c2)
    an = re.match(r"^-?\d+(?:\.\d+)?", a2)
    if cn and an and float(cn.group()) == float(an.group()):
        # only if the prose is that number plus a unit word, not a different number
        rest = c2[cn.end():].strip()
        return rest == "" or rest.isalpha() or rest in ("seconds", "second", "s", "ms")
    if {c2, a2} <= {"true", "false", "none", "null"}:
        return c2 == a2 or (c2, a2) in (("none", "null"), ("null", "none"))

    # Prose names things: the code says 'eu-west-1' and the document says
    # "the eu-west-1 region". The extractor takes the noun with it, and treating
    # that as drift is not a harmless false positive -- the fix step then
    # dutifully deletes the word "region" from a sentence that was correct. A
    # claimed value that is the real value plus ordinary words is the same value.
    if a2 and c2.startswith(a2):
        tail = c2[len(a2):].strip()
        return tail == "" or all(w.isalpha() for w in tail.split())
    if a2 and c2.endswith(a2):
        head = c2[: -len(a2)].strip()
        return head == "" or all(w.isalpha() for w in head.split())
    return False


def _type_matches(claimed: str, actual: str) -> bool:
    c, a = _normalise(claimed), _normalise(actual)
    if c == a:
        return True
    # "a list of strings" vs "list[str]"
    alias = {"string": "str", "strings": "str", "integer": "int", "integers": "int",
             "boolean": "bool", "booleans": "bool", "dictionary": "dict",
             "dictionaries": "dict", "dicts": "dict", "nothing": "none",
             "lists": "list", "objects": "dict", "object": "dict"}
    words = [alias.get(w, w) for w in re.findall(r"[a-z]+", c)]
    core = re.findall(r"[a-z]+", a)
    return bool(core) and all(w in words for w in core)


def check(claims: list[Claim], facts: CodeFacts) -> tuple[list[Drift], list[Claim]]:
    """Verify every claim against the code. Returns (drifts, verified)."""
    drifts: list[Drift] = []
    verified: list[Claim] = []

    for c in claims:
        fn = facts.get_function(c.symbol)
        const = facts.get_constant(c.symbol)

        # A claim about a constant is a claim about a constant, whatever the
        # extractor labelled it. Documentation says "the default timeout is 30
        # seconds"; whether that reads as a parameter default or a constant is a
        # question about English, not about the code, and getting it wrong should
        # not turn a straightforward stale value into "no such symbol".
        if const is not None and fn is None:
            c = Claim(kind="constant_value", symbol=c.symbol, value=c.value,
                      quote=c.quote, parameter=c.parameter)

        if c.kind == "constant_value":
            if const is None:
                drifts.append(Drift(c, "no such constant", "-", "breaking",
                                    f"the document describes {c.symbol}, which does not "
                                    f"exist in the code"))
                continue
            where = f"{const.file}:{const.line}"
            if _same_value(c.value, const.value):
                verified.append(c)
            else:
                drifts.append(Drift(c, const.value, where, "stale",
                                    f"the document says {c.value}, the code says {const.value}"))
            continue

        if fn is None:
            drifts.append(Drift(c, "no such symbol", "-", "breaking",
                                f"the document describes {c.symbol}, which does not exist "
                                f"in the code"))
            continue

        where = f"{fn.file}:{fn.line}"

        if c.kind == "parameter_exists":
            name = c.parameter or c.value
            if name in fn.param_names:
                verified.append(c)
            else:
                drifts.append(Drift(c, ", ".join(fn.param_names) or "(none)", where, "breaking",
                                    f"the document documents a parameter {name!r} that "
                                    f"{c.symbol} does not take"))

        elif c.kind == "parameter_default":
            if c.parameter not in fn.param_names:
                drifts.append(Drift(c, ", ".join(fn.param_names) or "(none)", where, "breaking",
                                    f"the document gives a default for {c.parameter!r}, "
                                    f"which {c.symbol} does not take"))
                continue
            actual = fn.default_for(c.parameter)
            if actual is None:
                drifts.append(Drift(c, "no default (required)", where, "breaking",
                                    f"the document says {c.parameter} defaults to {c.value}, "
                                    f"but it is a required argument"))
            elif _same_value(c.value, actual):
                verified.append(c)
            else:
                drifts.append(Drift(c, actual, where, "stale",
                                    f"the document says {c.parameter} defaults to {c.value}, "
                                    f"the code says {actual}"))

        elif c.kind == "return_type":
            if not fn.returns:
                drifts.append(Drift(c, "unannotated", where, "unverifiable",
                                    f"{c.symbol} has no return annotation, so the claim "
                                    f"cannot be checked either way"))
            elif _type_matches(c.value, fn.returns):
                verified.append(c)
            else:
                drifts.append(Drift(c, fn.returns, where, "stale",
                                    f"the document says it returns {c.value}, the "
                                    f"signature says {fn.returns}"))

        elif c.kind == "raises":
            wanted = c.value.split(".")[-1].strip()
            if wanted in fn.raises:
                verified.append(c)
            else:
                drifts.append(Drift(c, ", ".join(fn.raises) or "(raises nothing directly)",
                                    where, "stale",
                                    f"the document says it raises {wanted}; the body raises "
                                    f"{', '.join(fn.raises) or 'nothing directly'}"))

    return drifts, verified
