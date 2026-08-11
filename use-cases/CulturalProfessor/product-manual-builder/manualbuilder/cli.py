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
from pathlib import Path

from manualbuilder import (localize as lz, paginate as pg, projections as pj,
                           session, verify as vf)
from manualbuilder.spec import SpecError, load_spec

DEFAULT_SPEC = Path("spec/halyard_m1.yaml")
LOCALES = Path("locales")
OUT = Path("out")


def _spec(args):
    return load_spec(args.spec)


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
    print(f"spec        {spec.name} rev {spec.revision} — "
          f"{len(spec.parts)} parts, {len(spec.steps)} steps, "
          f"{len(spec.warnings)} warnings, {len(spec.faults)} faults")

    manual = pj.manual_html(spec)
    card = pj.quick_start_html(spec)

    # The consistency claim, checked rather than trusted.
    for step in spec.quick_start():
        if step.body not in manual or step.body not in card:
            print(f"  FAIL  step {step.id!r} differs between the two documents")
            return 1
    for fault in spec.quick_start_troubleshooting():
        if fault.fix not in manual or fault.fix not in card:
            print(f"  FAIL  fix {fault.id!r} differs between the two documents")
            return 1
    print(f"card        {len(spec.quick_start_steps)} of {len(spec.steps)} steps and "
          f"{len(spec.quick_start_faults)} of {len(spec.faults)} fixes, "
          f"every word identical to the manual")

    layouts = {
        "manual": pg.paginate(pj.manual_blocks(spec), pg.PAGE),
        "card": pg.paginate(pj.quick_start_blocks(spec), pg.PANEL),
    }
    print(f"{'layout':<11} manual {layouts['manual'].pages} pages, fullest "
          f"{layouts['manual'].tightest()[1]:.0%}; card "
          f"{layouts['card'].pages} panels, fullest "
          f"{layouts['card'].tightest()[1]:.0%}")
    for name, layout in layouts.items():
        unit = "page" if name == "manual" else "panel"
        for block_id, excess in layout.overflows():
            print(f"  FAIL  {block_id} overruns its {unit} by {excess} lines")
            return 1

    failures = 0
    for language, localised in sorted(_locales(spec).items()):
        problem = _check_locale(spec, localised, language, layouts)
        if problem:
            print(f"  FAIL  {problem}")
            failures += 1
            continue
        ratio = len(pj.manual_html(localised)) / len(manual)
        tightest = max(
            pg.paginate(pj.manual_blocks(localised), pg.PAGE).tightest()[1],
            pg.paginate(pj.quick_start_blocks(localised), pg.PANEL).tightest()[1],
        )
        print(f"{'locale ' + language:<11} same page for every block, text "
              f"{ratio:.0%} of source, {1 - tightest:.0%} headroom")

    print("ok" if not failures else f"{failures} locale(s) would repaginate")
    return 1 if failures else 0


def _check_locale(spec, localised, language: str, layouts) -> str | None:
    """Structure first, then pagination. Returns the problem, or None.

    The order is deliberate: a missing heading and a page that moved have the
    same symptom in print, and reporting the heading is what tells somebody
    which one it is.
    """
    try:
        lz.assert_same_structure(pj.manual_html(spec),
                                 pj.manual_html(localised), language)
        lz.assert_same_structure(pj.quick_start_html(spec),
                                 pj.quick_start_html(localised), language)
        pg.assert_same_pagination(
            layouts["manual"], pg.paginate(pj.manual_blocks(localised), pg.PAGE),
            language, "manual")
        pg.assert_same_pagination(
            layouts["card"], pg.paginate(pj.quick_start_blocks(localised), pg.PANEL),
            language, "card")
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
            images[language][image_id] = name    # a local path, so out/ opens
            written += 1

    documents = [("manual", spec, pj.manual_blocks, pg.PAGE, "")]
    documents.append(("quickstart", spec, pj.quick_start_blocks, pg.PANEL, ""))
    for language, localised in sorted(_locales(spec).items()):
        documents.append((f"manual.{language}", localised, pj.manual_blocks,
                          pg.PAGE, language))
        documents.append((f"quickstart.{language}", localised,
                          pj.quick_start_blocks, pg.PANEL, language))

    for name, source, builder, box, language in documents:
        blocks = builder(source, images[language])
        (OUT / f"{name}.html").write_text(pj.render(blocks), encoding="utf-8")
        (OUT / f"{name}.preview.html").write_text(
            _preview(name, blocks, pg.paginate(blocks, box), language),
            encoding="utf-8")

    print(f"{written} diagrams and {len(documents)} documents in {OUT}/")
    print(f"open {OUT}/manual.preview.html to see where the pages break")
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
            continue                       # a table continuing overleaf
        parts.append(by_id[placement.block_id].html)

    lang = f' lang="{language}"' if language else ""
    return (f'<!doctype html><meta charset="utf-8"><title>{title}</title>'
            f"<style>{_PREVIEW_CSS}</style>"
            f'<body{lang}><main>' + "\n".join(parts) + "</main></body>")


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
    path.write_text(json.dumps({
        "manual_id": published.manual_id,
        "card_id": published.card_id,
        "sessions": published.sessions,
        "durable": published.durable,
        "language": language,
        "images": published.images,
    }, indent=2), encoding="utf-8")
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

    missing = [name for name, value in (
        ("--manual", published.manual_id),
        ("--card", published.card_id),
        ("--session", published.sessions.get(published.manual_id)),
    ) if not value]
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
            print(f"no locales/{args.language}.yaml; have "
                  f"{', '.join(sorted(locales)) or 'none'}", file=sys.stderr)
            return 2
        spec = locales[args.language]

    with _client() as client:
        published = session.publish(client, spec, language=args.language)
    path = _save(published, args.language)
    for document_id in published.document_ids:
        print(f"{published.name_for(document_id):<16} {document_id}  "
              f"in {published.sessions[document_id]}")
    print(f"images  {len(published.images)} uploaded")
    print(f"\nwritten to {path}; `edit`, `sync` and `export` read it from there.")
    return 0


