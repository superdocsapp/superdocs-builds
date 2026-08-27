#!/usr/bin/env python3
"""Renewal Desk -- a renewal quote and price-change notice batch on SuperDocs.

For a list of fabricated accounts renewing, produce a renewal quote and a
price-change notice per account. Python computes every number (pricing.py);
SuperDocs writes and holds the documents; a human approves anything above the
defined increase gate before the batch can be called complete; the batch
reports which accounts it deliberately did not process, and why.

Commands
    plan              what the batch WOULD do -- engine only, zero API calls
    run               generate documents (gated accounts park at the review gate)
    review            show what is waiting on a human, with diffs
    serve             the same review gate as a web console (default port 7000)
    decide            approve / revise / reject one account's notice
    finalize          export anything approved but not yet exported
    report            write out/batch-report.md; exit 1 while the batch is incomplete
    setup-templates   register the two templates in the SuperDocs template library

Requires only the Python standard library. Key comes from SUPERDOCS_API_KEY or
~/.superdocs/agent_credentials.json (the documented agent-signup store).
"""

from __future__ import annotations

import argparse
import calendar
import difflib
import html as html_mod
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from pricing import Decision, decide_all, money
from superdocs_client import (
    Client,
    QuotaExhausted,
    SuperDocsError,
    parse_pending_changes,
)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TEMPLATES = HERE / "templates"
OUT = HERE / "out"
STATE_DIR = OUT / "state"

PLACEHOLDER_RX = re.compile(r"\[(?:[A-Z][A-Z0-9_]{2,})\]")

# Free-tier discipline: stop before the account is bled dry, never at the 429.
MIN_REMAINING_FLOOR = 15


# ----------------------------------------------------------------- state
#
# One file per account, plus a tiny batch file. Deliberately NOT one shared
# state.json: two CLI invocations running at once (a `decide` on one account
# while another was still generating) both did read-modify-write on the single
# file and silently clobbered each other -- an account that had been exported
# came back as "failed" and four others vanished. Per-account files make that
# race structurally impossible: two commands touching two accounts never write
# the same path.
def _batch_path() -> Path:
    return STATE_DIR / "_batch.json"


def _lock_path() -> Path:
    return STATE_DIR / "_run.lock"


class BatchLock:
    """One writer at a time, for the whole batch.

    Per-account state files stop two commands corrupting one account's record,
    but they do not stop a second `run` from starting while a first is still
    working -- and `--fresh` deleting state under a live process produced a
    batch with two different session nonces in it, half belonging to a run that
    was still going. Exclusive create is the cheap, portable way to make that
    impossible: O_CREAT|O_EXCL fails if the file is already there.
    """

    def __init__(self, what: str):
        self.what = what
        self.fd = None

    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(_lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = "unknown"
            try:
                held = _lock_path().read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise SystemExit(
                f"Another batch command is already running ({held}).\n"
                f"Wait for it to finish. If you are certain nothing is running "
                f"(a previous run was killed), delete:\n  {_lock_path()}"
            )
        os.write(self.fd, f"{self.what} pid={os.getpid()} "
                          f"started={datetime.now(timezone.utc).isoformat()}".encode())
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            _lock_path().unlink(missing_ok=True)
        return False


def _acct_path(account_id: str) -> Path:
    return STATE_DIR / f"{account_id}.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic swap: a crash never leaves half-written state


def load_batch() -> dict:
    p = _batch_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"nonce": None}


def save_batch(batch: dict) -> None:
    _write_json(_batch_path(), batch)


def acct_state(account_id: str) -> dict:
    p = _acct_path(account_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"status": "not_started"}


def save_acct(account_id: str, st: dict) -> None:
    _write_json(_acct_path(account_id), st)


def all_states() -> dict[str, dict]:
    if not STATE_DIR.exists():
        return {}
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(STATE_DIR.glob("*.json"))
        if not p.stem.startswith("_")
    }


def total_ops() -> int:
    return sum(st.get("ops_spent", 0) for st in all_states().values())


def last_remaining(states: dict | None = None) -> int | None:
    states = states if states is not None else all_states()
    seen = [st["monthly_remaining_last_seen"] for st in states.values()
            if st.get("monthly_remaining_last_seen") is not None]
    return min(seen) if seen else None


def settle_ops(st: dict, client: Client) -> None:
    """Fold this client's spend into the account that caused it."""
    st["ops_spent"] = st.get("ops_spent", 0) + client.ops_spent
    if client.monthly_remaining is not None:
        st["monthly_remaining_last_seen"] = client.monthly_remaining
    client.ops_spent = 0


# ----------------------------------------------------------- formatting
def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def norm(html: str) -> str:
    return html_mod.unescape(html).replace(" ", " ")


