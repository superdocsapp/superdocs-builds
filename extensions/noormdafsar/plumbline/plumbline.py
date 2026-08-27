#!/usr/bin/env python3
"""Plumbline -- documentation that stays true to the code.

A plumb line tells you whether a wall is true. This tells you whether a document
still is.

    scan     what the code actually says, read from the AST   (no API calls)
    check    extract the document's claims and verify them     (SuperDocs)
    fix      draft corrections, held at a human gate           (SuperDocs)
    decide   approve or reject a drafted correction
    apply    write the approved document back to the repository
    serve    the same review gate as an MCP server for coding agents

The division of labour is the whole idea: a model is good at reading English and
pulling typed claims out of it, and bad at being authoritative about a function
signature. Python's `ast` is the reverse. So the model extracts claims, `ast`
decides the truth, and the two are compared.

Standard library only. Key from SUPERDOCS_API_KEY, .env, or the agent store.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from claims import Drift, check, parse_claims
from extract import build_prompt, parse_table
from codefacts import read_tree
from superdocs_client import Client, SuperDocsError, parse_pending_changes

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
STATE = OUT / "state.json"

SEVERITY_ORDER = {"breaking": 0, "stale": 1, "unverifiable": 2}


# ------------------------------------------------------------------- state
def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# -------------------------------------------------------------------- scan
def cmd_scan(args) -> int:
    facts = read_tree(Path(args.code))
    print(f"{len(facts.functions)} function(s), {len(facts.constants)} constant(s) "
          f"in {args.code}\n")
    for name, c in sorted(facts.constants.items()):
        print(f"  {c.file}:{c.line:<4} {name} = {c.value}")
    print()
    for name, f in sorted(facts.functions.items()):
        print(f"  {f.file}:{f.line:<4} {f.signature()}")
        if f.raises:
            print(f"{'':>12}raises {', '.join(f.raises)}")
    print("\nRead from the AST. No model was involved and no API call was made.")
    return 0


# ------------------------------------------------------------------- check
def extract_claims(client: Client, doc_html: str, facts, session: str) -> tuple[list, list]:
    """Ask SuperDocs to write the claims table, then read it back.

    The intermediate artefact is a real document, which is worth more than a
    hidden JSON payload: `out/claims.md` can be opened and argued with.
    """
    doc_text = strip_tags(doc_html)
    client.chat(build_prompt(doc_text, facts.symbols()), session,
                approval_mode="approve_all", model_tier="pro")
    table_md = client.export_text(session, "markdown")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "claims.md").write_text(table_md, encoding="utf-8")

    rows = parse_table(table_md)
    return parse_claims({"claims": rows}, doc_text)


def cmd_check(args) -> int:
    facts = read_tree(Path(args.code))
    doc_path = Path(args.doc)
    doc_html = doc_path.read_text(encoding="utf-8")

    client = Client()
    session = f"plumbline-{doc_path.stem}-claims"
    claims, dropped = extract_claims(client, doc_html, facts, session)
    drifts, verified = check(claims, facts)

    st = load_state()
    st.update({
        "doc": str(doc_path),
        "code": args.code,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "claims": len(claims),
        "verified": len(verified),
        "dropped": dropped,
        "drifts": [d.as_dict() for d in drifts],
        "status": "drift" if drifts else "true",
    })
    save_state(st)
    _print_report(claims, verified, drifts, dropped)
    return 1 if drifts else 0


def _print_report(claims, verified, drifts: list[Drift], dropped) -> None:
    print(f"{len(claims)} checkable claim(s) extracted from the document")
    print(f"  {len(verified)} verified against the code")
    print(f"  {len(drifts)} drifted")
    if dropped:
        print(f"  {len(dropped)} discarded as ungrounded:")
        for d in dropped:
            print(f"      - {d}")
    if not drifts:
        print("\nThe document is true to the code. Nothing to fix.")
        return
    print()
    for d in sorted(drifts, key=lambda x: SEVERITY_ORDER.get(x.severity, 9)):
        print(f"  [{d.severity:<12}] {d.claim.symbol}"
              + (f".{d.claim.parameter}" if d.claim.parameter else ""))
        print(f"      document : {d.claim.value}")
        print(f"      code     : {d.truth}   ({d.where})")
        print(f"      quote    : “{d.claim.quote[:96]}”")
        print()
    print("`fix` drafts corrections for these and holds them at a human gate.")


# --------------------------------------------------------------------- fix
def _fix_message(drifts: list[Drift]) -> tuple[str, list[str]]:
    lines, musts = [], []
    for i, d in enumerate(drifts, 1):
        lines.append(
            f"{i}. In the sentence: “{d.claim.quote}”\n"
            f"   The document says {d.claim.value!r}. The code says {d.truth!r} "
            f"({d.where}). Correct the document to match the code."
        )
        if d.severity != "breaking":
            musts.append(d.truth)
    msg = (
        "This document has drifted from the code it describes. Correct only the "
        "statements listed below.\n\n"
        + "\n".join(lines)
        + "\n\nRules:\n"
        "- Change ONLY these statements. Every other sentence, heading and code "
        "sample stays exactly as it is.\n"
        "- Use the code's value verbatim. Do not reword the surrounding sentence "
        "beyond what the correction requires.\n"
        "- Where the document describes a parameter that does not exist, remove "
        "that description cleanly rather than inventing a replacement.\n"
        "- Do not add notes, changelogs, or comments about having made the edit."
    )
    return msg, musts


_BLOCK_RX = re.compile(r"<(p|h[1-6]|li)\b[^>]*>(.*?)</\1>", re.S | re.I)


def _blocks(html: str) -> list[str]:
    return [strip_tags(m.group(2)) for m in _BLOCK_RX.finditer(html)]


_SENTENCE_RX = re.compile(r"[^.!?]+[.!?]|[^.!?]+$")


def _sentences(html: str) -> list[str]:
    out = []
    for block in _blocks(html):
        for s in _SENTENCE_RX.findall(block):
            s = _norm_ws(s)
            if s:
                out.append(s)
    return out


def collateral_edits(before_html: str, after_html: str, quotes: list[str]) -> list[str]:
    """Sentences that changed without being asked to.

    Verifying that the corrections landed says nothing about what else moved. On
    the first real run this tool corrected all five drifts and also quietly
    deleted the word "region" from a sentence it had no business touching, and
    added a parameter to another. Both passed every check, because every check
    was looking only at what was supposed to change.

    Compared sentence by sentence rather than paragraph by paragraph, because
    the first version of this guard ran at paragraph granularity and found
    nothing: the deletion happened inside the same paragraph as a legitimate
    correction, so the whole paragraph counted as fair game. Precision has to
    match the size of the thing being protected.
    """
    protected = [_norm_ws(q) for q in quotes if q.strip()]
    before, after = _sentences(before_html), _sentences(after_html)
    after_set = set(after)

    out: list[str] = []
    for s in before:
        if s in after_set:
            continue                                   # survived untouched
        if any(p in s or s in p for p in protected):
            continue                                   # this one was meant to change
        out.append(f"a sentence was altered or removed without being part of the "
                   f"fix:\n        “{s[:120]}”")
    return out


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def carries(text: str, value: str) -> bool:
    """Does this text contain the code's value?

    The code's value comes from the AST as source text, so a string constant
    arrives as `'EUR'` with its quotes. Prose writes it as EUR. Comparing the
    two literally is why the pre-gate check and the post-approval check
    disagreed with each other about the same document -- one stripped quotes and
    the other did not. One helper, used by both, ends that.
    """
    return value.strip("'\"") in text


def _missing_from(changes: list[dict], musts: list[str]) -> list[str]:
    """Which required values the proposed edit does not yet contain."""
    proposed = strip_tags(" ".join(c.get("new_html") or "" for c in changes))
    return [m for m in musts if not carries(proposed, m)]


def cmd_fix(args) -> int:
    st = load_state()
    if st.get("status") != "drift":
        print("Nothing to fix. Run `check` first.")
        return 0

    drifts = [Drift(
        claim=type("C", (), {**d, "quote": d["quote"], "symbol": d["symbol"],
                             "value": d["claimed"], "parameter": d["parameter"],
                             "kind": d["kind"]})(),
        truth=d["actual"], where=d["where"], severity=d["severity"], detail=d["detail"],
    ) for d in st["drifts"]]

    doc_path = Path(st["doc"])
    client = Client()
    session = f"plumbline-{doc_path.stem}-fix-{int(datetime.now().timestamp())}"
    msg, musts = _fix_message(drifts)

    job_id = client.chat_async(msg, session,
                               document_html=doc_path.read_text(encoding="utf-8"),
                               approval_mode="ask_every_time", model_tier="pro")
    job = client.wait_for_job(job_id, session_id=session)
    if job.get("status") != "awaiting_approval":
        st.update(status="fix_failed", fail_reason=f"job ended {job.get('status')}")
        save_state(st)
        print(f"The fix job ended {job.get('status')} instead of pausing for review.")
        return 2

    changes = parse_pending_changes((job.get("metadata") or {}).get("pending_changes"))

    # Do not spend a reviewer's attention on a draft we already know is
    # incomplete. The first pass routinely corrects one paragraph and stops, so
    # the proposal is checked for every required value BEFORE the gate, and sent
    # back automatically until it is whole. The human sees one complete draft,
    # not three partial ones.
    for attempt in range(2):
        missing = _missing_from(changes, musts)
        if not missing:
            break
        print(f"  draft {attempt + 1} corrected only some of the drift; "
              f"still missing {', '.join(missing)} — asking again")
        client.approve(session, job_id,
                       [{"change_id": c["change_id"], "approved": False} for c in changes],
                       approved_default=False,
                       feedback="Incomplete. You corrected some statements and left "
                                "others untouched. Every one of these values must "
                                "appear in the document: " + ", ".join(missing)
                                + ". Correct every listed statement in one pass.")
        job = client.wait_for_job(job_id, session_id=session)
        if job.get("status") == "awaiting_approval":
            changes = parse_pending_changes(
                (job.get("metadata") or {}).get("pending_changes"))
            continue
        # the denial settled the job; re-issue the whole edit as a fresh turn
        job_id = client.chat_async(msg, session,
                                   document_html=doc_path.read_text(encoding="utf-8"),
                                   approval_mode="ask_every_time", model_tier="pro")
        job = client.wait_for_job(job_id, session_id=session)
        if job.get("status") != "awaiting_approval":
            break
        changes = parse_pending_changes((job.get("metadata") or {}).get("pending_changes"))

    still_missing = _missing_from(changes, musts)
    st.update(status="awaiting_review", session=session, job_id=job_id,
              must_appear=musts, pending=len(changes))
    save_state(st)

    print(f"{len(changes)} correction(s) drafted and held for review.\n")
    if still_missing:
        print(f"  NOTE: after two attempts the draft still does not carry "
              f"{', '.join(still_missing)}. Approving it will be refused; "
              f"reject and correct those by hand.\n")
    for i, c in enumerate(changes, 1):
        print(f"  correction {i}/{len(changes)}")
        print(f"    was : {strip_tags(c.get('old_html') or '')[:150]}")
        print(f"    now : {strip_tags(c.get('new_html') or '')[:150]}")
        print()
    print("`decide approve` accepts them, `decide reject` discards them. Nothing "
          "is written to the repository until you approve.")
    return 0


# ------------------------------------------------------------------ decide
def cmd_decide(args) -> int:
    st = load_state()
    if st.get("status") != "awaiting_review":
        print(f"Nothing is awaiting review (status: {st.get('status', 'none')}).")
        return 1

    client = Client()
    job = client.job(st["job_id"])
    changes = parse_pending_changes((job.get("metadata") or {}).get("pending_changes"))
    approve = args.verdict == "approve"

    if changes:
        client.approve(st["session"], st["job_id"],
                       [{"change_id": c["change_id"], "approved": approve} for c in changes],
                       approved_default=approve,
                       feedback=None if approve else (args.reason or "rejected by reviewer"))
        job = client.wait_for_job(st["job_id"], session_id=st["session"])

    if not approve:
        st.update(status="rejected", decision={"verdict": "reject", "by": args.by,
                                               "reason": args.reason,
                                               "at": datetime.now(timezone.utc).isoformat()})
        save_state(st)
        print("Rejected. The document is untouched and the drift is still on the record.")
        return 0

    html = ((job.get("result") or {}).get("document_changes") or {}).get("updated_html", "")
    text = strip_tags(html)
    missing = [m for m in st.get("must_appear", []) if not carries(text, m)]
    if missing:
        st.update(status="fix_failed",
                  fail_reason="approved edit did not carry the code's values: "
                              + ", ".join(missing))
        save_state(st)
        print("The approved edit does not contain the values it was supposed to "
              "correct to:\n  - " + "\n  - ".join(missing)
              + "\nNothing was written. Run `fix` again.")
        return 2

    # And nothing else may have moved.
    original = Path(st["doc"]).read_text(encoding="utf-8")
    quotes = [d["quote"] for d in st.get("drifts", [])]
    collateral = collateral_edits(original, html, quotes)
    if collateral and not args.allow_collateral:
        st.update(status="fix_failed",
                  fail_reason="edit touched paragraphs outside the fix: "
                              + "; ".join(c.splitlines()[0] for c in collateral))
        save_state(st)
        print("The approved edit changed parts of the document it was not asked "
              "to change:\n  - " + "\n  - ".join(collateral)
              + "\n\nNothing was written. Run `fix` again, or re-run with "
                "--allow-collateral if these edits are genuinely wanted.")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    staged = OUT / "corrected.html"
    staged.write_text(html, encoding="utf-8")
    st.update(status="approved", staged=str(staged),
              decision={"verdict": "approve", "by": args.by,
                        "at": datetime.now(timezone.utc).isoformat()})
    save_state(st)
    print(f"Approved and staged at {staged.relative_to(HERE)}.\n"
          f"`apply` writes it over {st['doc']}; until then the repository is untouched.")
    return 0


# ------------------------------------------------------------------- apply
def cmd_apply(args) -> int:
    st = load_state()
    if st.get("status") != "approved":
        print(f"Nothing approved to apply (status: {st.get('status', 'none')}).")
        return 1
    doc = Path(st["doc"])
    staged = Path(st["staged"])
    backup = OUT / (doc.name + ".before")
    backup.write_text(doc.read_text(encoding="utf-8"), encoding="utf-8")
    doc.write_text(staged.read_text(encoding="utf-8"), encoding="utf-8")
    st.update(status="applied", backup=str(backup))
    save_state(st)
    print(f"Written to {doc}.")
    print(f"The previous version is at {backup.relative_to(HERE)}, and `git diff` "
          f"shows exactly what changed.")
    return 0


# ------------------------------------------------------------------- serve
def cmd_serve(args) -> int:
    from mcp_server import main as mcp_main

    mcp_main()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="plumbline", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="what the code says (no API calls)")
    s.add_argument("--code", default="sample-repo/meridian_sdk")
    s.set_defaults(fn=cmd_scan)

    c = sub.add_parser("check", help="verify the document's claims against the code")
    c.add_argument("--code", default="sample-repo/meridian_sdk")
    c.add_argument("--doc", default="sample-repo/docs/api-reference.html")
    c.set_defaults(fn=cmd_check)

    f = sub.add_parser("fix", help="draft corrections, held at a human gate")
    f.set_defaults(fn=cmd_fix)

    d = sub.add_parser("decide")
    d.add_argument("verdict", choices=["approve", "reject"])
    d.add_argument("--allow-collateral", action="store_true",
                   help="accept edits to paragraphs the fix did not name")
    d.add_argument("--reason", default="")
    d.add_argument("--by", default="reviewer")
    d.set_defaults(fn=cmd_decide)

    sub.add_parser("apply", help="write the approved document into the repo").set_defaults(fn=cmd_apply)
    sub.add_parser("serve", help="run as an MCP server for coding agents").set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except SuperDocsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
