"""The command line.

`check` and `build` need no key and no network, which is deliberate: everything
this project actually guarantees -- the card matching the manual, the diagrams
being reproducible, a translation keeping its shape -- is checkable before
anything is uploaded. `publish` and `edit` are the two commands that spend
quota.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from manualbuilder import localize as lz
from manualbuilder import paginate as pg
from manualbuilder import projections as pj
from manualbuilder import session
from manualbuilder import verify as vf
from manualbuilder.spec import SpecError, load_spec

DEFAULT_SPEC = Path("spec/halyard_m1.yaml")
LOCALES = Path("locales")
OUT = Path("out")


# ---------------------------------------------------------------- style --
# Four codes, the same ones `selftest` and `demo` already use, so a color
# means the same thing everywhere in this project: bold for a heading, dim
# for something advisory, green for done, red for blocked or wrong. Gated on
# `isatty()` so a redirected or piped run -- including every test, since
# pytest's captured stdout is never a tty -- gets plain text, not escape
# codes sitting in a log file.


def _style(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def _bold(text: str) -> str:
    return _style("1", text)


def _dim(text: str) -> str:
    return _style("2", text)


def _green(text: str) -> str:
    return _style("32", text)


def _red(text: str) -> str:
    return _style("31", text)


def _next(*lines: str) -> None:
    """A suggestion for what to run next, styled the same way everywhere.

    Not printed after every command -- only where a batch was just parked or
    just applied, the two moments where "what do I do with this" is a real
    question and not noise on top of an answer that already said everything.
    """
    for line in lines:
        print(_dim(f"  next  {line}"))


def _spec(args):
    return load_spec(args.spec)


def _spec_for(args):
    """The spec the published pair was rendered from, locale and all.

    A pair published in German is checked against the German spec or not
    checked at all: the passages `verify` and `drifted` look for are the ones
    that were rendered into the documents, not the ones in `spec/`. The
    language comes from the flag if there is one and from `published.json` if
    there is not, because that is where `publish` wrote what it published.
    """
    spec = _spec(args)
    language = getattr(args, "language", "") or _saved_language()
    if not language:
        return spec
    locales = _locales(spec)
    if language not in locales:
        raise SpecError(f"no locales/{language}.yaml, and {OUT / STATE} says the pair is in it")
    return locales[language]


def _saved_language() -> str:
    path = OUT / STATE
    if not path.is_file():
        return ""
    return json.loads(path.read_text(encoding="utf-8")).get("language", "")


def _locales(spec):
    """Every locale file next to the spec, keyed by language."""
    if not LOCALES.is_dir():
        return {}
    out = {}
    for path in sorted(LOCALES.glob("*.yaml")):
        locale = lz.load_locale(path)
        out[locale["language"]] = lz.localised_spec(spec, locale)
    return out


# ------------------------------------------------------------- offline --


def cmd_check(args) -> int:
    """Validate the spec and every locale. No network, no key."""
    spec = _spec(args)
    print(
        f"spec        {spec.name} rev {spec.revision} — "
        f"{len(spec.parts)} parts, {len(spec.steps)} steps, "
        f"{len(spec.warnings)} warnings, {len(spec.faults)} faults"
    )

    manual = pj.manual_html(spec)
    card = pj.quick_start_html(spec)

    # The consistency claim, checked rather than trusted.
    for step in spec.quick_start():
        if step.body not in manual or step.body not in card:
            print(f"  {_red('FAIL')}  step {step.id!r} differs between the two documents")
            return 1
    for fault in spec.quick_start_troubleshooting():
        if fault.fix not in manual or fault.fix not in card:
            print(f"  {_red('FAIL')}  fix {fault.id!r} differs between the two documents")
            return 1
    print(
        f"card        {len(spec.quick_start_steps)} of {len(spec.steps)} steps and "
        f"{len(spec.quick_start_faults)} of {len(spec.faults)} fixes, "
        f"every word identical to the manual"
    )

    layouts = {
        "manual": pg.paginate(pj.manual_blocks(spec), pg.PAGE),
        "card": pg.paginate(pj.quick_start_blocks(spec), pg.PANEL),
    }
    print(
        f"{'layout':<11} manual {layouts['manual'].pages} pages, fullest "
        f"{layouts['manual'].tightest()[1]:.0%}; card "
        f"{layouts['card'].pages} panels, fullest "
        f"{layouts['card'].tightest()[1]:.0%}"
    )
    for name, layout in layouts.items():
        unit = "page" if name == "manual" else "panel"
        for block_id, excess in layout.overflows():
            print(f"  {_red('FAIL')}  {block_id} overruns its {unit} by {excess} lines")
            return 1

    failures = 0
    for language, localised in sorted(_locales(spec).items()):
        problem = _check_locale(spec, localised, language, layouts)
        if problem:
            print(f"  {_red('FAIL')}  {problem}")
            failures += 1
            continue
        ratio = len(pj.manual_html(localised)) / len(manual)
        tightest = max(
            pg.paginate(pj.manual_blocks(localised), pg.PAGE).tightest()[1],
            pg.paginate(pj.quick_start_blocks(localised), pg.PANEL).tightest()[1],
        )
        print(
            f"{'locale ' + language:<11} same page for every block, text "
            f"{ratio:.0%} of source, {1 - tightest:.0%} headroom"
        )

    print(_green("ok") if not failures else _red(f"{failures} locale(s) would repaginate"))
    return 1 if failures else 0


def _check_locale(spec, localised, language: str, layouts) -> str | None:
    """Structure first, then pagination. Returns the problem, or None.

    The order is deliberate: a missing heading and a page that moved have the
    same symptom in print, and reporting the heading is what tells somebody
    which one it is.
    """
    try:
        lz.assert_same_structure(pj.manual_html(spec), pj.manual_html(localised), language)
        lz.assert_same_structure(
            pj.quick_start_html(spec), pj.quick_start_html(localised), language
        )
        pg.assert_same_pagination(
            layouts["manual"],
            pg.paginate(pj.manual_blocks(localised), pg.PAGE),
            language,
            "manual",
        )
        pg.assert_same_pagination(
            layouts["card"],
            pg.paginate(pj.quick_start_blocks(localised), pg.PANEL),
            language,
            "card",
        )
    except (lz.LocaleError, pg.PaginationError) as exc:
        return str(exc)
    return None


def cmd_build(args) -> int:
    """Render everything to `out/`. No network, no key."""
    spec = _spec(args)
    OUT.mkdir(exist_ok=True)

    # A diagram is drawn from the parts graph, and a localised spec is a parts
    # graph with German labels in it -- so every language gets its own drawings
    # from the same renderer rather than the English ones with a translation
    # around them. Nothing is redrawn by hand and no model is in this path.
    sources = {"": spec} | dict(sorted(_locales(spec).items()))
    images: dict[str, dict[str, str]] = {}
    written = 0
    for language, source in sources.items():
        suffix = f".{language}" if language else ""
        images[language] = {}
        for image_id, svg in session.render_diagrams(source).items():
            name = f"{image_id.replace(':', '_')}{suffix}.svg"
            (OUT / name).write_text(svg, encoding="utf-8")
            images[language][image_id] = name  # a local path, so out/ opens
            written += 1

    documents = [("manual", spec, pj.manual_blocks, pg.PAGE, "")]
    documents.append(("quickstart", spec, pj.quick_start_blocks, pg.PANEL, ""))
    for language, localised in sorted(_locales(spec).items()):
        documents.append((f"manual.{language}", localised, pj.manual_blocks, pg.PAGE, language))
        documents.append(
            (
                f"quickstart.{language}",
                localised,
                pj.quick_start_blocks,
                pg.PANEL,
                language,
            )
        )

    for name, source, builder, box, language in documents:
        blocks = builder(source, images[language])
        (OUT / f"{name}.html").write_text(pj.render(blocks), encoding="utf-8")
        (OUT / f"{name}.preview.html").write_text(
            _preview(name, blocks, pg.paginate(blocks, box), language), encoding="utf-8"
        )

    print(f"{written} diagrams and {len(documents)} documents in {OUT}/")
    _next(
        f"open {OUT}/manual.preview.html to see where the pages break",
        "manualbuilder publish (needs a key) to put these on the service",
    )
    return 0


def _preview(title: str, blocks, layout, language: str) -> str:
    """The document with the page boundaries drawn on it.

    `*.html` is what gets uploaded: the bare chunks, no wrapper, because that is
    what makes a chunk-level edit provable. This file is the same body with a
    stylesheet and a rule drawn wherever `paginate` says a page ends. It exists
    so the pagination claim can be looked at instead of taken on trust -- open
    the English and the German side by side and the rules land in the same
    places.
    """
    by_id = {block.id: block for block in blocks}
    parts: list[str] = []
    page = 0
    for placement in layout.placements:
        if placement.page != page:
            page = placement.page
            parts.append(f'<hr class="pagebreak" data-page="{page}">')
        if placement.rows and placement.rows[0] > 0:
            continue  # a table continuing overleaf
        parts.append(by_id[placement.block_id].html)

    lang = f' lang="{language}"' if language else ""
    return (
        f'<!doctype html><meta charset="utf-8"><title>{title}</title>'
        f"<style>{_PREVIEW_CSS}</style>"
        f"<body{lang}><main>" + "\n".join(parts) + "</main></body>"
    )


_PREVIEW_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; background: #f2f0ec; font: 16px/1.55 Charter, Georgia, serif;
       color: #14110d; }
main { max-width: 46rem; margin: 0 auto; padding: 3rem 2rem 6rem; }
h1 { font-size: 2rem; margin: 0 0 .4rem; letter-spacing: -.01em; }
h2 { font-size: 1.35rem; margin: 2.4rem 0 .6rem;
     border-bottom: 2px solid #14110d; padding-bottom: .25rem; }
h3 { font-size: 1.1rem; margin: 1.8rem 0 .4rem; }
p { margin: 0 0 .8rem; }
strong { letter-spacing: .01em; }
figure { margin: 1rem 0; }
figure img { display: block; width: 100%; max-width: 34rem; }
figcaption { font-size: .82rem; color: #6a6155; margin-top: .35rem; }
table { border-collapse: collapse; width: 100%; margin: .6rem 0 1.2rem;
        font-size: .9rem; }
th, td { border: 1px solid #cfc8bd; padding: .4rem .55rem; text-align: left;
         vertical-align: top; }
th { background: #e7e3dc; font-weight: 600; }
.pagebreak { border: 0; border-top: 1px dashed #b8ab97; margin: 2.5rem 0 1.2rem;
             position: relative; }
.pagebreak::after { content: "page " attr(data-page); position: absolute;
                    top: -.62rem; right: 0; background: #f2f0ec; padding: 0 .5rem;
                    font: .7rem/1 ui-monospace, monospace; color: #a1907a;
                    letter-spacing: .08em; text-transform: uppercase; }
@media (prefers-color-scheme: dark) {
  body { background: #14120f; color: #ece7df; }
  h2 { border-bottom-color: #ece7df; }
  th { background: #241f19; } th, td { border-color: #3a332a; }
  figcaption { color: #9a9086; }
  .pagebreak { border-top-color: #4a4034; }
  .pagebreak::after { background: #14120f; color: #6f6355; }
}
"""