def _heading_counts(html: str) -> dict[str, int]:
    """How many times each heading appears, as a heading."""
    counts: dict[str, int] = {}
    for raw in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S | re.I):
        text = strip_tags(raw)
        if text and "[" not in text:
            counts[text] = counts.get(text, 0) + 1
    return counts


MONEY_RX = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")
PERCENT_RX = re.compile(r"\d+(?:\.\d+)?\s?%")


def figures_in(text: str) -> list[str]:
    """Every money amount and percentage in a string."""
    return MONEY_RX.findall(text) + PERCENT_RX.findall(text)


def _stray_figures(doc: str, allowed: list[str]) -> list[str]:
    """Any money or percentage in the document that we did not supply.

    This is the check that should have existed from the start. Verifying that
    the RIGHT figures are present says nothing about whether WRONG ones are
    also present -- and a run produced an approved, exported letter whose
    opening paragraph announced a price of $25.00, a number that appears
    nowhere in the source data. Every required figure was present, no
    placeholder survived, headings were unique, and the document was still
    false. Presence is not absence.
    """
    ok = set()
    for a in allowed:
        for m in MONEY_RX.findall(a):
            ok.add(m.replace(" ", ""))
        for m in PERCENT_RX.findall(a):
            ok.add(m.replace(" ", ""))

    stray = []
    for found in MONEY_RX.findall(doc) + PERCENT_RX.findall(doc):
        norm_found = found.replace(" ", "")
        if norm_found not in ok:
            stray.append(found)
    return sorted(set(stray))


def verify_fill(updated_html: str, must_appear: list[str],
                template_html: str | None = None,
                allowed_figures: list[str] | None = None) -> list[str]:
    """Deterministic check that the AI used our numbers and left no blanks.

    Returns a list of problems; empty means the document is verified. This is
    the never-bluff rule: a figure the model dropped or altered is caught here,
    not by a human reading the DOCX later.

    The duplication checks below exist because "is every required string
    present, and is every placeholder gone?" is satisfied just as happily by a
    document containing the whole letter seven times over -- which is exactly
    what one run produced when the model pasted its full answer into every
    chunk instead of the one placeholder each chunk held. Presence alone is not
    correctness.
    """
    doc = norm(updated_html)
    problems = [f"missing required text: {s!r}" for s in must_appear if s not in doc]

    leftover = sorted(set(PLACEHOLDER_RX.findall(doc)))
    if leftover:
        problems.append(f"unfilled placeholders remain: {', '.join(leftover)}")

    # No figure may appear that we did not supply.
    for stray in _stray_figures(strip_tags(doc), allowed_figures or must_appear):
        problems.append(
            f"invented figure {stray!r} appears in the document but was never "
            f"supplied; every money amount and percentage must come from the "
            f"pricing engine")

    # A salutation belongs to a letter exactly once.
    salutations = doc.count("Dear ")
    if salutations > 1:
        problems.append(
            f"the letter body repeats: found {salutations} salutations, expected 1 "
            f"(the model likely filled every chunk with the whole document)")

    # Each heading the template defines belongs to the document exactly once.
    #
    # Counted as headings, not as text. Two earlier versions of this check were
    # too blunt and failed perfectly good documents: a per-figure repetition cap
    # tripped because the seat count "80" is a substring of other numbers, and
    # counting heading text anywhere tripped because "Customer" is a heading AND
    # an ordinary word in the body. A check that rejects valid work in order to
    # catch invalid work is not a check worth having.
    if template_html:
        want = _heading_counts(template_html)
        got = _heading_counts(doc)
        for text, n_want in want.items():
            n_got = got.get(text, 0)
            if n_got > n_want:
                problems.append(
                    f"heading {text!r} appears {n_got} times, expected {n_want} "
                    f"(the model likely filled every chunk with the whole document)")

    # Whole-document bloat, as a backstop for duplication the checks above miss.
    if template_html:
        grew = len(strip_tags(doc)) / max(1, len(strip_tags(template_html)))
        if grew > 12:
            problems.append(
                f"document is {grew:.0f}x the template's text length; "
                f"expected roughly 3-8x for a filled letter")

    return problems


# ------------------------------------------------------------- payloads
def account_by_id(accounts: dict, account_id: str) -> dict:
    return next(a for a in accounts["accounts"] if a["account_id"] == account_id)


def quote_values(acct: dict, d: Decision, batch: dict) -> dict[str, str]:
    return {
        "QUOTE_NUMBER": f"RD-{batch['renewal_cycle']}-{acct['account_id']}",
        "QUOTE_DATE": long_date(batch["today"]),
        "VALID_UNTIL": long_date(acct["renewal_date"]),
        "COMPANY_NAME": acct["company"],
        "CONTACT_NAME": acct["contact"]["name"],
        "CONTACT_TITLE": acct["contact"]["title"],
        "CURRENT_PLAN": acct["plan"],
        "CURRENT_SEATS": str(acct["seats_contracted"]),
        "CURRENT_PRICE": money(d.current_price),
        "CURRENT_ANNUAL": money(d.current_annual),
        "RENEWAL_PLAN": acct["plan"],
        "RENEWAL_SEATS": str(d.renewal_seats),
        "RENEWAL_TERM": f"{acct['term_months']} months",
        "RENEWAL_PRICE": money(d.new_price),
        "RENEWAL_ANNUAL": money(d.renewal_annual),
        "ADJUSTMENT_SUMMARY": d.summary_sentence(),
        "RENEWAL_DATE": long_date(acct["renewal_date"]),
    }


