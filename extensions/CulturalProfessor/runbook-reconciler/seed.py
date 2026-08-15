#!/usr/bin/env python3
"""Put the sample runbook into a real Confluence space, and take it out again.

The end-to-end demo needs a live page with real runbook prose in it. Page 98311
in the test site is an empty template — no thresholds, no commands, no
escalation targets — so a sweep against it correctly finds nothing, which
demonstrates nothing.

    .venv/bin/python seed.py create   # create (or update) the page, then label it
    .venv/bin/python seed.py show     # what a sweep would find on it
    .venv/bin/python seed.py delete   # remove it again

It needs the virtualenv (httpx), unlike `preflight.py` which is deliberately
stdlib-only so it can diagnose a broken install.

The page content is `fixtures/live/payments-api-runbook.storage.xhtml`, and the drift in
it is planted against the bundled corpus estate — so `INFRA_REPO_PATHS` must
still point at `fixtures/infra` (the default) for the findings to be the ones
listed in the README. Pointing this at a real estate and a real runbook is the
same command with different inputs; the point of the fixture is that the
expected output is known in advance.

**This writes to a real wiki.** It creates one page, in the space named by
`CONFLUENCE_SPACE_KEY`, titled below. It never touches any other page.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reconciler.config import Config
from reconciler.confluence.client import ConfluenceError, ConfluenceSource

TITLE = "Runbook — payments-api latency and error budget"
BODY = Path(__file__).resolve().parent / "fixtures" / "live" / "payments-api-runbook.storage.xhtml"


def find_page(client: ConfluenceSource, title: str) -> dict | None:
    """The page by title, if it is already there.

    By listing rather than by CQL search, because CQL is unreachable with a
    scoped token — see BUGS.md item 2. On a personal space the page list is
    short enough that this is not worth optimising.
    """
    cursor = None
    while True:
        body = client._get(
            "/wiki/api/v2/pages",
            limit=250,
            cursor=cursor,
            **({"space-id": client.space_id()} if client.space_id() else {}),
        )
        for entry in body.get("results", []):
            if entry.get("title") == title:
                return entry
        cursor = None
        links = body.get("_links") or {}
        if "next" in links:
            cursor = links["next"].split("cursor=")[-1].split("&")[0]
        if not cursor:
            return None


def seeded_content() -> str:
    """The bytes we send, which are also the bytes Confluence stores.

    `.rstrip("\n")` matters: the fixture file ends with a newline the way every
    text file should, and Confluence drops it. Without this the page and its own
    source differ by one byte the moment it is created, and `diff` opens the
    demo by reporting a changed range nobody made.
    """
    return BODY.read_text(encoding="utf-8").rstrip("\n")


def create(client: ConfluenceSource) -> str:
    content = seeded_content()
    existing = find_page(client, TITLE)

    if existing:
        page_id = str(existing["id"])
        version = int((existing.get("version") or {}).get("number", 1))
        client.write(page_id, content, version, TITLE)
        print(f"updated existing page {page_id}")
    else:
        space = client.space_id()
        if not space:
            raise SystemExit("CONFLUENCE_SPACE_KEY is not set or did not resolve")
        created = client._client.post(
            "/wiki/api/v2/pages",
            json={
                "spaceId": space,
                "status": "current",
                "title": TITLE,
                "body": {"representation": "storage", "value": content},
            },
        )
        if created.status_code >= 400:
            raise SystemExit(f"create failed: {created.status_code} {created.text[:300]}")
        page_id = str(created.json()["id"])
        print(f"created page {page_id}")

    label(client, page_id)
    print(f"  page id: {page_id}")
    print("  next: ./rr check   (RR_SOURCE stays 'auto', so it reads Confluence)")
    return page_id


def label(client: ConfluenceSource, page_id: str) -> None:
    """Add the crawl label, or say plainly that it has to be done by hand.

    `rr` finds runbooks by label, so an unlabelled page is invisible to it. The
    v1 label endpoint is the only one that adds a label and it is unreachable
    with a scoped token (BUGS.md item 2), so this is genuinely likely to fail —
    and a seeding script that fails silently here leaves somebody debugging an
    empty sweep.
    """
    wanted = client.label or "runbook"
    if wanted in client.labels(page_id):
        print(f"  label {wanted!r}: already present")
        return
    try:
        response = client._client.post(
            f"/wiki/rest/api/content/{page_id}/label", json=[{"prefix": "global", "name": wanted}]
        )
        if response.status_code < 400:
            print(f"  label {wanted!r}: added")
            return
        detail = f"{response.status_code} {response.text[:120]}"
    except ConfluenceError as exc:
        detail = str(exc)[:120]

    print(f"  label {wanted!r}: COULD NOT BE ADDED ({detail})")
    print(
        "  ^ add it by hand: open the page, '...' menu, Labels, type "
        f"{wanted!r}. `rr` finds runbooks by label and will not see this page without it."
    )


def show(client: ConfluenceSource, page_id: str | None = None) -> None:
    from reconciler.check.vertical import check_page
    from reconciler.estate import Estate
    from reconciler.extract.patterns import extract_claims

    page = find_page(client, TITLE)
    if not page:
        raise SystemExit("the page is not there; run `create` first")
    document = client.read(str(page["id"]))
    claims = extract_claims(document)
    findings = check_page(str(page["id"]), claims, Estate.load(Config.load()))
    counts = {
        v: sum(1 for f in findings if f.verdict == v)
        for v in ("contradicts", "agrees", "unverifiable")
    }
    print(
        f"page {page['id']} · {len(claims)} claims · "
        + " · ".join(f"{n} {v}" for v, n in counts.items())
    )
    for finding in sorted(findings, key=lambda f: f.subject):
        if finding.verdict != "contradicts":
            continue
        claim = next((c for c in claims if c.claim_id == finding.claim_id), None)
        print(f"  {finding.subject}")
        print(f"     page says {claim.asserted!r} · estate says {str(finding.observed)[:60]!r}")


def diff(client: ConfluenceSource) -> None:
    """The live page against the bytes that were seeded into it.

    This is the demo beat that a block-level diff in the Confluence UI cannot
    give you: not "here is what changed" at paragraph resolution, but every
    changed range in the whole body, at character resolution. If this tool ever
    altered a byte it was not approved to alter, it shows up here — which is why
    the comparison is against the seeded file rather than against the page's own
    previous version.
    """
    import difflib

    page = find_page(client, TITLE)
    if not page:
        raise SystemExit("the page is not there; run `create` first")
    seeded = seeded_content()
    live = client.read(str(page["id"])).body

    ranges = [
        (tag, seeded[i1:i2], live[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, seeded, live, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]
    if not ranges:
        print(f"page {page['id']} is byte-identical to the seeded content")
        return
    print(f"page {page['id']} · {len(ranges)} changed range(s) out of {len(seeded)} bytes:")
    for tag, was, now in ranges:
        print(f"  {tag}: {was!r} -> {now!r}")
    unchanged = len(seeded) - sum(len(w) for _, w, _ in ranges)
    print(f"\n{unchanged} of {len(seeded)} bytes untouched.")


def delete(client: ConfluenceSource) -> None:
    """Remove the demo page, or fail loudly enough that nobody thinks it went.

    `DELETE /wiki/api/v2/pages/{id}` answers `401 Unauthorized; scope does not
    match` for a scoped API token — `delete:page:confluence` is not among the
    scopes one can be granted. So this genuinely cannot clean up, and the only
    honest thing it can do is say so and exit non-zero.

    The first version printed `delete 557058 -> 401` and returned normally, so
    `./demo` announced "every stage passed" with the page still sitting in the
    space. Reporting success for something that did not happen is the exact
    failure this whole project exists to catch, and it was in the cleanup path
    of its own demo.
    """
    page = find_page(client, TITLE)
    if not page:
        print("nothing to delete")
        return
    page_id = str(page["id"])
    response = client._client.delete(f"/wiki/api/v2/pages/{page_id}")
    if response.status_code < 400:
        print(f"deleted page {page_id}")
        return

    raise SystemExit(
        f"could not delete page {page_id}: {response.status_code} "
        f"{response.text[:120]}\n"
        f"  a scoped API token cannot delete pages (delete:page:confluence is not\n"
        f"  grantable), so this one has to go by hand: open the page, '...' menu,\n"
        f"  Delete. It is titled {TITLE!r}."
    )


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    config = Config.load()
    if not config.has_confluence:
        raise SystemExit("Confluence is not configured; see .env.example")
    with ConfluenceSource.from_config(config) as client:
        if action == "create":
            create(client)
        elif action == "show":
            show(client)
        elif action == "diff":
            diff(client)
        elif action == "delete":
            delete(client)
        else:
            raise SystemExit(f"unknown action {action!r}; use create, show, diff or delete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
