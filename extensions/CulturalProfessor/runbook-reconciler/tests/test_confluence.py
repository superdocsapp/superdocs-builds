"""The Confluence adapter, against recorded shapes and — opt-in — a real site.

Almost everything here runs with no site, no token and no network, against
reply shapes recorded from a real Cloud instance on 2026-08-15. That is a
deliberate limit and worth naming: these tests prove this code reads those
shapes correctly, not that Confluence still sends them. The live stage in
`selftest` is what proves the second thing, and it is opt-in because it writes
to somebody's wiki.

The auth discovery tests are the valuable ones. The 401-from-the-site-host
behaviour is exactly the kind of thing that gets "fixed" by someone hardcoding
the gateway, and then breaks the day a classic token turns up.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from reconciler.confluence.client import ConfluenceError, ConfluenceSource, Credentials, discover
from reconciler.confluence.local import VersionConflict

CLOUD_ID = "11111111-2222-3333-4444-555555555555"
SITE = "https://meridian.atlassian.net"
GATEWAY = f"https://api.atlassian.com/ex/confluence/{CLOUD_ID}"

#: A page reply in the shape v2 really returns, trimmed to what is read.
PAGE_BODY = {
    "id": "98311",
    "title": "Runbook: payments-api high latency",
    "status": "current",
    "version": {"number": 7},
    "body": {
        "storage": {"value": "<p>above <strong>800ms</strong></p>", "representation": "storage"}
    },
}


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def source_with(handler) -> ConfluenceSource:
    client = ConfluenceSource(Credentials(GATEWAY, "Basic abc", "test", CLOUD_ID))
    client._client = httpx.Client(base_url=GATEWAY, transport=transport(handler))
    return client


# ------------------------------------------------------------------- auth ---


def test_a_scoped_token_is_rejected_by_the_site_and_accepted_by_the_gateway() -> None:
    """The behaviour that costs people an afternoon, pinned as a test.

    The site host answers 401 to a credential that is perfectly valid. Anyone
    who trusts that goes to the token page instead of to the other host.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url.endswith("/_edge/tenant_info"):
            return httpx.Response(200, json={"cloudId": CLOUD_ID})
        if url.startswith(SITE):
            return httpx.Response(401, text="Unauthorized")
        return httpx.Response(200, json={"results": []})

    credentials = discover(SITE, "a@b.c", "scoped-token", transport=transport(handler))

    assert credentials.api_base == GATEWAY
    assert credentials.authorization.startswith("Basic ")
    assert credentials.how == "gateway + basic (scoped token)"
    assert any("tenant_info" in url for url in seen)


def test_a_classic_token_still_works_through_the_site() -> None:
    """Probing rather than hardcoding is what keeps this true."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/_edge/tenant_info"):
            return httpx.Response(404, text="not a cloud site")
        return httpx.Response(200, json={"results": []})

    credentials = discover(SITE, "a@b.c", "classic-token", transport=transport(handler))
    assert credentials.api_base == SITE
    assert credentials.cloud_id is None


def test_a_dead_credential_says_which_half_is_wrong() -> None:
    """The site resolved, so it is the token — and the message says so.

    "401" on its own sends people to the wrong page for an hour.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/_edge/tenant_info"):
            return httpx.Response(200, json={"cloudId": CLOUD_ID})
        return httpx.Response(401, text="Unauthorized")

    with pytest.raises(ConfluenceError, match="the credential is the problem"):
        discover(SITE, "a@b.c", "revoked", transport=transport(handler))


# ------------------------------------------------------------------ reads ---


def test_a_page_is_read_as_storage_format_with_its_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("body-format") == "storage"
        return httpx.Response(200, json=PAGE_BODY)

    with source_with(handler) as client:
        document = client.read("98311")
    assert document.version == 7
    assert "800ms" in document.body
    assert document.blocks[0].text == "above 800ms"


def test_pages_are_filtered_by_label_client_side() -> None:
    """CQL search answers 401 with a scoped token, so this is the only way.

    One extra call per page. On a large space that is the dominant cost of a
    sweep, and it is in BUGS.md rather than hidden here.
    """
    labels = {"1": ["runbook"], "2": ["architecture"], "3": ["runbook", "dr"]}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/labels"):
            page_id = path.split("/")[-2]
            return httpx.Response(200, json={"results": [{"name": n} for n in labels[page_id]]})
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": pid, "title": f"page {pid}", "version": {"number": 1}} for pid in labels
                ]
            },
        )

    with source_with(handler) as client:
        found = client.pages()
    assert [p.page_id for p in found] == ["1", "3"]


def test_pagination_follows_the_cursor() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/labels"):
            return httpx.Response(200, json={"results": [{"name": "runbook"}]})
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "1", "title": "a", "version": {"number": 1}}],
                    "_links": {"next": "/wiki/api/v2/pages?cursor=abc123&limit=250"},
                },
            )
        return httpx.Response(
            200, json={"results": [{"id": "2", "title": "b", "version": {"number": 1}}]}
        )

    with source_with(handler) as client:
        found = client.pages()
    assert [p.page_id for p in found] == ["1", "2"]
    assert calls == [None, "abc123"]