def quote_message(values: dict[str, str]) -> str:
    lines = "\n".join(f"  [{k}] -> {v}" for k, v in values.items())
    return (
        "Fill this renewal quote template. Replace every bracketed placeholder "
        "with its exact value from the list below.\n"
        "Rules:\n"
        "- Use each value EXACTLY as written, character for character. Never "
        "recompute, reformat, round, or restyle a number or a date.\n"
        "- Change nothing except the placeholders. All other wording, headings "
        "and table structure stay exactly as they are.\n"
        "- Leave no bracketed placeholder behind.\n\n"
        f"Values:\n{lines}"
    )


def notice_facts(acct: dict) -> str:
    s = acct.get("usage_story") or {}
    feats = "; ".join(s.get("top_feature_adoption", []))
    return (
        f"- Company: {acct['company']} ({acct['plan']} plan)\n"
        f"- Contact: {acct['contact']['name']}, {acct['contact']['title']}\n"
        f"- Contracted seats: {acct['seats_contracted']}, active seats: {acct.get('seats_active')}\n"
        f"- Average monthly API calls: {s.get('api_calls_month_avg'):,} "
        f"(prior year: {s.get('api_calls_prior_year_avg'):,})\n"
        f"- Storage in use: {s.get('storage_gb')} GB\n"
        f"- What they actually use: {feats}\n"
        f"- Support history: {s.get('support')}\n"
        f"- Account notes: {s.get('notes')}"
    )


def notice_message(acct: dict, d: Decision,
                   batch: dict) -> tuple[str, list[str], list[str]]:
    """Build the notice instruction, the strings verification demands, and the
    full set of figures the document is allowed to contain."""
    eff = long_date(acct["renewal_date"])
    drivers = "\n".join(
        f"  - {dr.reason}" + (f" (+{dr.pct:g}%)" if dr.pct else "")
        + (f" [{dr.detail}]" if dr.detail else "")
        for dr in d.drivers
    )
    if d.direction == "increase":
        change_kind = "a price increase"
        pct_token = f"{d.change_pct:.1f}%"
        must = [money(d.current_price), money(d.new_price), pct_token, eff]
        change_line = (
            f"the per-seat price moves from {money(d.current_price)} to "
            f"{money(d.new_price)} per month (an increase of {pct_token}), "
            f"effective {eff}"
        )
    elif d.direction == "decrease":
        change_kind = "a price decrease"
        pct_token = f"{abs(d.change_pct):.1f}%"
        must = [money(d.current_price), money(d.new_price), pct_token, eff]
        change_line = (
            f"the per-seat price moves from {money(d.current_price)} to "
            f"{money(d.new_price)} per month (a decrease of {pct_token}), "
            f"effective {eff}"
        )
    else:
        change_kind = "a renewal confirmation with no price change"
        must = [money(d.new_price), eff]
        change_line = (
            f"the per-seat price is confirmed unchanged at {money(d.new_price)} "
            f"per month for the term starting {eff}"
        )

    churn = "churn_risk" in acct.get("flags", [])
    tone_extra = (
        "\n- This customer is flagged at-risk internally. Acknowledge plainly "
        "that their usage has decreased, invite a right-sizing conversation "
        "before the renewal date, and keep the door open. No pressure tactics. "
        "Never name or hint at an internal risk flag, score, or sentiment "
        "assessment -- that is our data, not theirs."
        if churn else ""
    )

    msg = (
        "Fill this price-change notice template for one specific customer. "
        f"This is {change_kind}.\n\n"
        "AUTHORITATIVE FIGURES (use these exactly; never invent, recompute, or "
        "round any number; no other figures may appear in the document):\n"
        f"  - Current price per seat per month: {money(d.current_price)}\n"
        f"  - Renewal price per seat per month: {money(d.new_price)}\n"
        f"  - Change: {d.change_pct:+.1f}%\n"
        f"  - Effective date: {eff}\n"
        f"  - Renewal seats: {d.renewal_seats}, term: {acct['term_months']} months\n"
        f"  - Named drivers of the change:\n{drivers}\n\n"
        f"FACTS ABOUT THIS ACCOUNT (the only facts you may use):\n{notice_facts(acct)}\n\n"
        "Placeholder instructions:\n"
        f"  [NOTICE_DATE] -> {long_date(batch['today'])}\n"
        f"  [CONTACT_NAME] -> {acct['contact']['name']}\n"
        "  [OPENING_PARAGRAPH] -> one short paragraph: what this letter is and "
        "the single headline change, stated plainly. This letter is unsolicited; "
        "the customer has not asked for anything and nothing has been 'approved'.\n"
        f"  [CHANGE_SUMMARY] -> state that {change_line}. Include the annual "
        f"value at renewal: {money(d.renewal_annual)} for {d.renewal_seats} seats.\n"
        "  [ACCOUNT_SPECIFIC_EXPLANATION] -> 2 to 4 sentences explaining why "
        "this change applies to THIS account, built from the account facts "
        "above: name their actual features, their actual growth or decline, "
        "their actual seat pattern. Tie each named driver to the specific fact "
        "that triggered it. It must read like it was written about this one "
        "customer by someone who knows the account. Generic filler that could "
        "be mail-merged into any letter is a failure.\n"
        "  [UNCHANGED_PARAGRAPH] -> what does not change: plan, features, "
        "support terms, contract terms.\n"
        "  [OPTIONS_PARAGRAPH] -> renew as-is, talk to us before the renewal "
        "date, or exercise notice rights under the agreement.\n\n"
        "Tone rules:\n"
        "- This is a letter TO the customer. Write in the second person: 'your "
        "team', 'you crossed', 'your seat count'. Never refer to them in the "
        "third person by company name or as 'they', and never write 'our plan' "
        "when you mean theirs -- that reads like an internal note, not a letter "
        "someone received.\n"
        "- Do not name the contact anywhere in the body; the salutation already "
        "does that. Do not refer to anyone's leadership or job title.\n"
        "- Plain and direct. No marketing language, no exclamation marks, no "
        "'we are excited to'. Do not use the words 'utilize' or 'leverage'; "
        "'use' is the word.\n"
        "- Do not apologize more than once.\n"
        "- Never invent a number, product name, date, request or fact that is "
        "not listed above."
        + tone_extra +
        "\nReplace every bracketed placeholder. Change nothing else."
    )
    # Everything the document MAY legitimately contain is, by definition,
    # everything the instruction supplied. Deriving the allowlist from the
    # prompt rather than enumerating it by hand is what stops this check
    # rejecting good work: an earlier version listed the figures manually and
    # then failed valid letters over "102%" and "$43.75", both of which the
    # prompt had handed the model itself.
    return msg, must, figures_in(msg) + list(must)