# ------------------------------------------------------------- online --


def _client():
    from manualbuilder.superdocs import SuperDocs, load_dotenv

    load_dotenv()
    return SuperDocs()


STATE = "published.json"
PROPOSAL = "proposal.json"


def _save(published, language: str) -> Path:
    """Remember what `publish` made, so nothing has to be pasted by hand.

    A published pair is two documents and the session each is edited in, and a
    demo that asks somebody to copy four ids between commands is a demo that
    goes wrong on camera.
    """
    OUT.mkdir(exist_ok=True)
    path = OUT / STATE
    path.write_text(
        json.dumps(
            {
                "manual_id": published.manual_id,
                "card_id": published.card_id,
                "sessions": published.sessions,
                "durable": published.durable,
                "language": language,
                "images": published.images,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _load(args):
    """The published pair: from the flags if given, from `out/` if not."""
    saved = {}
    path = OUT / STATE
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))

    published = session.Publication(
        manual_id=getattr(args, "manual", "") or saved.get("manual_id", ""),
        card_id=getattr(args, "card", "") or saved.get("card_id", ""),
        sessions=dict(saved.get("sessions", {})),
        durable=dict(saved.get("durable", {})),
        images=saved.get("images", {}),
    )
    # There is one session per document and no single id that means "the
    # session", so a --session on the command line applies to both documents
    # named alongside it.
    if getattr(args, "session", ""):
        for document_id in published.document_ids:
            published.sessions.setdefault(document_id, args.session)

    missing = [
        name
        for name, value in (
            ("--manual", published.manual_id),
            ("--card", published.card_id),
            ("--session", published.sessions.get(published.manual_id)),
        )
        if not value
    ]
    if missing:
        raise SpecError(
            f"no published pair to work on: {', '.join(missing)} not given and "
            f"{path} does not have it. Run `publish` first."
        )
    return published


def cmd_publish(args) -> int:
    """Upload one language's pair. One pair per run, deliberately.

    Publishing every locale at once would be one flag and several times the
    quota, and the pair is the unit that has to stay consistent -- a German
    manual and a German card live in one session and are edited together, the
    same way the English pair is. Cross-language consistency is not maintained by
    chat at all: it comes from the spec, and `check` is what proves it.
    """
    spec = _spec(args)
    if args.language:
        locales = _locales(spec)
        if args.language not in locales:
            print(
                f"no locales/{args.language}.yaml; have {', '.join(sorted(locales)) or 'none'}",
                file=sys.stderr,
            )
            return 2
        spec = locales[args.language]

    with _client() as client:
        published = session.publish(client, spec, language=args.language)
    path = _save(published, args.language)
    for document_id in published.document_ids:
        # Padded before it is coloured: an escape code has visible width to
        # `str.format`, which does not know it is not a printed character, so
        # colouring a value first and padding it second misaligns every
        # column after it in a real terminal.
        name = f"{published.name_for(document_id):<16}"
        print(f"{_bold(name)} {document_id}  in {published.sessions[document_id]}")
    print(f"images  {len(published.images)} uploaded")
    print(f"\nwritten to {path}")
    _next(
        'manualbuilder ask "…" to explore a document before changing it',
        'manualbuilder edit "…" to propose a wording change to both',
    )
    return 0


def cmd_edit(args) -> int:
    """One instruction, both documents, nothing applied without a look."""
    from manualbuilder.superdocs import SuperDocsError

    published = _load(args)
    with _client() as client:
        changes, _ = session.edit_both(client, published, args.instruction)

        if not changes:
            print("the turn proposed no changes.")
            _next(
                'manualbuilder ask "…" to see what the document currently says',
                "a more specific instruction, if the fact is there and was missed",
            )
            return 0

        grouped = session.changes_by_document(published, changes)
        for document_id, items in grouped.items():
            print(f"\n{_bold(f'{published.name_for(document_id)} — {len(items)} change(s)')}")
            for change in items:
                print(f"  [{change.operation}] {change.change_id}")
                print(f"    chunk {change.chunk_id}")
                print(f"    - {change.old_html[:100]}")
                print(f"    + {change.new_html[:100]}")
                if change.explanation:
                    print(f"    why: {change.explanation[:150]}")

        try:
            excused = session.assert_touched_both_or_absent(client, published, changes)
        except SuperDocsError as exc:
            print(f"\n{_red('REFUSED')}: {exc}")
            return 1
        for document_id in excused:
            print(
                "\n"
                + _dim(
                    f"{published.name_for(document_id)} was not required to change -- "
                    f"nothing in it currently resembles what changed elsewhere."
                )
            )

        path = _save_proposal(published, changes)
        if not args.yes:
            print(f"\nnothing approved. {path} holds the batch:")
            _next(
                "manualbuilder approve             to apply all of it",
                "manualbuilder approve --reject ID to apply the rest",
            )
            return 0

        results = session.approve_all(client, published, changes)
        print(f"\n{_green(f'approved {len(changes)} change(s) across {len(results)} turn(s)')}")
        _settle(client, published, changes)
        path.unlink(missing_ok=True)
        if not _realign(client, published, _spec_for(args), getattr(args, "no_repair", False)):
            return 1
        _next(
            "manualbuilder verify to confirm it landed the same way in both documents",
            "manualbuilder export --format html for the finished pair",
        )
    return 0


def cmd_ask(args) -> int:
    """Ask one document a question. Nothing is proposed, nothing applied.

    `edit` is the wrong shape for this: it always targets the pair, so a
    question about just the manual would needlessly cost a second turn
    against the card, and it only ever looks at proposed changes -- a plain
    answer is fetched off the API and thrown away there. This asks one
    document and prints what it said.
    """
    from manualbuilder.superdocs import SuperDocs

    published = _load(args)
    document_id = published.card_id if args.document == "card" else published.manual_id
    with _client() as client:
        reply = session.ask(client, published, document_id, args.question)

    print(reply.get("response") or "(the service returned no response text)")

    changes = SuperDocs.pending_changes(reply)
    if changes:
        print(
            "\n"
            + _dim(
                f"note: this also proposed {len(changes)} change(s). `ask` does not "
                f"apply them -- the synchronous endpoint's proposals can never be "
                f"approved. Run `edit` with the same wording if you meant to change "
                f"something."
            )
        )
    return 0


def _save_proposal(published, changes) -> Path:
    """Write the proposed batch down so a person can review it and come back.

    Change ids are minted per turn: re-running `edit` to reject one of them
    produces a different batch with different ids, so a review that spans two
    commands has to be reviewing a *recorded* batch rather than a remembered
    one. This is that record, and it is why `approve` is its own command.
    """
    OUT.mkdir(exist_ok=True)
    path = OUT / PROPOSAL
    path.write_text(
        json.dumps(
            {
                "sessions": published.sessions,
                "jobs": published.jobs,
                "changes": [
                    {
                        "change_id": c.change_id,
                        "operation": c.operation,
                        "chunk_id": c.chunk_id,
                        "document_id": c.document_id,
                        "old_html": c.old_html,
                        "new_html": c.new_html,
                        "explanation": c.explanation,
                    }
                    for c in changes
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def cmd_approve(args) -> int:
    """Apply a batch `edit` proposed, minus anything rejected by id.

    The gate, as its own step. Rejecting one change does not discard the rest:
    the two changes that were asked for go in and the one that was not stays
    out, in a single review.
    """
    from manualbuilder.superdocs import ProposedChange, SuperDocsError

    path = OUT / PROPOSAL
    published = _load(args)

    # `--discard` deliberately does not need a proposal file. The case it exists
    # for is a batch parked by a run that never wrote one -- a crash between
    # turns, a different machine, a session someone left open -- and that is
    # precisely when there is nothing on disk to read.
    if args.discard:
        with _client() as client:
            denied = session.discard_outstanding(client, published)
        path.unlink(missing_ok=True)
        print(
            _green(f"denied {denied} proposed change(s); the session is free for the next edit")
            if denied
            else _green("nothing was parked; the session is free")
        )
        return 0

    if not path.is_file():
        print(f"no proposal at {path}; run `edit` first", file=sys.stderr)
        return 2
    saved = json.loads(path.read_text(encoding="utf-8"))
    published.sessions.update(saved.get("sessions", {}))
    published.jobs = saved["jobs"]
    changes = [
        ProposedChange(
            change_id=c["change_id"],
            operation=c["operation"],
            chunk_id=c["chunk_id"],
            document_id=c["document_id"],
            old_html=c["old_html"],
            new_html=c["new_html"],
            explanation=c["explanation"],
        )
        for c in saved["changes"]
    ]

    reject = set(args.reject)
    with _client() as client:
        try:
            results = session.approve_all(client, published, changes, reject=reject)
        except SuperDocsError as exc:
            print(f"{_red('REFUSED')}: {exc}", file=sys.stderr)
            return 1

        for change in changes:
            rejected = change.change_id in reject
            verdict = _red("rejected") if rejected else _green("approved")
            print(
                f"  {verdict}  {change.change_id}  {published.name_for(change.document_id or '')}"
            )
        print(
            f"\n{len(changes) - len(reject)} approved, {len(reject)} rejected, "
            f"across {len(results)} turn(s)"
        )
        _settle(client, published, [c for c in changes if c.change_id not in reject])

        path.unlink()  # a batch is applied once; a stale one is a trap
        if not _realign(client, published, _spec_for(args), args.no_repair):
            return 1

    _next(
        "manualbuilder verify to confirm it landed the same way in both documents",
        "manualbuilder export --format html for the finished pair",
    )
    return 0


def _settle(client, published, changes) -> bool:
    """Wait for the read side to serve what was just approved, and report it.

    An approval returns before the documents come back with it in them. That is
    BUGS #10 on `export` and BUGS #22 on the read this build actually uses: a nine-change diagram swap was
    approved, `200`, every change accepted, and `verify` -- reading each
    document by its durable id, seconds later -- reported all nine figures still
    pointing at the previous drawings. A re-read minutes later, with nothing
    done in between, passed. The pair had been correct the whole time.

    So the wait happens here, once, where the write was, rather than being
    discovered by every command downstream of it. The reads are free, the loop
    leaves as soon as the documents agree, and the two cases worth a line get
    one: a wait that was needed, and a wait that ran out.
    """
    if not changes:
        return True
    report = session.settle(client, published, changes)
    if report.settled:
        # One read per document means it was already current; more than that
        # means this command absorbed a delay that would otherwise have been
        # reported as a wrong document.
        if report.reads > len({change.document_id for change in changes}):
            print(
                _dim(
                    f"the service served the pre-approval document for "
                    f"{report.waited:.1f}s after the approval returned; it is "
                    f"current now"
                )
            )
        return True

    stuck = sum(len(chunks) for chunks in report.outstanding.values())
    print(
        f"\n{_red('not yet visible')}: the approval was accepted, but after "
        f"{report.waited:.0f}s the service is still serving the previous content "
        f"for {stuck} chunk(s)."
    )
    print(
        "Nothing is wrong with the batch -- this is the read side lagging the "
        "write (BUGS #22).\n`verify` run now would report those as an older "
        "drawing or an unedited step; run it again in a minute."
    )
    return False


def _realign(client, published, spec, skip: bool = False) -> bool:
    """Read the pair back, and put right any passage that moved in only one.

    The gap this closes is one `assert_touched_both_or_absent` cannot see.
    Asked to raise a torque figure, the manual's turn found three passages --
    the rails step, the gantry step, and the troubleshooting table's own
    re-torque line -- and the card's turn found two of its three. Both
    documents proposed something, so the batch was applied, and the pair came
    apart on the one passage the card missed. `verify` reported it afterwards,
    correctly and far too late to be useful.

    So the pair is compared passage by passage the moment the batch lands, on
    the documents as the service is serving them, and the document that was
    left behind is asked -- once, with the exact wording the other one now has
    -- to say the same thing. That costs one operation, and only when the pair
    has actually come apart. `--no-repair` reports and stops instead.
    """
    from manualbuilder.superdocs import SuperDocsError

    drifts = session.drifted(session.read_pair(client, published), spec)
    if not drifts:
        return True

    print(f"\n{_bold('the pair came apart on ' + str(len(drifts)) + ' passage(s):')}")
    for drift in drifts:
        behind = drift.lagging or "one document"
        # The words that differ, not the two passages: they are near-identical
        # by construction, so printing both truncates to the same 120
        # characters and shows a reader nothing at all.
        print(
            f"  {drift.label:<22} {behind} still reads the way it did before "
            f"the edit ({vf.difference(drift.behind, drift.ahead)})"
        )
        print(_dim(f"    {drift.behind[:110]}…"))

    stuck = [drift for drift in drifts if not drift.repairable]
    if stuck or skip:
        print(
            "\n"
            + _red("the manual and the card disagree.")
            + (
                " Both documents have moved, and differently, so which wording\n"
                "was meant is a question for a person rather than for another turn."
                if stuck
                else " Not repaired: --no-repair."
            )
        )
        _next(
            'manualbuilder edit "…" to say it again for both documents',
            "manualbuilder verify to see the disagreement in full",
        )
        return False

    print(_dim("\nasking the document that lagged to say what the other one says (1 operation)"))
    try:
        changes = session.realign(client, published, drifts)
    except SuperDocsError as exc:
        print(f"\n{_red('REFUSED')}: {exc}")
        _next("manualbuilder approve --discard to free the session; nothing was applied")
        return False

    session.approve_all(client, published, changes)
    for change in changes:
        print(
            f"  {_green('approved')}  {change.change_id}  "
            f"{published.name_for(change.document_id or '')}"
        )
    _settle(client, published, changes)

    left = session.drifted(session.read_pair(client, published), spec)
    if left:
        print("\n" + _red("the pair still disagrees on: ") + ", ".join(d.label for d in left))
        _next('manualbuilder edit "…" to say it again for both documents')
        return False
    print(_green("the manual and the card agree again, word for word."))
    return True


def cmd_sync(args) -> int:
    """Re-draw every diagram from the spec and put the new ones in place.

    The path a spec change takes when the documents are already published. The
    drawing is regenerated, never patched -- and the swap that carries it into
    the document is checked to have been a swap and nothing else before anyone
    is asked to approve it.
    """
    from manualbuilder.superdocs import SuperDocsError

    spec = _spec(args)
    if args.language:
        locales = _locales(spec)
        if args.language not in locales:
            print(f"no locales/{args.language}.yaml", file=sys.stderr)
            return 2
        spec = locales[args.language]

    published = _load(args)
    with _client() as client:
        changes, expected, asked = session.swap_diagrams(client, published, spec)
        # `swap_diagrams` moves each document into a fresh session, so the
        # record on disk has to follow or the next command talks to the old one.
        _save(published, args.language)
        print(f"{len(pj.image_ids(spec))} diagram(s) re-rendered and uploaded")

        try:
            # Two checks, and neither one implies the other: the first says
            # nothing but diagram URLs moved, the second says every diagram URL
            # that should have moved did. A turn that changed nothing passes the
            # first on its own.
            session.assert_only_the_image_changed(changes, expected)
            session.assert_every_figure_swapped(changes, asked)
        except SuperDocsError as exc:
            print(f"\n{_red('REFUSED')}: {exc}")
            _next("manualbuilder approve --discard to free the session; nothing was applied")
            return 1

        for change in changes:
            print(
                f"  [{change.operation}] chunk {change.chunk_id} in "
                f"{published.name_for(change.document_id or '')}"
            )
        print(f"\n{len(changes)} change(s), each one an image URL and nothing else")

        path = _save_proposal(published, changes)
        if not args.yes:
            print(f"nothing approved. {path} holds the batch.")
            _next("manualbuilder approve to apply it")
            return 0

        results = session.approve_all(client, published, changes)
        print(_green(f"approved {len(changes)} swap(s) across {len(results)} turn(s)"))
        _settle(client, published, changes)
        _next("manualbuilder verify to confirm the pair still agrees, pointing at the new diagrams")
    path.unlink(missing_ok=True)
    return 0


def cmd_export(args) -> int:
    """Pull both finished documents back down. The fourth call of the spine.

    Export is how a claim about a document becomes checkable: the manual on
    disk after an approved edit is the manual the service holds, not the one
    this program believes it uploaded. Exports cost no quota, which is why the
    verification path leans on them.
    """
    OUT.mkdir(exist_ok=True)
    published = _load(args)
    with _client() as client:
        # Export is keyed by session, and a session renders its focused
        # document -- so each document is focused in turn rather than assuming
        # one call brings back both.
        # Into out/export/, never out/ itself: `build` writes `manual.html`
        # there, and an export landing on top of it would replace the local
        # render with the service's copy under the same name. Comparing the two
        # is most of what export is for here.
        target = OUT / "export"
        target.mkdir(parents=True, exist_ok=True)
        _rebind(client, published, args)
        for document_id in published.document_ids:
            name = published.name_for(document_id).replace(" ", "-")
            # One document per session, so its own session exports it: no
            # focus juggling, and no way to export the wrong one.
            data = client.export_bytes(published.session_for(document_id), args.format)
            path = target / f"{name}.{args.format}"
            path.write_bytes(data)
            print(f"{path}  {len(data):,} bytes")
    return 0


def cmd_status(args) -> int:
    """What is published, and whether anything is in the way of an edit.

    Free, and the first thing to run when a command has just refused. The state
    that stops work here is a batch parked at `awaiting_approval`: it holds its
    session, the next turn in that session comes back 409 `session_busy`, and
    nothing about the error names the batch. This does.
    """
    published = _load(args)
    print(_bold(f"{'document':<16} {'id':<16} session"))
    for document_id in published.document_ids:
        print(
            f"{published.name_for(document_id):<16} {document_id:<16} "
            f"{published.sessions.get(document_id, '—')}"
        )
    print(f"\nimages   {len(published.images)} diagram URL(s) recorded")

    proposal = OUT / PROPOSAL
    if proposal.is_file():
        saved = json.loads(proposal.read_text(encoding="utf-8"))
        print(
            f"proposal {len(saved.get('changes', []))} change(s) written to "
            f"{proposal}, not yet decided"
        )

    blocked = 0
    with _client() as client:
        for document_id in published.document_ids:
            for job in client.active_jobs(published.session_for(document_id)):
                status = job.get("status")
                blocked += status == "awaiting_approval"
                print(
                    f"\n{published.name_for(document_id)}: job "
                    f"{job.get('job_id') or job.get('id')} is {status}"
                )
    if blocked:
        print(
            "\n"
            + _red(
                f"{blocked} batch(es) parked. A parked batch holds its session, so "
                f"`approve`\nor `approve --discard` has to happen before any other "
                f"edit in it."
            )
        )
    else:
        print("\n" + _green("nothing parked; both sessions are free for the next edit."))
    return 0


def _rebind(client, published, args) -> None:
    """Check each session still holds its document, and re-open it if not.

    Reading is keyed by session and a session is not a stable handle: it serves
    whatever it is focused on. Anything that changes focus -- a person opening
    the pair in the web interface and clicking the other tab -- silently points
    a read at the wrong document. Cheap to check, and the alternative is a
    verification step that confidently reports on a document nobody asked about.
    """
    moved = published.ensure_sessions(client)
    if not moved:
        return
    for document_id in moved:
        print(
            f"note: {published.name_for(document_id)}'s session no longer held "
            f"it; re-opened as {published.sessions[document_id]}"
        )
    _save(published, getattr(args, "language", ""))


def cmd_verify(args) -> int:
    """Read both documents back off the service and check what they say.

    The claim every other command makes is about what it sent. This is the one
    that asks what is actually there -- so it reads each document back by its
    **durable id** and checks the answer against `out/published.json` and
    against the spec. Nothing here is billed.

    Reading by id rather than exporting is the whole difference between this
    command being trustworthy and not. Export is keyed by session, and a session
    serves whatever it is focused on: open the pair in the web interface, click
    the other tab, and the session recorded for the card starts serving the
    manual -- same call, same session id, a different document, no error. That
    happened, and this command reported the card as having eight figures and
    disagreeing with the manual, which was true of the document it was handed
    and nothing to do with the card.

    `GET /v1/documents/{id}?include_html=true` names the document, so there is
    no focus to drift and no session to re-bind first. It is also the read the
    service's own agent guide points at: *"Verify for free -- never export just
    to check."* Export is still what `export` does, because a rendered PDF is a
    deliverable and this is not.
    """
    spec = _spec(args)
    if args.language:
        locales = _locales(spec)
        if args.language not in locales:
            print(f"no locales/{args.language}.yaml", file=sys.stderr)
            return 2
        spec = locales[args.language]

    published = _load(args)
    target = OUT / "served"
    target.mkdir(parents=True, exist_ok=True)

    def read_pair(client) -> dict[str, str]:
        served = session.read_pair(client, published)
        for name, html in served.items():
            (target / f"{name.replace(' ', '-')}.html").write_text(html, encoding="utf-8")
        return served

    stale = False
    with _client() as client:
        served = read_pair(client)
        print(f"read both documents by id into {target}/ (no quota spent)\n")
        findings = vf.verify(served, published.images, spec)

        # A read taken shortly after an approval can still be the pre-approval
        # document -- the whole reason `approve` now waits for the read side
        # before it returns. This command is also run on its own, hours or
        # machines away from whatever approved last, so it does not get to
        # assume that wait happened: one failing read buys one re-read, which
        # is free, before anybody is told the pair is wrong.
        if vf.failed(findings):
            print(
                _dim(
                    f"{len(vf.failed(findings))} check(s) failed on this read. A read "
                    f"taken just after an approval can still be the pre-approval "
                    f"document, so this is read once more before it is reported."
                )
            )
            time.sleep(session.SETTLE_POLL)
            served = read_pair(client)
            findings = vf.verify(served, published.images, spec)
            stale = not vf.failed(findings)
            print(
                _dim(
                    "the first read was stale; what follows is the re-read.\n"
                    if stale
                    else "the re-read says the same thing.\n"
                )
            )

    for finding in findings:
        # Padded before it is coloured, same reason as `publish`'s document
        # column: an escape code has visible width to `str.format`.
        colored = {vf.FAIL: _red, vf.OK: _green}.get(finding.status, _dim)
        status = colored(f"{finding.status:<4}")
        print(f"  {status} {finding.check:<34} {finding.detail}")

    bad = vf.failed(findings)
    moot = [f for f in findings if f.status == vf.MOOT]
    summary = f"{len(findings) - len(bad) - len(moot)} passed, {len(bad)} failed" + (
        f", {len(moot)} no longer checkable" if moot else ""
    )
    print(f"\n{summary}" if bad else f"\n{_green(summary)}")
    if bad:
        print(
            "\n"
            + _red("the documents on the service are not what this program recorded publishing.")
        )
        _next("manualbuilder status to see what, if anything, is parked and blocking a fix")
        return 1
    print(
        "every figure points at the drawing uploaded for it, and every "
        "instruction\nthe card shares with the manual is word for word the same "
        "in both."
    )
    _next("manualbuilder export --format html for the finished pair")
    return 0


def _published_args(parser) -> None:
    """The three ids that identify a published pair.

    All optional: `publish` writes them to out/published.json and these are the
    override for working on a pair this machine did not publish.
    """
    parser.add_argument("--session", default="", help="chat session id")
    parser.add_argument("--manual", default="", help="manual document id")
    parser.add_argument("--card", default="", help="quick-start document id")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manualbuilder", description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate the spec and every locale (offline)")
    sub.add_parser("build", help="render documents and diagrams to out/ (offline)")
    publish = sub.add_parser("publish", help="upload both documents and their diagrams")
    publish.add_argument(
        "--language",
        default="",
        help="a locale from locales/ (default: the spec's own)",
    )

    edit = sub.add_parser("edit", help="one instruction, both documents")
    edit.add_argument("instruction")
    _published_args(edit)
    edit.add_argument(
        "--yes",
        action="store_true",
        help="approve the proposed changes; without it, nothing is applied",
    )
    ask = sub.add_parser("ask", help="ask one document a question; nothing is proposed or applied")
    ask.add_argument("question")
    _published_args(ask)
    ask.add_argument(
        "--document",
        choices=("manual", "card"),
        default="manual",
        help="which document to ask (default: manual)",
    )

    approve = sub.add_parser(
        "approve", help="apply the batch `edit` proposed, minus what you reject"
    )
    approve.add_argument(
        "--reject",
        action="append",
        default=[],
        metavar="CHANGE_ID",
        help="reject one change by id; the rest still applies. Repeatable.",
    )
    approve.add_argument(
        "--discard",
        action="store_true",
        help="throw the whole batch away and unblock the session",
    )
    approve.add_argument(
        "--no-repair",
        action="store_true",
        help=(
            "report a passage that moved in only one of the two documents "
            "instead of asking the other one to catch up (which costs an "
            "operation)"
        ),
    )
    _published_args(approve)

    sync = sub.add_parser("sync", help="re-render the diagrams and swap them in")
    _published_args(sync)
    sync.add_argument("--language", default="", help="a locale from locales/")
    sync.add_argument(
        "--yes",
        action="store_true",
        help="approve the swaps; without it, nothing is applied",
    )

    export = sub.add_parser("export", help="download both finished documents")
    _published_args(export)
    export.add_argument("--format", default="pdf", help="pdf (default) or docx")

    status = sub.add_parser("status", help="what is published, and what is blocking an edit (free)")
    _published_args(status)

    check_live = sub.add_parser("verify", help="read both documents back and check them (free)")
    _published_args(check_live)
    check_live.add_argument("--language", default="", help="a locale from locales/")

    args = parser.parse_args(argv)
    handler = {
        "check": cmd_check,
        "build": cmd_build,
        "publish": cmd_publish,
        "edit": cmd_edit,
        "ask": cmd_ask,
        "approve": cmd_approve,
        "sync": cmd_sync,
        "export": cmd_export,
        "status": cmd_status,
        "verify": cmd_verify,
    }[args.command]
    try:
        return handler(args)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
