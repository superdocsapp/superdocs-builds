"""Tests for the deterministic half of the factory. No network, no API key.

  python3 test_engine.py
"""

import os
import sys
import tempfile
from decimal import Decimal

import engine
import run
import superdocs

RULES, BLOCKS, RECORDS = engine.load_data()
PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        FAILED.append("{0}{1}".format(name, ": " + detail if detail else ""))


def by_id(customer_id):
    for record in RECORDS:
        if record["customer_id"] == customer_id:
            return record
    raise AssertionError("no record " + customer_id)


def held_reason(customer_id):
    result = engine.prepare(by_id(customer_id), RULES, BLOCKS)
    if result["status"] != "held":
        return None
    return " ".join(failure["reason"] for failure in result["failures"])


def test_interest_is_exact_and_reproducible():
    result = engine.prepare(by_id("CUS-1001"), RULES, BLOCKS)
    # 42500 cents at 10 percent for 214 days on a 365 day basis, rounded half up.
    expected_interest = (Decimal(42500) * Decimal(1000) / Decimal(10000)
                         * Decimal(214) / Decimal(365))
    check("interest matches hand arithmetic",
          result["values"]["interest_cents"] == Decimal(round(expected_interest)),
          str(result["values"]["interest_cents"]))
    check("refund is overcharge plus interest",
          result["values"]["refund_cents"]
          == result["values"]["overcharge_cents"] + result["values"]["interest_cents"])
    check("every formula step is in the audit trail",
          len(result["trail"]) == len(RULES["formula"]["steps"]))
    check("trail shows substituted arithmetic, not just the answer",
          any("42500 * 1000 / 10000" in line for line in result["trail"]))


def test_broken_records_are_held_with_named_reasons():
    cases = [
        ("CUS-2001", "greater than zero"),
        ("CUS-2002", "'notice_date' is missing"),
        ("CUS-2003", "does not match the figure the formula produces"),
        ("CUS-2004", "is not configured in rules.json"),
        ("CUS-2005", "No approved wording block exists"),
        ("CUS-2006", "No approved wording block exists"),
        ("CUS-2007", "falls after the notice date"),
        ("CUS-2008", "above the"),
    ]
    for customer_id, fragment in cases:
        reason = held_reason(customer_id)
        check("{0} is held".format(customer_id), reason is not None)
        check("{0} reason names the actual problem".format(customer_id),
              reason is not None and fragment in reason, str(reason))
        check("{0} reason is not generic".format(customer_id),
              reason is not None and "failed validation" not in reason.lower())


def test_clean_records_produce_letters():
    prepared = engine.prepare_all(RECORDS, RULES, BLOCKS)
    ready = [item for item in prepared if item["status"] == "ready"]
    check("clean records still produce letters", len(ready) >= 15, str(len(ready)))
    for letter in ready:
        record = letter["record"]
        block = letter["block"]
        check("block matches the record variant",
              (block["jurisdiction"] == record["jurisdiction"]
               and block["stage"] == record["stage"]
               and block["language"] == record["language"]))
        for section in letter["sections"]:
            check("no placeholder is left unfilled", "{{" not in section["text"],
                  section["text"][:60])


def test_approved_wording_is_never_altered():
    """Strip the inserted values back out and the approved block must reappear."""
    prepared = engine.prepare_all(RECORDS, RULES, BLOCKS)
    for letter in [item for item in prepared if item["status"] == "ready"]:
        for section in letter["sections"]:
            rebuilt = section["text"]
            for placeholder in sorted(section["placeholders"], key=len, reverse=True):
                value = str(letter["fills"][placeholder])
                rebuilt = rebuilt.replace(value, "{{" + placeholder + "}}")
            check("section '{0}' is the approved wording with values inserted".format(
                section["id"]), rebuilt == section["approved_text"],
                "got: " + rebuilt[:80])


def test_language_variant_is_produced():
    spanish = engine.prepare(by_id("CUS-1003"), RULES, BLOCKS)
    check("spanish letter uses the spanish block",
          spanish["block"]["language"] == "es", spanish["block"]["id"])
    account_line = [section for section in spanish["sections"]
                    if section["id"] == "account_line"][0]
    check("spanish date format is used", "de agosto de 2026" in account_line["text"],
          account_line["text"])
    english = engine.prepare(by_id("CUS-1001"), RULES, BLOCKS)
    english_line = [section for section in english["sections"]
                    if section["id"] == "account_line"][0]
    check("english date format is used", "August 17, 2026" in english_line["text"],
          english_line["text"])