# ------------------------------------------------------------ pipeline
def stop_reason(client: Client, max_ops: int) -> str | None:
    spent = total_ops() + client.ops_spent
    if spent >= max_ops:
        return f"stopping rule: {spent} operations spent >= --max-ops {max_ops}"
    if client.monthly_remaining is not None and client.monthly_remaining < MIN_REMAINING_FLOOR:
        return (f"stopping rule: only {client.monthly_remaining} operations left "
                f"this month (floor {MIN_REMAINING_FLOOR})")
    return None


def _updated_html(out: dict) -> str:
    """The filled document, treating "absent" and "null" as the same thing.

    The service may answer with document_changes.updated_html set to null when it
    made no edit. .get(key, "") does not help there -- a default only applies to a
    missing key, not a present null -- so the None flowed onward and blew up in
    html.unescape with "argument of type NoneType is not iterable", which names
    neither the account nor the cause. An empty string is the honest reading:
    nothing came back, so verification will report the placeholders unfilled.
    """
    changes = out.get("document_changes") or {}
    return changes.get("updated_html") or ""


def _why(e: BaseException) -> str:
    """A failure reason a human can act on.

    SuperDocsError already reads as a sentence. Anything else is a bug here or a
    response shape we did not expect, and str() alone can be empty -- one such
    failure recorded itself as "notice: " with nothing after it.
    """
    return str(e) if isinstance(e, SuperDocsError) else f"{type(e).__name__}: {e}"


def fill_document(client: Client, session_id: str, template_html: str,
                  message: str, must: list[str], tier: str | None,
                  allowed: list[str] | None = None) -> dict:
    """One sync fill + verification + at most one repair turn.

    Returns {"html": ...} or raises SuperDocsError with the problems named. A
    document that fails verification is never exported.
    """
    out = client.chat(message, session_id, document_html=template_html,
                      approval_mode="approve_all", model_tier=tier)
    html = _updated_html(out)
    problems = verify_fill(html, must, template_html, allowed)
    if not problems:
        return {"html": html}
    repair = (
        "The document has verification problems that must be fixed exactly:\n- "
        + "\n- ".join(problems)
        + "\nFix only these. Use the exact values from my previous message."
    )
    out = client.chat(repair, session_id, approval_mode="approve_all", model_tier=tier)
    html = _updated_html(out)
    problems = verify_fill(html, must, template_html, allowed)
    if problems:
        raise SuperDocsError("verification failed after one repair: " + "; ".join(problems))
    return {"html": html}