def test_our_own_account_id_is_read_once() -> None:
    """How the watcher ignores its own writes rather than looping on them."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"accountId": "557058:me"})

    with source_with(handler) as client:
        assert client.account_id() == "557058:me"
        assert client.account_id() == "557058:me"
    assert len(calls) == 1


# ----------------------------------------------------------------- writes ---


def test_a_write_increments_the_version_and_keeps_the_title() -> None:
    """Sending an empty title renames the page, so the title is carried through."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            sent.update(json.loads(request.content))
            return httpx.Response(200, json={"version": {"number": 8}})
        return httpx.Response(200, json=PAGE_BODY)

    with source_with(handler) as client:
        version = client.write("98311", "<p>new</p>", 7, title=PAGE_BODY["title"])

    assert version == 8
    assert sent["version"]["number"] == 8
    assert sent["title"] == PAGE_BODY["title"]
    assert sent["body"]["representation"] == "storage"
    assert "runbook-reconciler" in sent["version"]["message"]


def test_a_write_without_a_title_fetches_one_rather_than_sending_blank() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            assert json.loads(request.content)["title"] == PAGE_BODY["title"]
            return httpx.Response(200, json={"version": {"number": 8}})
        return httpx.Response(200, json=PAGE_BODY)

    with source_with(handler) as client:
        client.write("98311", "<p>new</p>", 7)
    assert methods == ["GET", "PUT"]


def test_a_concurrent_edit_raises_rather_than_retrying() -> None:
    """Retrying blind is the worst available response.

    The passage may have moved, or may say something else now. The conflict
    propagates so the caller re-resolves the anchor.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(409, text="version conflict")
        return httpx.Response(200, json=PAGE_BODY)

    with source_with(handler) as client, pytest.raises(VersionConflict, match="re-resolve"):
        client.write("98311", "<p>new</p>", 7, title="t")


def test_a_comment_is_posted_as_a_footer_comment() -> None:
    """An inline comment needs a text anchor.

    The passages that reach this path are exactly the ones whose anchoring this
    tool has just said it cannot do safely, so claiming an inline anchor would
    be a capability present and broken.
    """
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/footer-comments")
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "c1"})

    with source_with(handler) as client:
        assert client.comment("98311", "<p>needs a human</p>") == "c1"
    assert sent["pageId"] == "98311"


def test_an_api_error_names_the_call_that_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Current user not permitted")

    with source_with(handler) as client, pytest.raises(ConfluenceError, match="403"):
        client.read("98311")


# ------------------------------------------------------------------- live ---


@pytest.mark.skipif(
    os.environ.get("RR_LIVE_CONFLUENCE_TESTS") != "1",
    reason=(
        "writes to a real wiki; opt in with RR_LIVE_CONFLUENCE_TESTS=1 and "
        "RR_LIVE_PAGE_ID=<a page you own>"
    ),
)
def test_live_read_write_round_trip() -> None:
    """The only test here that proves Confluence still behaves this way.

    Reads a page you nominate, appends and removes a marker paragraph, and
    asserts the body comes back byte-identical afterwards. It is opt-in and
    needs a page id because a test that writes to somebody's wiki by default is
    a test that should not exist.

    **The marker is deliberately pure ASCII.** The first version used an em dash
    and failed against page 98311 on 2026-08-15: Confluence stored `&mdash;`
    for the `—` that was sent. That is Confluence normalising *new* content, not
    a fault in the round trip, and a test that trips over it is testing the
    wrong thing — see `test_live_an_untouched_body_survives_a_write`, which
    tests the property this project actually depends on.
    """
    from reconciler.config import Config

    config = Config.load()
    page_id = os.environ["RR_LIVE_PAGE_ID"]
    with ConfluenceSource.from_config(config) as client:
        before = client.read(page_id)
        marker = "<p>runbook-reconciler live test - removed immediately</p>"
        version = client.write(page_id, before.body + marker, before.version, before.title)
        try:
            middle = client.read(page_id)
            assert marker in middle.body
        finally:
            client.write(page_id, before.body, version, before.title)
        assert client.read(page_id).body == before.body


@pytest.mark.skipif(
    os.environ.get("RR_LIVE_CONFLUENCE_TESTS") != "1",
    reason="writes to a real wiki; opt in with RR_LIVE_CONFLUENCE_TESTS=1",
)
def test_live_an_untouched_body_survives_a_write() -> None:
    """Rule 2's live half, and it was not obvious it would hold.

    The splice guarantees that *what this tool sends* differs from the original
    in exactly one contiguous range. It cannot, by itself, guarantee what
    Confluence chooses to *store* — and Confluence demonstrably rewrites some
    content on the way in, turning a sent `—` into a stored `&mdash;`.

    If that normalisation applied to the whole body, every write would silently
    change bytes outside the approved passage and the central promise of this
    project would be false through no fault of the splice. It does not: a body
    PUT back unchanged is returned byte-for-byte identical. Verified against
    page 98311 on 2026-08-15, and worth re-running against any site before
    trusting the promise on it.
    """
    from reconciler.config import Config

    config = Config.load()
    page_id = os.environ["RR_LIVE_PAGE_ID"]
    with ConfluenceSource.from_config(config) as client:
        before = client.read(page_id)
        client.write(page_id, before.body, before.version, before.title)

        assert client.read(page_id).body == before.body, (
            "Confluence rewrote a body that was sent back unchanged; the "
            "byte-identity promise cannot be kept on this site"
        )
