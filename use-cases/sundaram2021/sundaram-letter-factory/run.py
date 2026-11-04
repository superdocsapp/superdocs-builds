"""Run the letter factory end to end.

  python3 run.py                 full run against SuperDocs
  python3 run.py --sample 3      first three customer records only
  python3 run.py --offline       assemble and validate, make no API calls
  python3 run.py --resume        continue a stopped run without paying twice

The order is always the same: prepare and validate every record locally, then
send only the records that passed, in batches sized to the operation limit.
"""

import argparse
import hashlib
import html as html_module
import json
import os
import re
import sys

import engine
import superdocs

# One free tier operation covers up to 25 edited sections, so batches are packed
# against that number rather than against a letter count.
MAX_SECTIONS_PER_OPERATION = 25

# The editor proposes its changes in rounds and pauses for approval between them.
# This only guards against an unexpected loop, it is not a retry count.
MAX_APPROVAL_ROUNDS = 20

# If a turn leaves tokens unfilled, one more turn is sent naming just those
# sections. Two attempts is the ceiling: past that the record is held, not retried.
MAX_CHAT_ATTEMPTS = 2

# pro completes a whole batch in a single turn. Lower tiers stopped part way
# through a multi letter batch when I tested them, which held letters back.
MODEL_TIER = "pro"