def export_pair(client: Client, st: dict, account_id: str) -> list[str]:
    files = []
    for kind in ("quote", "notice"):
        sess = st["sessions"][kind]
        name = "renewal-quote" if kind == "quote" else "price-change-notice"
        path = OUT / account_id / f"{name}.docx"
        client.export(sess, "docx", path, filename=name)
        files.append(str(path.relative_to(HERE)).replace("\\", "/"))
    return files


def cmd_plan(_args) -> int:
    decisions, _accounts, _policy = decide_all(DATA)
    print(f"{'account':<10} {'company':<28} {'action':<26} "
          f"{'price':<20} {'pct':>7}  gate")
    print("-" * 105)
    for d in decisions:
        if d.action == "skip":
            print(f"{d.account_id:<10} {d.company[:27]:<28} "
                  f"{'SKIP: ' + d.skip_reason[:60]:<70}")
            continue
        gate = "HUMAN REVIEW" if d.gated else "auto"
        print(f"{d.account_id:<10} {d.company[:27]:<28} {d.direction:<26} "
              f"{money(d.current_price)} -> {money(d.new_price):<9} "
              f"{d.change_pct:>+6.1f}%  {gate}")
        for reason in d.gate_reasons:
            print(f"{'':<10} {'':<28} - {reason}")
    n_skip = sum(1 for d in decisions if d.action == "skip")
    n_gate = sum(1 for d in decisions if d.gated)
    print(f"\n{len(decisions)} accounts: {len(decisions) - n_skip} to process "
          f"({n_gate} will wait at the human gate), {n_skip} deliberately skipped.")
    print("Zero API calls were made. `run` executes this plan.")
    return 0


def cmd_run(args) -> int:
    with BatchLock(f"run {' '.join(sys.argv[1:])}"):
        return _run(args)