def test_no_customer_is_processed_twice():
    duplicated = RECORDS + [by_id("CUS-1001")]
    prepared = engine.prepare_all(duplicated, RULES, BLOCKS)
    ids = [item["record"]["customer_id"] for item in prepared]
    check("duplicate customer ids are skipped", len(ids) == len(set(ids)))


def test_batches_respect_the_operation_limit():
    ready = [item for item in engine.prepare_all(RECORDS, RULES, BLOCKS)
             if item["status"] == "ready"]
    batches = run.pack_batches(ready)
    for batch in batches:
        sections = sum(len(letter["sections"]) + 1 for letter in batch)
        check("batch stays inside one operation",
              sections <= run.MAX_SECTIONS_PER_OPERATION, str(sections))
    packed = sum(len(batch) for batch in batches)
    check("every ready letter is packed exactly once", packed == len(ready))


def test_a_new_jurisdiction_needs_no_code_change():
    """Only runs once New York exists in the data files."""
    if "new_york" not in RULES["jurisdictions"]:
        return
    candidates = [record for record in RECORDS if record["jurisdiction"] == "new_york"
                  and "defect_note" not in record]
    check("new york records exist", bool(candidates))
    for record in candidates:
        result = engine.prepare(record, RULES, BLOCKS)
        check("new york record {0} produces a letter".format(record["customer_id"]),
              result["status"] == "ready",
              str(result.get("failures")))
        if result["status"] == "ready":
            check("new york uses the new york rate",
                  result["values"]["annual_rate_bps"] == Decimal(
                      RULES["jurisdictions"]["new_york"]["interest_rate_bps"]))


class FakeClient(object):
    """Stands in for SuperDocs so the approval path can be tested with no API key."""

    def __init__(self, changes):
        self.rounds = [("awaiting_approval", changes), ("completed", [])]
        self.decisions = []

    def wait_for_pause(self, job_id):
        return self.rounds.pop(0) if self.rounds else ("completed", [])

    def approve(self, session_id, job_id, change_id, approved):
        self.decisions.append((change_id, approved))
        return {"status": "ok"}


def _drift_setup():
    entry = {"customer_id": "CUS-9001", "section_id": "dispute_rights",
             "template_text": "You may contact the {{CUS-9001.regulator}} at any time.",
             "expected_text": "You may contact the California Department of Financial "
                              "Protection and Innovation at any time.",
             "editable": True}
    change = {"change_id": "chg-1", "chunk_id": "chunk-1",
              "new_html": "<p>You may contact the Financial Conduct Authority at any time.</p>"}
    outcomes = {"CUS-9001": {"approved_sections": set(), "problems": []}}
    return entry, change, outcomes


def test_drifted_wording_is_denied_and_reported():
    entry, change, outcomes = _drift_setup()
    client = FakeClient([change])
    run.run_approval_rounds(client, "s", "j", {"chunk-1": entry}, outcomes, lambda m: None)
    check("the drifted change was denied at the API", client.decisions == [("chg-1", False)],
          str(client.decisions))
    check("the section was not recorded as approved",
          not outcomes["CUS-9001"]["approved_sections"])
    problems = outcomes["CUS-9001"]["problems"]
    check("the denial is reported once", len(problems) == 1, str(len(problems)))
    check("the report quotes what was expected",
          "California Department of Financial Protection" in problems[0]["reason"])
    check("the report quotes what was received",
          "Financial Conduct Authority" in problems[0]["reason"])


def test_matching_wording_is_approved():
    entry, change, outcomes = _drift_setup()
    change["new_html"] = "<p>" + entry["expected_text"] + "</p>"
    client = FakeClient([change])
    run.run_approval_rounds(client, "s", "j", {"chunk-1": entry}, outcomes, lambda m: None)
    check("an exact match is approved at the API", client.decisions == [("chg-1", True)],
          str(client.decisions))
    check("the section is recorded as approved",
          outcomes["CUS-9001"]["approved_sections"] == set(["dispute_rights"]))
    check("an approved section raises no problem", not outcomes["CUS-9001"]["problems"])


