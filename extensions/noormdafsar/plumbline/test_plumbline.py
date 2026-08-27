"""Tests for the deterministic half. No API key, no network, no SuperDocs.

    python test_plumbline.py

The model's job in Plumbline is to read English and produce claims. That part is
not deterministic and is not tested here. Everything that decides whether a
document is TRUE is deterministic, and all of it is tested here -- because a
drift report is only worth reading if the verification behind it cannot be
argued with.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from claims import Claim, check
from codefacts import read_source, read_tree
from extract import parse_table

HERE = Path(__file__).resolve().parent
FAILURES: list[str] = []


def ok(name: str, cond: bool, detail: str = ""):
    if not cond:
        FAILURES.append(f"{name}{': ' + detail if detail else ''}")


def facts_from(src: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "mod.py"
        p.write_text(src, encoding="utf-8")
        return read_source([p], root=Path(d))


# --------------------------------------------------------------- the AST side
def test_signatures():
    f = facts_from('''
CONST_A = 42
TIMEOUT: int = 30

class C:
    def m(self, a, b: str = "x", *args, kw: int = 1, **rest) -> list[dict]:
        if a:
            raise ValueError("no")
        raise LookupError()

    async def am(self) -> None: ...
''')
    fn = f.get_function("C.m")
    ok("method found", fn is not None)
    ok("param names", fn.param_names == ["a", "b", "*args", "kw", "**rest"],
       str(fn.param_names))
    ok("default read from source", fn.default_for("b") == "'x'", fn.default_for("b"))
    ok("required param has no default", fn.default_for("a") is None)
    ok("keyword-only default", fn.default_for("kw") == "1")
    ok("return annotation", fn.returns == "list[dict]", str(fn.returns))
    ok("raises collected in order", fn.raises == ["ValueError", "LookupError"],
       str(fn.raises))
    ok("async flagged", f.get_function("C.am").is_async is True)
    ok("constants read", f.get_constant("CONST_A").value == "42")
    ok("annotated constant read", f.get_constant("TIMEOUT").value == "30")
    ok("bare method name resolves", f.get_function("m") is not None)


def test_nested_functions_are_not_public_surface():
    f = facts_from('''
def outer():
    def inner():
        pass
''')
    ok("nested function ignored", f.get_function("outer.inner") is None)


# ------------------------------------------------------------ the claim side
SRC = '''
DEFAULT_TIMEOUT = 45

class Client:
    def go(self, path: str, *, retries: int = 3, verbose: bool = False) -> list[dict]:
        if not path:
            raise ValueError("path required")
        return []
'''


def claim(kind, symbol, value, parameter="", quote="q"):
    return Claim(kind=kind, symbol=symbol, value=value, parameter=parameter, quote=quote)


def test_true_claims_verify():
    f = facts_from(SRC)
    good = [
        claim("constant_value", "DEFAULT_TIMEOUT", "45"),
        claim("constant_value", "DEFAULT_TIMEOUT", "45 seconds"),   # prose unit
        claim("parameter_default", "Client.go", "3", "retries"),
        claim("parameter_exists", "Client.go", "verbose", "verbose"),
        claim("return_type", "Client.go", "a list of dictionaries"),  # prose type
        claim("return_type", "Client.go", "list[dict]"),
        claim("raises", "Client.go", "ValueError"),
    ]
    drifts, verified = check(good, f)
    ok("every true claim verifies", not drifts,
       "; ".join(f"{d.claim.describe()} -> {d.detail}" for d in drifts))
    ok("verified count", len(verified) == len(good))


def test_false_claims_drift():
    f = facts_from(SRC)
    bad = [
        claim("constant_value", "DEFAULT_TIMEOUT", "30"),
        claim("parameter_default", "Client.go", "5", "retries"),
        claim("parameter_exists", "Client.go", "timeout", "timeout"),
        claim("return_type", "Client.go", "a string"),
        claim("raises", "Client.go", "KeyError"),
        claim("parameter_default", "Client.go", "1", "path"),      # required arg
        claim("parameter_exists", "Client.nope", "x", "x"),        # missing symbol
    ]
    drifts, verified = check(bad, f)
    ok("every false claim drifts", len(drifts) == len(bad),
       f"only {len(drifts)} of {len(bad)}")
    ok("nothing false verified", not verified)

    by = {(d.claim.kind, d.claim.parameter or d.claim.value): d for d in drifts}
    ok("stale constant carries the real value",
       by[("constant_value", "30")].truth == "45")
    ok("missing symbol is breaking",
       by[("parameter_exists", "x")].severity == "breaking")
    ok("required-arg default is breaking",
       by[("parameter_default", "path")].severity == "breaking")
    ok("wrong default is stale",
       by[("parameter_default", "retries")].severity == "stale")
    ok("every drift names a location",
       all(d.where for d in drifts))


def test_a_claim_about_a_constant_is_checked_as_one():
    """The extractor often labels 'the default timeout is 30 seconds' a
    parameter_default. That is a question about English, not about the code, and
    must not turn a plain stale value into 'no such symbol'."""
    f = facts_from(SRC)
    drifts, _ = check([claim("parameter_default", "DEFAULT_TIMEOUT", "30", "timeout")], f)
    ok("mislabelled constant still checked", len(drifts) == 1)
    ok("reported as stale, not breaking", drifts[0].severity == "stale",
       drifts[0].severity)
    ok("against the real value", drifts[0].truth == "45", drifts[0].truth)


def test_unannotated_return_is_unverifiable_not_wrong():
    f = facts_from("def f(x):\n    return x\n")
    drifts, verified = check([claim("return_type", "f", "a string")], f)
    ok("no annotation means unverifiable", drifts and drifts[0].severity == "unverifiable")
    ok("and is not counted as verified", not verified)


# ------------------------------------------------------------- table parsing
def test_table_parser_survives_a_real_export():
    md = """# Extracted claims