def _run(args) -> int:
        decisions, accounts, _policy = decide_all(DATA)
        batch = accounts["batch"]
        batch_state = load_batch()
        if args.fresh or not batch_state.get("nonce"):
            if args.fresh and STATE_DIR.exists():
                for old in STATE_DIR.glob("*.json"):
                    old.unlink()
            batch_state = {"nonce": datetime.now(timezone.utc).strftime("%m%d%H%M")}
            save_batch(batch_state)
        client = Client()

        quote_tpl = (TEMPLATES / "renewal-quote.html").read_text(encoding="utf-8")
        notice_tpl = (TEMPLATES / "price-change-notice.html").read_text(encoding="utf-8")

        processed = 0
        try:
            for d in decisions:
                st = acct_state(d.account_id)
                if d.action == "skip":
                    st.update(status="skipped", skip_reason=d.skip_reason)
                    save_acct(d.account_id, st)
                    print(f"[skip] {d.account_id}: {d.skip_reason}")
                    continue
                if st["status"] in ("exported", "rejected", "awaiting_review"):
                    print(f"[keep] {d.account_id}: already {st['status']}")
                    continue
                if args.only and d.account_id != args.only:
                    continue
                if args.sample and processed >= args.sample:
                    print(f"[stop] --sample {args.sample} reached; remaining accounts untouched")
                    break
                reason = stop_reason(client, args.max_ops)
                if reason:
                    print(f"[stop] {reason}")
                    break

                acct = account_by_id(accounts, d.account_id)
                nonce = batch_state["nonce"]
                # A retry needs its own session. Re-sending a fill into the session
                # that already performed it makes the model answer "nothing to
                # change" and return a null document -- which is how an interrupted
                # account failed forever on every later attempt.
                attempt = int(st.get("attempt", 0)) + 1
                sessions = {
                    "quote": f"rd-{batch['renewal_cycle']}-{nonce}-{d.account_id}-quote-{attempt}",
                    "notice": f"rd-{batch['renewal_cycle']}-{nonce}-{d.account_id}-notice-{attempt}",
                }
                st.update(status="generating", attempt=attempt, sessions=sessions,
                          gated=d.gated, gate_reasons=d.gate_reasons,
                          pricing={"old": d.current_price, "new": d.new_price,
                                   "pct": d.change_pct, "direction": d.direction})
                save_acct(d.account_id, st)
                print(f"[work] {d.account_id} ({d.company}): "
                      f"{money(d.current_price)} -> {money(d.new_price)} "
                      f"({d.change_pct:+.1f}%)"
                      + ("  ** gated for human review" if d.gated else ""))

                # ---- quote: strict deterministic fill, sync ----
                qvals = quote_values(acct, d, batch)
                must_q = [v for k, v in qvals.items() if k != "ADJUSTMENT_SUMMARY"]
                try:
                    q_msg = quote_message(qvals)
                    fill_document(client, sessions["quote"], quote_tpl,
                                  q_msg, must_q, tier=None,
                                  allowed=figures_in(q_msg) + must_q)
                    print("       quote filled and verified")
                except QuotaExhausted:
                    raise  # a spent quota stops the batch; it is not this account failing
                except Exception as e:
                    st.update(status="failed", fail_reason=f"quote: {_why(e)}")
                    settle_ops(st, client)
                    save_acct(d.account_id, st)
                    print(f"       FAILED: {e}")
                    continue

                # ---- notice ----
                n_msg, must_n, allowed_n = notice_message(acct, d, batch)
                if d.gated:
                    try:
                        job_id = client.chat_async(n_msg, sessions["notice"],
                                                   document_html=notice_tpl,
                                                   approval_mode="ask_every_time",
                                                   model_tier="pro")
                        job = client.wait_for_job(job_id, session_id=sessions["notice"])
                        if job.get("status") == "awaiting_approval":
                            changes = parse_pending_changes(
                                (job.get("metadata") or {}).get("pending_changes"))
                            st.update(status="awaiting_review", job_id=job_id,
                                      pending_count=len(changes), must_appear=must_n,
                                  allowed_figures=allowed_n)
                            print(f"       notice drafted; {len(changes)} proposed change(s) "
                                  f"parked at the human gate")
                        elif job.get("status") == "completed":
                            # ask_every_time finished without pausing: the platform gate
                            # did not engage. Do not trust it -- hold the account anyway.
                            st.update(status="awaiting_review", job_id=job_id,
                                      pending_count=0, must_appear=must_n, allowed_figures=allowed_n,
                                      note="completed without platform pause; held locally")
                            print("       WARNING: job completed without pausing; "
                                  "account held for human review anyway")
                        else:
                            st.update(status="failed",
                                      fail_reason=f"notice job {job.get('status')}: "
                                                  f"{job.get('error', 'no detail')}")
                            print(f"       FAILED: notice job {job.get('status')}")
                    except QuotaExhausted:
                        raise
                    except Exception as e:
                        # A held account is the whole point of this batch, so losing
                        # one to a transport hiccup must not lose the other nine.
                        st.update(status="failed", fail_reason=f"notice: {_why(e)}")
                        print(f"       FAILED: {_why(e)}")
                else:
                    try:
                        fill_document(client, sessions["notice"], notice_tpl,
                                      n_msg, must_n, tier="pro",
                                      allowed=allowed_n)
                        st["status"] = "approved_auto"
                        files = export_pair(client, st, d.account_id)
                        st.update(status="exported", files=files)
                        print(f"       notice filled and verified; exported: "
                              f"{', '.join(Path(f).name for f in files)}")
                    except QuotaExhausted:
                        raise
                    except Exception as e:
                        st.update(status="failed", fail_reason=f"notice: {_why(e)}")
                        print(f"       FAILED: {e}")

                processed += 1
                settle_ops(st, client)
                save_acct(d.account_id, st)
        except QuotaExhausted as e:
            print(f"[halt] {e}")

        rem = client.monthly_remaining if client.monthly_remaining is not None else last_remaining()
        print(f"\nOperations spent so far: {total_ops()}"
              + (f" (account has {rem} left this month)" if rem is not None else ""))
        print("Next: `review` to see what is waiting on a human, `report` for the ledger.")
        return 0


def _pending_for(client: Client, st: dict) -> tuple[dict, list]:
    job = client.job(st["job_id"])
    changes = parse_pending_changes((job.get("metadata") or {}).get("pending_changes"))
    return job, changes


def cmd_review(args) -> int:
    waiting = {aid: st for aid, st in all_states().items()
               if st.get("status") == "awaiting_review"}
    if not waiting:
        print("Nothing is waiting on a human.")
        return 0
    client = Client()
    for aid, st in waiting.items():
        print("=" * 78)
        print(f"{aid} -- {money(st['pricing']['old'])} -> {money(st['pricing']['new'])} "
              f"({st['pricing']['pct']:+.1f}%)")
        for r in st.get("gate_reasons", []):
            print(f"  gate: {r}")
        for rev in st.get("revisions", []):
            print(f"  previously sent back by {rev['by']}: {rev['feedback'][:90]}")
        job, changes = _pending_for(client, st)
        if not changes:
            print(f"  job status: {job.get('status')}; no pending changes "
                  f"(note: {st.get('note', '-')})")
            continue
        for i, c in enumerate(changes, 1):
            print(f"  change {i}/{len(changes)} [{c.get('operation')}] "
                  f"{c.get('ai_explanation', '')[:100]}")
            old_t = strip_tags(c.get("old_html") or "")
            new_t = strip_tags(c.get("new_html") or "")
            for line in difflib.unified_diff(old_t.split(". "), new_t.split(". "),
                                             lineterm="", n=0):
                if line.startswith(("---", "+++", "@@")):
                    continue
                print(f"    {line[:110]}")
        print(f"  -> decide with: python renewal_desk.py decide {aid} "
              f"approve | revise --feedback '...' | reject")
        settle_ops(st, client)
        save_acct(aid, st)
    return 0