CHUNK_RE = re.compile(
    r"<(h1|h2|h3|p)\b[^>]*data-chunk-id=\"([^\"]+)\"[^>]*>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def normalize(text):
    """Compare letter text without being tripped up by markup or spacing.

    The editor is free to return equivalent HTML, so wording is compared as
    plain text with whitespace collapsed. Every visible character still has to
    match the approved block exactly.
    """
    plain = TAG_RE.sub("", text)
    plain = html_module.unescape(plain)
    return " ".join(plain.split())


def batch_key(letters):
    """A stable name for a batch, derived from its content rather than the clock.

    Two runs over the same records produce the same key and therefore the same
    SuperDocs session, so a re-run lands on the work already done instead of
    creating a fresh session and paying for it again.
    """
    material = json.dumps(
        [[letter["record"]["customer_id"]] + [section["text"] for section in letter["sections"]]
         for letter in letters], sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def run_key(letters, export_format):
    material = json.dumps(sorted(batch_key([letter]) for letter in letters)) + export_format
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def load_state(path, expected_run_key):
    """Read the state left by an earlier run, refusing to mix it with other data."""
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        state = json.load(fh)
    if state.get("run_key") != expected_run_key:
        raise SystemExit(
            "Cannot resume: {0} was written for a different set of records or export format.\n"
            "Either restore the data files it was written for, or delete that file and start a "
            "fresh run.".format(path))
    return state


def save_state(path, state):
    """Written after every batch, so a crash never loses the record of paid work."""
    temporary = path + ".tmp"
    with open(temporary, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(temporary, path)


def token_for(customer_id, placeholder):
    return "{{" + customer_id + "." + placeholder + "}}"


def build_batch(letters):
    """Build the upload template and the flat section list that mirrors it.

    Placeholder tokens are namespaced per customer so a batch never contains two
    identical tokens with different correct values.
    """
    parts = []
    flat = []
    for letter in letters:
        customer_id = letter["record"]["customer_id"]
        marker = "Internal batch separator, letter for account {0}".format(
            letter["record"]["account_number"])
        parts.append("<h2>{0}</h2>".format(html_module.escape(marker)))
        flat.append({"customer_id": customer_id, "section_id": "__separator__",
                     "template_text": marker, "expected_text": marker, "editable": False})
        for section in letter["sections"]:
            template_text = section["approved_text"]
            for placeholder in section["placeholders"]:
                template_text = template_text.replace(
                    "{{" + placeholder + "}}", token_for(customer_id, placeholder))
            parts.append("<{0}>{1}</{0}>".format(
                section["tag"], html_module.escape(template_text)))
            flat.append({
                "customer_id": customer_id,
                "section_id": section["id"],
                "template_text": template_text,
                "expected_text": section["text"],
                "editable": section["has_placeholders"],
            })
    return "\n".join(parts), flat


def build_instruction(flat, only_sections=None):
    """Write the edit instruction as exact before and after text per section.

    I first wrote this as a token to value map and let the editor do the
    substitution. On longer letters that produced invented figures, invented
    interest rates and even an invented regulator name. My verification denied
    all of it, but half the run was held back. Stating the exact text each
    section must end up reading removes the room to invent: the wording still
    comes from the approved block and the figures still come from the formula,
    and the editor is left with the targeted edit itself.
    """
    lines = [
        "This document is a batch of legally approved letters. Apply these exact section "
        "replacements. Each item gives the current text of one section and the exact text it "
        "must read afterwards. Copy the replacement text character for character. Do not "
        "reword, summarise, translate or reorder anything, and do not invent any number, date, "
        "rate or organisation name.",
        "",
    ]
    numbered = 0
    for entry in flat:
        if not entry["editable"]:
            continue
        if only_sections is not None:
            wanted = only_sections.get(entry["customer_id"])
            if not wanted or entry["section_id"] not in wanted:
                continue
        numbered += 1
        lines.append("{0}. Section currently reading:".format(numbered))
        lines.append("   " + entry["template_text"])
        lines.append("   must read exactly:")
        lines.append("   " + entry["expected_text"])
        lines.append("")
    lines.append("Leave every other section exactly as it is. The document is not finished "
                 "until no {{ }} token remains anywhere in it.")
    return "\n".join(lines)


def pack_batches(letters):
    """Pack letters so one batch stays inside one operation.

    The editor can propose a change to any section in the document, not only the
    ones holding placeholders, so the count here is every section a letter
    contributes plus its batch separator.
    """
    batches = []
    current = []
    current_sections = 0
    for letter in letters:
        cost = len(letter["sections"]) + 1
        if current and current_sections + cost > MAX_SECTIONS_PER_OPERATION:
            batches.append(current)
            current = []
            current_sections = 0
        current.append(letter)
        current_sections += cost
    if current:
        batches.append(current)
    return batches


def letter_html(letter):
    parts = []
    for section in letter["sections"]:
        parts.append("<{0}>{1}</{0}>".format(
            section["tag"], html_module.escape(section["text"])))
    return ("<!DOCTYPE html>\n<html>\n<head><meta charset=\"utf-8\"><title>{0}</title></head>\n"
            "<body>\n{1}\n</body>\n</html>\n").format(
                html_module.escape(letter["block"]["subject"]), "\n".join(parts))


def run_approval_rounds(client, session_id, job_id, by_chunk, outcomes, log):
    """Verify and answer every proposed change until the job has nothing left.

    A change is approved only when its text matches the approved wording with the
    figures filled in, character for character. Anything else is denied.
    """
    answered = set()
    rounds = 0
    while rounds < MAX_APPROVAL_ROUNDS:
        status, changes = client.wait_for_pause(job_id)
        fresh = [change for change in changes if change["change_id"] not in answered]
        if not fresh:
            if status != "completed":
                log("chat: job paused as {0} with nothing new to approve, moving on".format(status))
            break
        log("chat: verifying {0} proposed change(s)".format(len(fresh)))
        for change in fresh:
            answered.add(change["change_id"])
            entry = by_chunk.get(change.get("chunk_id"))
            returned_text = normalize(change.get("new_html") or "")
            if entry is None:
                client.approve(session_id, job_id, change["change_id"], False)
                for outcome in outcomes.values():
                    outcome["problems"].append({
                        "section_id": "__unknown__",
                        "reason": "SuperDocs proposed a change to a section that is not part "
                                  "of this batch, so it was denied."})
                continue

            outcome = outcomes[entry["customer_id"]]
            matches = returned_text == normalize(entry["expected_text"])

            client.approve(session_id, job_id, change["change_id"], matches)
            if matches:
                outcome["approved_sections"].add(entry["section_id"])
            else:
                outcome["problems"].append({
                    "section_id": entry["section_id"],
                    "reason": "Proposed wording for section '{0}' did not match the approved "
                              "block, so the change was denied. Expected: \"{1}\". "
                              "Received: \"{2}\".".format(
                                  entry["section_id"], entry["expected_text"], returned_text)})
        rounds += 1
    log("chat: {0} change(s) verified across {1} approval round(s)".format(len(answered), rounds))


def process_batch(client, batch_index, letters, out_dir, export_format, log, key):
    """Upload, chat, verify, approve, export. Returns per customer outcomes."""
    session_id = "letter-factory-" + key
    template_html, flat = build_batch(letters)

    uploaded = client.upload_document(
        session_id, "batch-{0}-template.html".format(batch_index), template_html)
    returned = CHUNK_RE.findall(uploaded["html"])
    if len(returned) != len(flat):
        raise superdocs.SuperDocsError(
            "upload returned {0} sections but the template had {1}".format(
                len(returned), len(flat)))
    for (_, chunk_id, body), entry in zip(returned, flat):
        if normalize(body) != normalize(entry["template_text"]):
            raise superdocs.SuperDocsError(
                "uploaded section '{0}' came back altered, refusing to continue".format(
                    entry["section_id"]))
        entry["chunk_id"] = chunk_id
    by_chunk = dict((entry["chunk_id"], entry) for entry in flat)
    log("upload: {0} sections registered for {1} letters".format(len(flat), len(letters)))

    outcomes = {}
    for letter in letters:
        outcomes[letter["record"]["customer_id"]] = {
            "approved_sections": set(), "problems": []}

    def outstanding():
        pending = {}
        for letter in letters:
            customer_id = letter["record"]["customer_id"]
            wanted = set(section["id"] for section in letter["sections"]
                         if section["has_placeholders"])
            left = sorted(wanted - outcomes[customer_id]["approved_sections"])
            if left:
                pending[customer_id] = left
        return pending

    only_sections = None
    chat_turns = 0
    for attempt in range(1, MAX_CHAT_ATTEMPTS + 1):
        if attempt > 1:
            log("chat: {0} section(s) still unfilled, sending one follow up turn".format(
                sum(len(v) for v in only_sections.values())))
        job_id = client.start_chat(
            session_id, build_instruction(flat, only_sections), model_tier=MODEL_TIER)
        chat_turns += 1
        run_approval_rounds(client, session_id, job_id, by_chunk, outcomes, log)
        only_sections = outstanding()
        if not only_sections:
            break

    still_missing = outstanding()
    for customer_id, outcome in outcomes.items():
        missing = still_missing.get(customer_id, [])
        # A section denied on the first turn and fixed on the follow up turn is not a problem.
        outcome["problems"] = [problem for problem in outcome["problems"]
                               if problem["section_id"] not in outcome["approved_sections"]]
        reported = set(problem["section_id"] for problem in outcome["problems"])
        for section_id in missing:
            if section_id not in reported:
                outcome["problems"].append({
                    "section_id": section_id,
                    "reason": "SuperDocs proposed no accepted edit for section '{0}' after {1} "
                              "attempt(s), so the figures for that section were never "
                              "inserted.".format(section_id, MAX_CHAT_ATTEMPTS)})
        outcome["problems"] = [problem["reason"] for problem in outcome["problems"]]

    export_name = "batch-{0}".format(batch_index)
    payload = client.export(session_id, export_format, export_name)
    export_path = os.path.join(out_dir, "{0}.{1}".format(export_name, export_format))
    with open(export_path, "wb") as fh:
        fh.write(payload)
    log("export: wrote {0} ({1} bytes)".format(export_path, len(payload)))

    return outcomes, export_path, session_id, chat_turns


def main():
    parser = argparse.ArgumentParser(description="Collections and remediation letter factory")
    parser.add_argument("--sample", type=int, default=None,
                        help="process only the first N customer records")
    parser.add_argument("--offline", action="store_true",
                        help="validate and assemble only, make no SuperDocs calls")
    parser.add_argument("--format", default="docx",
                        choices=["docx", "pdf", "html", "markdown", "txt"],
                        help="export format for each batch")
    parser.add_argument("--resume", action="store_true",
                        help="continue a previous run, skipping batches already paid for")
    parser.add_argument("--out", default="out", help="output directory")
    args = parser.parse_args()

    def log(message):
        print("  " + message)
        sys.stdout.flush()

    out_dir = os.path.abspath(args.out)
    letters_dir = os.path.join(out_dir, "letters")
    if not os.path.isdir(letters_dir):
        os.makedirs(letters_dir)

    rules, blocks, records = engine.load_data()
    print("Letter factory run")
    print("  data: {0} customer records, {1} approved wording blocks, {2} jurisdictions".format(
        len(records), len(blocks), len(rules["jurisdictions"])))
    if args.sample:
        print("  small sample mode: first {0} records only".format(args.sample))
    if args.offline:
        print("  offline mode: no SuperDocs calls will be made")

    prepared = engine.prepare_all(records, rules, blocks, sample=args.sample)
    ready = [item for item in prepared if item["status"] == "ready"]
    held = [{"customer_id": item["record"]["customer_id"],
             "customer_name": item["record"]["customer_name"],
             "variant": engine.variant_key(item["record"]),
             "reasons": [failure["reason"] for failure in item["failures"]],
             "checks": [failure["check_id"] for failure in item["failures"]]}
            for item in prepared if item["status"] == "held"]
    print("\nValidation: {0} records passed, {1} held back".format(len(ready), len(held)))

    for letter in ready:
        path = os.path.join(letters_dir, letter["record"]["customer_id"] + ".html")
        with open(path, "w") as fh:
            fh.write(letter_html(letter))

    batches = pack_batches(ready)
    sent = []
    exports = []
    operations = 0
    reused_operations = 0
    failure = None
    state_path = os.path.join(out_dir, "run-state.json")
    report_path = os.path.join(out_dir, "run-report.json")

    if args.offline:
        print("Skipping SuperDocs stage. {0} letters assembled locally in {1}".format(
            len(ready), letters_dir))
    else:
        key_for_run = run_key(ready, args.format)
        state = load_state(state_path, key_for_run) if args.resume else None
        if args.resume and state is None:
            print("  nothing to resume from, {0} does not exist, starting a fresh run".format(
                state_path))
        if state is None:
            state = {"run_key": key_for_run, "batches": {}}

        client = superdocs.SuperDocs(log=log)
        print("\nSuperDocs stage: {0} letters in {1} batch(es), one chat operation per batch "
              "unless a batch needs a follow up turn".format(len(ready), len(batches)))

        # Every batch is wrapped so a failure part way through still reports what
        # was already paid for, and leaves state behind to resume from.
        try:
            for index, batch in enumerate(batches, start=1):
                key = batch_key(batch)
                done = state["batches"].get(key)
                if done and done.get("status") == "completed":
                    print("\nBatch {0} of {1}: already completed in an earlier run, skipping "
                          "({2} letters, {3} operation(s) already spent)".format(
                              index, len(batches), len(batch), done["chat_turns"]))
                    sent.extend(done["sent"])
                    held.extend(done["held"])
                    exports.append(done["export_path"])
                    reused_operations += done["chat_turns"]
                    continue

                print("\nBatch {0} of {1}: {2} letters".format(index, len(batches), len(batch)))
                outcomes, export_path, session_id, chat_turns = process_batch(
                    client, index, batch, out_dir, args.format, log, key)
                operations += chat_turns

                batch_sent = []
                batch_held = []
                for letter in batch:
                    customer_id = letter["record"]["customer_id"]
                    outcome = outcomes[customer_id]
                    if outcome["problems"]:
                        batch_held.append({
                            "customer_id": customer_id,
                            "customer_name": letter["record"]["customer_name"],
                            "variant": letter["variant"],
                            "reasons": outcome["problems"],
                            "checks": ["approved_wording_verification"],
                        })
                    else:
                        batch_sent.append({
                            "customer_id": customer_id,
                            "variant": letter["variant"],
                            "session_id": session_id,
                        })
                sent.extend(batch_sent)
                held.extend(batch_held)
                exports.append(export_path)
                state["batches"][key] = {
                    "batch_index": index, "session_id": session_id,
                    "export_path": export_path, "chat_turns": chat_turns,
                    "sent": batch_sent, "held": batch_held, "status": "completed",
                }
                save_state(state_path, state)
        except (superdocs.SuperDocsError, KeyboardInterrupt) as error:
            failure = "interrupted by the operator" if isinstance(
                error, KeyboardInterrupt) else str(error)
            save_state(state_path, state)

    report = build_report(prepared, ready, sent, held, exports, operations,
                          reused_operations, args, letters_dir, failure)
    print_report(report)
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    print("\nFull report with the calculation trail for every letter: {0}".format(report_path))
    if failure:
        print("\nThis run stopped early: {0}".format(failure))
        print("Work already paid for is recorded in {0}. Re-run the same command with --resume "
              "to continue from the batch that failed.".format(state_path))
        return 1
    return 0


def build_report(prepared, ready, sent, held, exports, operations, reused_operations, args,
                 letters_dir, failure=None):
    counts = {}
    source = sent if not args.offline else [
        {"customer_id": letter["record"]["customer_id"], "variant": letter["variant"]}
        for letter in ready]
    for item in source:
        counts[item["variant"]] = counts.get(item["variant"], 0) + 1
    return {
        "mode": "offline" if args.offline else "superdocs",
        "sample": args.sample,
        "records_considered": len(prepared),
        "letters_sent": len(source),
        "records_held": len(held),
        "status": "failed" if failure else "completed",
        "failure": failure,
        "operations_used": operations,
        "operations_reused_from_earlier_run": reused_operations,
        "counts_by_variant": counts,
        "held_records": held,
        "sent_records": sent,
        "exports": exports,
        "letters_directory": letters_dir,
        "calculations": [{
            "customer_id": letter["record"]["customer_id"],
            "variant": letter["variant"],
            "wording_block": letter["block"]["id"],
            "figures": dict((name, str(value)) for name, value in letter["values"].items()),
            "trail": letter["trail"],
        } for letter in ready],
    }


def print_report(report):
    print("\n" + "=" * 78)
    print("RUN REPORT")
    print("=" * 78)
    label = "assembled" if report["mode"] == "offline" else "sent"
    print("\nCounts by variant ({0}):".format(label))
    if not report["counts_by_variant"]:
        print("  none")
    for variant in sorted(report["counts_by_variant"]):
        print("  {0}: {1} {2}".format(variant, report["counts_by_variant"][variant], label))
    print("\nTotal {0}: {1}    held back: {2}    operations used: {3}{4}".format(
        label, report["letters_sent"], report["records_held"], report["operations_used"],
        "    reused from an earlier run: {0}".format(
            report["operations_reused_from_earlier_run"])
        if report["operations_reused_from_earlier_run"] else ""))
    if report["status"] == "failed":
        print("\nRUN INCOMPLETE. Counts above cover only the batches that finished.")
    print("\nHeld back records ({0}):".format(report["records_held"]))
    if not report["held_records"]:
        print("  none")
    for item in report["held_records"]:
        print("  {0} ({1}, {2})".format(item["customer_id"], item["customer_name"], item["variant"]))
        for reason in item["reasons"]:
            print("      reason: {0}".format(reason))

if __name__ == "__main__":
    sys.exit(main())