def test_batch_keys_come_from_content_not_the_clock():
    ready = [item for item in engine.prepare_all(RECORDS, RULES, BLOCKS)
             if item["status"] == "ready"]
    batches = run.pack_batches(ready)
    first = [run.batch_key(batch) for batch in batches]
    second = [run.batch_key(batch) for batch in run.pack_batches(ready)]
    check("the same batch always gets the same key", first == second)
    check("different batches get different keys", len(set(first)) == len(first))
    check("the run key is stable across calls",
          run.run_key(ready, "docx") == run.run_key(ready, "docx"))
    check("changing the export format changes the run key",
          run.run_key(ready, "docx") != run.run_key(ready, "pdf"))
    check("dropping a letter changes the run key",
          run.run_key(ready, "docx") != run.run_key(ready[:-1], "docx"))


def test_state_round_trips_and_refuses_foreign_data():
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "run-state.json")
    check("no state file means nothing to resume", run.load_state(path, "key-a") is None)
    run.save_state(path, {"run_key": "key-a", "batches": {"b1": {"chat_turns": 1}}})
    loaded = run.load_state(path, "key-a")
    check("state survives a save and load", loaded["batches"]["b1"]["chat_turns"] == 1)
    try:
        run.load_state(path, "key-b")
        check("resuming onto different data is refused", False, "no error raised")
    except SystemExit as error:
        check("resuming onto different data is refused", True)
        check("the refusal explains what to do", "delete that file" in str(error), str(error))


def test_report_records_a_failed_run():
    ready = [item for item in engine.prepare_all(RECORDS, RULES, BLOCKS)
             if item["status"] == "ready"]

    class Args(object):
        offline = False
        sample = None

    report = run.build_report([], ready, [], [], [], 3, 2, Args(), "out",
                              "POST /v1/chat/async returned HTTP 500")
    check("a failed run is marked failed", report["status"] == "failed")
    check("the failure reason is kept in the report", "HTTP 500" in report["failure"])
    check("operations already paid are separated from reused ones",
          report["operations_used"] == 3
          and report["operations_reused_from_earlier_run"] == 2)
    clean = run.build_report([], ready, [], [], [], 1, 0, Args(), "out", None)
    check("a clean run is marked completed", clean["status"] == "completed")


class FakeHTTPError(object):
    def __init__(self, retry_after):
        self.headers = {"Retry-After": retry_after} if retry_after else {}


def test_retry_after_is_honoured():
    check("a plain seconds value is used",
          superdocs._retry_after_seconds(FakeHTTPError("7"), 99) == 7)
    check("a missing header falls back to the backoff",
          superdocs._retry_after_seconds(FakeHTTPError(None), 99) == 99)
    check("an absurd value is capped",
          superdocs._retry_after_seconds(FakeHTTPError("99999"), 1)
          == superdocs.MAX_BACKOFF_SECONDS)
    check("an http date is understood",
          superdocs._retry_after_seconds(
              FakeHTTPError("Wed, 21 Oct 2099 07:28:00 GMT"), 5)
          == superdocs.MAX_BACKOFF_SECONDS)
    check("a malformed header falls back to the backoff",
          superdocs._retry_after_seconds(FakeHTTPError("soon please"), 42) == 42)


def test_connection_errors_are_retryable_and_named():
    check("429 is treated as retryable", 429 in superdocs.RETRYABLE_STATUS)
    check("server errors are treated as retryable",
          all(code in superdocs.RETRYABLE_STATUS for code in (500, 502, 503, 504)))
    check("a 401 is not retried", 401 not in superdocs.RETRYABLE_STATUS)
    for code in (401, 413, 429):
        advice = superdocs.STATUS_ADVICE.get(code)
        check("HTTP {0} carries advice, not just a number".format(code), bool(advice))
    check("the 413 advice names the setting to change",
          "MAX_SECTIONS_PER_OPERATION" in superdocs.STATUS_ADVICE[413])
    check("the resume hint is offered on failures", "--resume" in superdocs.RESUME_HINT)


def main():
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    print("{0} assertions passed, {1} failed".format(len(PASSED), len(FAILED)))
    for failure in FAILED:
        print("  FAILED: " + failure)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