def cmd_decide(args) -> int:
    with BatchLock(f"decide {args.account_id} {args.verdict}"):
        return _decide(args)


def _decide(args) -> int:
        st = acct_state(args.account_id)
        if st.get("status") != "awaiting_review":
            print(f"{args.account_id} is not awaiting review (status: {st.get('status')})")
            return 1
        client = Client()
        sess = st["sessions"]["notice"]
        job, changes = _pending_for(client, st)
        stamp = datetime.now(timezone.utc).isoformat()

        if args.verdict == "approve":
            if changes:
                client.approve(sess, st["job_id"],
                               [{"change_id": c["change_id"], "approved": True} for c in changes],
                               approved_default=True)
                job = client.wait_for_job(st["job_id"], session_id=sess)
            html = ((job.get("result") or {}).get("document_changes") or {}).get("updated_html", "")
            tpl = (TEMPLATES / "price-change-notice.html").read_text(encoding="utf-8")
            problems = (verify_fill(html, st.get("must_appear", []), tpl,
                                    st.get("allowed_figures")) if html else [])
            if problems:
                st.update(status="failed",
                          fail_reason="post-approval verification: " + "; ".join(problems))
                print("Approved changes failed verification; account marked failed:\n  - "
                      + "\n  - ".join(problems))
            else:
                st["decision"] = {"verdict": "approved", "by": args.by, "at": stamp}
                files = export_pair(client, st, args.account_id)
                st.update(status="exported", files=files)
                print(f"Approved and exported: {', '.join(files)}")

        elif args.verdict == "revise":
            if not args.feedback:
                print("revise needs --feedback 'what to change'")
                return 1
            # Step 1: deny, on the record, with the reviewer's reason attached.
            if changes:
                client.approve(sess, st["job_id"],
                               [{"change_id": c["change_id"], "approved": False} for c in changes],
                               approved_default=False, feedback=args.feedback)
                job = client.wait_for_job(st["job_id"], session_id=sess)
                if job.get("status") == "awaiting_approval":
                    changes = parse_pending_changes(
                        (job.get("metadata") or {}).get("pending_changes"))
                    st.setdefault("revisions", []).append(
                        {"feedback": args.feedback, "by": args.by, "at": stamp})
                    st.update(pending_count=len(changes), status="awaiting_review")
                    settle_ops(st, client)
                    save_acct(args.account_id, st)
                    print(f"Revised draft is back at the gate with {len(changes)} "
                          f"proposed change(s). Run `review` again.")
                    return 0

            # Step 2: the denial settled the job without re-proposing. A revision
            # that never paused is a revision nobody reviewed, so re-draft it as a
            # fresh gated turn rather than quietly accepting whatever landed.
            decisions, accounts, _policy = decide_all(DATA)
            d = next(x for x in decisions if x.account_id == args.account_id)
            acct = account_by_id(accounts, args.account_id)
            base_msg, must, allowed = notice_message(acct, d, accounts["batch"])
            redraft = (base_msg + "\n\nREVIEWER FEEDBACK on the previous draft, which "
                       "was rejected. Address it exactly:\n" + args.feedback)
            tpl = (TEMPLATES / "price-change-notice.html").read_text(encoding="utf-8")
            job_id = client.chat_async(redraft, sess, document_html=tpl,
                                       approval_mode="ask_every_time", model_tier="pro")
            job = client.wait_for_job(job_id, session_id=sess)
            st.setdefault("revisions", []).append(
                {"feedback": args.feedback, "by": args.by, "at": stamp, "redrafted": True})
            if job.get("status") == "awaiting_approval":
                changes = parse_pending_changes((job.get("metadata") or {}).get("pending_changes"))
                st.update(status="awaiting_review", job_id=job_id,
                          pending_count=len(changes), must_appear=must,
                      allowed_figures=allowed)
                print(f"Re-drafted from the template with your feedback; back at the "
                      f"gate with {len(changes)} proposed change(s). Run `review` again.")
            else:
                st.update(status="failed", fail_reason=f"re-draft job ended {job.get('status')}")
                print(f"Re-draft job ended {job.get('status')}; account marked failed.")

        elif args.verdict == "reject":
            if changes:
                client.approve(sess, st["job_id"],
                               [{"change_id": c["change_id"], "approved": False} for c in changes],
                               approved_default=False,
                               feedback=args.feedback or
                               "Rejected by reviewer. This notice will not be sent.")
            st["decision"] = {"verdict": "rejected", "by": args.by,
                              "reason": args.feedback or "rejected at the gate", "at": stamp}
            st.update(status="rejected")
            print(f"{args.account_id} rejected. Nothing will be exported for it, "
                  f"and the rejection is on the record.")

        settle_ops(st, client)
        save_acct(args.account_id, st)
        return 0