def cmd_edit(args) -> int:
    """One instruction, both documents, nothing applied without a look."""
    from manualbuilder.superdocs import SuperDocsError

    published = _load(args)
    with _client() as client:
        changes, _ = session.edit_both(client, published, args.instruction)

        if not changes:
            print("the turn proposed no changes.")
            return 0

        grouped = session.changes_by_document(published, changes)
        for document_id, items in grouped.items():
            print(f"\n{published.name_for(document_id)} — {len(items)} change(s)")
            for change in items:
                print(f"  [{change.operation}] {change.change_id}")
                print(f"    chunk {change.chunk_id}")
                print(f"    - {change.old_html[:100]}")
                print(f"    + {change.new_html[:100]}")
                if change.explanation:
                    print(f"    why: {change.explanation[:150]}")

        try:
            session.assert_touched_both(published, changes)
        except SuperDocsError as exc:
            print(f"\nREFUSED: {exc}")
            return 1

        path = _save_proposal(published, changes)
        if not args.yes:
            print(f"\nnothing approved. {path} holds the batch:")
            print("  manualbuilder approve            — apply all of it")
            print("  manualbuilder approve --reject ID — apply the rest")
            return 0

        results = session.approve_all(client, published, changes)
        print(f"\napproved {len(changes)} change(s) across {len(results)} turn(s)")
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
    path.write_text(json.dumps({
        "sessions": published.sessions,
        "jobs": published.jobs,
        "changes": [{"change_id": c.change_id, "operation": c.operation,
                     "chunk_id": c.chunk_id, "document_id": c.document_id,
                     "old_html": c.old_html, "new_html": c.new_html,
                     "explanation": c.explanation} for c in changes],
    }, indent=2), encoding="utf-8")
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
        print(f"denied {denied} proposed change(s); the session is free for the "
              f"next edit" if denied else "nothing was parked; the session is free")
        return 0

    if not path.is_file():
        print(f"no proposal at {path}; run `edit` first", file=sys.stderr)
        return 2
    saved = json.loads(path.read_text(encoding="utf-8"))
    published.sessions.update(saved.get("sessions", {}))
    published.jobs = saved["jobs"]
    changes = [ProposedChange(
        change_id=c["change_id"], operation=c["operation"], chunk_id=c["chunk_id"],
        document_id=c["document_id"], old_html=c["old_html"],
        new_html=c["new_html"], explanation=c["explanation"])
        for c in saved["changes"]]

    reject = set(args.reject)
    with _client() as client:

        try:
            results = session.approve_all(client, published, changes, reject=reject)
        except SuperDocsError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1

    for change in changes:
        verdict = "rejected" if change.change_id in reject else "approved"
        print(f"  {verdict}  {change.change_id}  "
              f"{published.name_for(change.document_id or '')}")
    print(f"\n{len(changes) - len(reject)} approved, {len(reject)} rejected, "
          f"across {len(results)} turn(s)")
    path.unlink()          # a batch is applied once; a stale one is a trap
    return 0


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
            print(f"\nREFUSED: {exc}")
            print("nothing was approved, and the batch is still parked. "
                  "`approve --discard` frees the session.")
            return 1

        for change in changes:
            print(f"  [{change.operation}] chunk {change.chunk_id} in "
                  f"{published.name_for(change.document_id or '')}")
        print(f"\n{len(changes)} change(s), each one an image URL and nothing else")

        path = _save_proposal(published, changes)
        if not args.yes:
            print(f"nothing approved. {path} holds the batch; `approve` applies it.")
            return 0

        results = session.approve_all(client, published, changes)
        print(f"approved {len(changes)} swap(s) across {len(results)} turn(s)")
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
            data = client.export_bytes(published.session_for(document_id),
                                       args.format)
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
    print(f"{'document':<16} {'id':<16} session")
    for document_id in published.document_ids:
        print(f"{published.name_for(document_id):<16} {document_id:<16} "
              f"{published.sessions.get(document_id, '—')}")
    print(f"\nimages   {len(published.images)} diagram URL(s) recorded")

    proposal = OUT / PROPOSAL
    if proposal.is_file():
        saved = json.loads(proposal.read_text(encoding="utf-8"))
        print(f"proposal {len(saved.get('changes', []))} change(s) written to "
              f"{proposal}, not yet decided")

    blocked = 0
    with _client() as client:
        for document_id in published.document_ids:
            for job in client.active_jobs(published.session_for(document_id)):
                status = job.get("status")
                blocked += status == "awaiting_approval"
                print(f"\n{published.name_for(document_id)}: job "
                      f"{job.get('job_id') or job.get('id')} is {status}")
    if blocked:
        print(f"\n{blocked} batch(es) parked. A parked batch holds its session, so "
              f"`approve`\nor `approve --discard` has to happen before any other "
              f"edit in it.")
    else:
        print("\nnothing parked; both sessions are free for the next edit.")
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
        print(f"note: {published.name_for(document_id)}'s session no longer held "
              f"it; re-opened as {published.sessions[document_id]}")
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

    served: dict[str, str] = {}
    with _client() as client:
        for document_id in published.document_ids:
            name = published.name_for(document_id)
            html = client.document_html(published.durable_for(document_id))
            (target / f"{name.replace(' ', '-')}.html").write_text(
                html, encoding="utf-8")
            served[name] = html
    print(f"read both documents by id into {target}/ (no quota spent)\n")

    findings = vf.verify(served, published.images, spec)
    for finding in findings:
        print(f"  {finding.status:<4} {finding.check:<34} {finding.detail}")

    bad = vf.failed(findings)
    moot = [f for f in findings if f.status == vf.MOOT]
    print(f"\n{len(findings) - len(bad) - len(moot)} passed, {len(bad)} failed"
          + (f", {len(moot)} no longer checkable" if moot else ""))
    if bad:
        print("\nthe documents on the service are not what this program "
              "recorded publishing.")
        return 1
    print("every figure points at the drawing uploaded for it, and every "
          "instruction\nthe card shares with the manual is word for word the same "
          "in both.")
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
    publish = sub.add_parser("publish",
                             help="upload both documents and their diagrams")
    publish.add_argument("--language", default="",
                         help="a locale from locales/ (default: the spec's own)")

    edit = sub.add_parser("edit", help="one instruction, both documents")
    edit.add_argument("instruction")
    _published_args(edit)
    edit.add_argument("--yes", action="store_true",
                      help="approve the proposed changes; without it, nothing is applied")
    approve = sub.add_parser(
        "approve", help="apply the batch `edit` proposed, minus what you reject")
    approve.add_argument("--reject", action="append", default=[],
                         metavar="CHANGE_ID",
                         help="reject one change by id; the rest still applies. "
                              "Repeatable.")
    approve.add_argument("--discard", action="store_true",
                         help="throw the whole batch away and unblock the session")
    _published_args(approve)

    sync = sub.add_parser("sync", help="re-render the diagrams and swap them in")
    _published_args(sync)
    sync.add_argument("--language", default="", help="a locale from locales/")
    sync.add_argument("--yes", action="store_true",
                      help="approve the swaps; without it, nothing is applied")

    export = sub.add_parser("export", help="download both finished documents")
    _published_args(export)
    export.add_argument("--format", default="pdf", help="pdf (default) or docx")

    status = sub.add_parser(
        "status", help="what is published, and what is blocking an edit (free)")
    _published_args(status)

    check_live = sub.add_parser(
        "verify", help="read both documents back and check them (free)")
    _published_args(check_live)
    check_live.add_argument("--language", default="",
                            help="a locale from locales/")

    args = parser.parse_args(argv)
    handler = {"check": cmd_check, "build": cmd_build, "publish": cmd_publish,
               "edit": cmd_edit, "approve": cmd_approve, "sync": cmd_sync,
               "export": cmd_export, "status": cmd_status,
               "verify": cmd_verify}[args.command]
    try:
        return handler(args)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