Here is the table you asked for.

| kind | symbol | parameter | value | quote |
| --- | --- | --- | --- | --- |
| parameter\\_default | Client.go | retries | 5 | it defaults to 5 |
| constant\\_value | DEFAULT\\_TIMEOUT |  | 30 seconds | the timeout is 30 seconds |
"""
    rows = parse_table(md)
    ok("two rows parsed", len(rows) == 2, str(len(rows)))
    ok("markdown escapes removed", rows[0]["kind"] == "parameter_default", rows[0]["kind"])
    ok("underscored symbol unescaped", rows[1]["symbol"] == "DEFAULT_TIMEOUT",
       rows[1]["symbol"])
    ok("empty cell preserved", rows[1]["parameter"] == "")


def test_table_parser_ignores_column_order():
    md = """| symbol | kind | quote | value | parameter |
| --- | --- | --- | --- | --- |
| Client.go | raises | it raises ValueError | ValueError |  |
"""
    rows = parse_table(md)
    ok("row parsed regardless of order", len(rows) == 1)
    ok("mapped by header name", rows[0]["value"] == "ValueError" and rows[0]["kind"] == "raises",
       str(rows[0]))


# ------------------------------------------------------- the shipped example
def test_the_sample_repo_has_the_drift_it_claims_to():
    f = read_tree(HERE / "sample-repo" / "meridian_sdk")
    ok("timeout really is 45", f.get_constant("DEFAULT_TIMEOUT").value == "45")
    ok("max_retries really is 3",
       f.get_function("Client.__init__").default_for("max_retries") == "3")
    ok("page_size really is 100",
       f.get_function("Client.list_ledgers").default_for("page_size") == "100")
    ok("currency really is EUR",
       f.get_function("Client.post_entry").default_for("currency") == "'EUR'")
    ok("close_ledger really has no effective_date",
       "effective_date" not in f.get_function("Client.close_ledger").param_names)
    doc = (HERE / "sample-repo" / "docs" / "api-reference.html").read_text(encoding="utf-8")
    for wrong in ["30 seconds", "defaults to 5", "defaults to 50", "USD", "effective_date"]:
        ok(f"the document still claims {wrong!r}", wrong in doc)


def test_prose_that_names_a_thing_is_not_drift():
    """A false positive here is not harmless: the fix step obediently edited a
    correct sentence to match, deleting the word "region" from it. The extractor
    reports "eu-west-1 region"; the code says 'eu-west-1'; those are the same
    value with a noun attached."""
    from claims import _same_value
    same = [("eu-west-1 region", "'eu-west-1'"), ("the eu-west-1", "'eu-west-1'"),
            ("30 seconds", "30"), ("EUR", "'EUR'")]
    different = [("30 seconds", "45"), ("USD", "'EUR'"), ("eu-central-1", "'eu-west-1'"),
                 ("5", "3"), ("50", "100")]
    for c, a in same:
        ok(f"{c!r} == {a!r}", _same_value(c, a), "reported as drift but is not")
    for c, a in different:
        ok(f"{c!r} != {a!r}", not _same_value(c, a), "missed a real drift")


def test_collateral_guard_works_at_sentence_granularity():
    """The paragraph-level version of this guard found nothing, because the
    unwanted deletion happened inside the same paragraph as a real correction."""
    from plumbline import collateral_edits
    before = ("<p>The timeout is 30 seconds. Requests go to eu-west-1 region "
              "unless another is given.</p>")
    after = ("<p>The timeout is 45 seconds. Requests go to eu-west-1 "
             "unless another is given.</p>")
    quotes = ["The timeout is 30 seconds."]
    found = collateral_edits(before, after, quotes)
    ok("the untouched sentence's change is caught", len(found) == 1, str(found))
    ok("the corrected sentence is not flagged",
       found and "region" in found[0], str(found))
    ok("an identical document is clean", not collateral_edits(before, before, quotes))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        before = len(FAILURES)
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            FAILURES.append(f"{t.__name__} raised {type(exc).__name__}: {exc}")
        mark = "ok  " if len(FAILURES) == before else "FAIL"
        print(f"  {mark}  {t.__name__}")
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):")
        for f_ in FAILURES:
            print(f"  - {f_}")
        return 1
    print(f"all {len(tests)} checks pass — no API key, no network")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