def cmd_finalize(_args) -> int:
    with BatchLock("finalize"):
        return _finalize()


def _finalize() -> int:
        client = Client()
        n = 0
        for aid, st in all_states().items():
            if st.get("status") == "approved_auto":
                files = export_pair(client, st, aid)
                st.update(status="exported", files=files)
                settle_ops(st, client)
                save_acct(aid, st)
                n += 1
        print(f"exported {n} account(s)")
        return 0


def cmd_report(_args) -> int:
    decisions, accounts, policy = decide_all(DATA)
    states = all_states()
    rem = last_remaining(states)

    lines = ["# Renewal batch report",
             "",
             f"- Cycle: **{accounts['batch']['renewal_cycle']}** | run date "
             f"{accounts['batch']['today']} | policy {policy['policy_version']}",
             f"- Operations spent: **{total_ops()}**"
             + (f" ({rem} remaining on the account)" if rem is not None else ""),
             ""]

    incomplete = []
    rows = ["| Account | Company | Price | Change | Gate | Status | Files |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    skipped = []
    for d in decisions:
        st = states.get(d.account_id, {"status": "not_started"})
        status = st["status"]
        if d.action == "skip":
            skipped.append((d.account_id, d.company, d.skip_reason))
            continue
        if status not in ("exported", "rejected"):
            incomplete.append((d.account_id, status))
        gate = "; ".join(d.gate_reasons) if d.gated else "auto"
        decision = st.get("decision", {})
        shown = status + (f" ({decision.get('verdict')})" if decision else "")
        revs = len(st.get("revisions", []))
        if revs:
            shown += f", {revs} revision(s)"
        files = "<br/>".join(Path(f).name for f in st.get("files", [])) or "-"
        rows.append(f"| {d.account_id} | {d.company} | "
                    f"{money(d.current_price)} -> {money(d.new_price)} | "
                    f"{d.change_pct:+.1f}% | {gate} | {shown} | {files} |")

    lines += ["## Processed accounts", ""] + rows + ["",
              "## Deliberately not processed", "",
              "| Account | Company | Why |", "| --- | --- | --- |"]
    for aid, company, why in skipped:
        lines.append(f"| {aid} | {company} | {why} |")

    rejected = [(aid, st) for aid, st in states.items()
                if st.get("status") == "rejected"]
    if rejected:
        lines += ["", "## Rejected at the gate", "",
                  "| Account | Reviewer | Reason |", "| --- | --- | --- |"]
        for aid, st in rejected:
            dec = st.get("decision", {})
            lines.append(f"| {aid} | {dec.get('by', '-')} | {dec.get('reason', '-')} |")

    lines += ["", "## Batch completeness", ""]
    if incomplete:
        lines.append("**INCOMPLETE.** The gate is holding it open:")
        for aid, status in incomplete:
            lines.append(f"- {aid}: {status}")
        lines.append("")
        lines.append("The batch is complete only when every non-skipped account "
                     "is exported or explicitly rejected by a human.")
    else:
        lines.append("**COMPLETE.** Every non-skipped account was exported or "
                     "explicitly rejected; every skip has a named reason above.")

    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / "batch-report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten to {report}")
    return 1 if incomplete else 0


def cmd_serve(args) -> int:
    """The review console. The gate is easier to hold when you can read the letter."""
    from web_server import serve

    serve(args.port)
    return 0


def cmd_setup_templates(_args) -> int:
    client = Client()
    for f in ("renewal-quote.html", "price-change-notice.html"):
        out = client.upload_template(TEMPLATES / f)
        print(f"uploaded {f}: {out.get('template_id', out)}")
    listing = client.list_templates()
    n = len(listing.get("templates", listing if isinstance(listing, list) else []))
    print(f"library now holds {n} template(s)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="renewal_desk", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)

    r = sub.add_parser("run")
    r.add_argument("--sample", type=int, default=0,
                   help="process at most N accounts (day-one learning mode)")
    r.add_argument("--max-ops", type=int, default=60,
                   help="stopping rule: halt once this many operations are spent")
    r.add_argument("--only", help="process a single account id")
    r.add_argument("--fresh", action="store_true",
                   help="new batch state and new sessions")
    r.set_defaults(fn=cmd_run)

    sub.add_parser("review").set_defaults(fn=cmd_review)

    dcd = sub.add_parser("decide")
    dcd.add_argument("account_id")
    dcd.add_argument("verdict", choices=["approve", "revise", "reject"])
    dcd.add_argument("--feedback", default="")
    dcd.add_argument("--by", default="reviewer")
    dcd.set_defaults(fn=cmd_decide)

    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=7000)
    sv.set_defaults(fn=cmd_serve)

    sub.add_parser("finalize").set_defaults(fn=cmd_finalize)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sub.add_parser("setup-templates").set_defaults(fn=cmd_setup_templates)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except SuperDocsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
