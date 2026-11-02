"""Confluence Cloud, through the door that actually opens.

## Auth, which is the part that costs people an afternoon

A **scoped** (granular) API token is rejected by the site host with `401`, which
is indistinguishable from a revoked credential and sends you to the token
management page instead of to the host. It only works through the gateway:

| Host                                             | Basic | Bearer |
|--------------------------------------------------|-------|--------|
| `https://<site>.atlassian.net`                    | 401   | 403    |
| `https://api.atlassian.com/ex/confluence/{cloudId}` | 200 | 200    |

So `discover()` resolves `cloudId` from `GET {site}/_edge/tenant_info` (no auth
needed) and then *probes* the three combinations rather than assuming one. A
classic token still works, and the day somebody swaps token types nothing here
needs changing. The same logic is in `preflight.py`, deliberately duplicated:
that script has to run before anything is installed, including this package.

## Which endpoints are verified, and which are not

Stated because the difference matters to whoever runs this next. Verified live
on 2026-08-15 against a real Cloud site with a scoped token:

- `GET /wiki/api/v2/pages` — with and without `body-format=storage`
- `GET /wiki/api/v2/pages/{id}/labels`
- `GET /wiki/api/v2/labels`
- `GET /wiki/api/v2/spaces`

**Not available, and this shapes the design:** `GET
/wiki/rest/api/content/search?cql=…` answers `401 Unauthorized; scope does not
match` through the gateway with a scoped token, and it was the natural way to
crawl by label. So labels are filtered client-side, one extra call per page. On
a 400-page space that is 400 calls, which is fine for a nightly sweep and would
not be for an interactive one; it is a real cost and it is in BUGS.md rather
than hidden here.

The v1 API as a whole is *not* off limits, which is worth stating because the
first version of this note claimed it was. Reachability follows the token's
granted scopes literally, endpoint by endpoint. Verified 2026-08-15:

    GET  /wiki/rest/api/content/search   401     GET  /wiki/rest/api/content/{id}/label   200
    GET  /wiki/rest/api/content/{id}     401     POST /wiki/rest/api/content/{id}/label   200
    GET  /wiki/rest/api/user/current     401     DELETE .../label/{name}                  204
    GET  /wiki/rest/api/space            401

The label endpoints work because `read:label` and `write:label` are on the
token; the rest are refused because their scopes are not grantable to an API
token. So "v1 is dead" is the wrong lesson and "check the scope for the exact
endpoint" is the right one — v1 labels are the only way to *add* a label, and
`demo/seed.py` depends on them.

*Inferred, not exercised:* `POST /wiki/api/v2/inline-comments` is documented and
has not been run against a live site by this build, because doing so would write
to somebody else's wiki to prove a point. `selftest` has an opt-in stage that
exercises
them against a page you nominate, and it says so loudly rather than skipping
quietly.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from reconciler.confluence.local import PageRef, VersionConflict
from reconciler.extract.storage import Document, parse

TIMEOUT = 30.0


class ConfluenceError(RuntimeError):
    """The API refused, and the message says what it said."""


@dataclass(frozen=True)
class Credentials:
    api_base: str
    authorization: str
    how: str
    cloud_id: str | None = None


def discover(
    site: str,
    email: str,
    token: str,
    timeout: float = TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> Credentials:
    """Find the host and credential combination that answers 200.

    Probing rather than assuming is what keeps this working when the token type
    changes underneath it. See the module docstring for why the obvious
    combination is the one that fails.

    `transport` exists so the probe order can be tested without a network. It is
    a real seam rather than a test hook: the alternative is monkeypatching
    `httpx.Client`, which recurses the moment this function constructs one.
    """
    site = site.rstrip("/")
    basic = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
    candidates: list[tuple[str, str, str]] = []

    cloud_id = None
    with httpx.Client(timeout=timeout, transport=transport) as client:
        try:
            edge = client.get(f"{site}/_edge/tenant_info")
            if edge.status_code == 200:
                cloud_id = edge.json().get("cloudId")
        except httpx.HTTPError:
            cloud_id = None

        if cloud_id:
            gateway = f"https://api.atlassian.com/ex/confluence/{cloud_id}"
            candidates.append((gateway, basic, "gateway + basic (scoped token)"))
            candidates.append((gateway, f"Bearer {token}", "gateway + bearer (scoped token)"))
        candidates.append((site, basic, "site + basic (classic token)"))

        last = None
        for api_base, authorization, how in candidates:
            probe = client.get(
                f"{api_base}/wiki/api/v2/spaces?limit=1",
                headers={"Authorization": authorization, "Accept": "application/json"},
            )
            if probe.status_code == 200:
                return Credentials(api_base, authorization, how, cloud_id)
            last = probe.status_code

    raise ConfluenceError(
        f"no host and credential combination worked (last HTTP {last}). "
        + (
            "The site resolved, so the credential is the problem: check the token is not "
            "revoked and that its scopes include read:page:confluence."
            if cloud_id
            else "The site itself did not resolve; check CONFLUENCE_BASE_URL."
        )
    )


class ConfluenceSource:
    """The live adapter, interchangeable with `LocalSource`.

    Same four operations — list, read, write, comment — so nothing above this
    layer can tell which it is talking to. That is what lets every test in this
    project run without a Confluence site, and what makes the demo's offline
    half honest rather than a separate code path.
    """

    def __init__(
        self,
        credentials: Credentials,
        space_key: str = "",
        label: str = "runbook",
        timeout: float = TIMEOUT,
    ) -> None:
        self.credentials = credentials
        self.space_key = space_key
        self.label = label
        self._client = httpx.Client(
            base_url=credentials.api_base,
            timeout=timeout,
            headers={
                "Authorization": credentials.authorization,
                "Accept": "application/json",
            },
        )
        self._space_id: str | None = None
        self._account_id: str | None = None

    @classmethod
    def from_config(cls, config: Any) -> ConfluenceSource:
        return cls(
            discover(config.confluence_site, config.confluence_email, config.confluence_token),
            space_key=config.space_key,
            label=config.runbook_label,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ConfluenceSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------------------------------------- plumbing --

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self._client.get(path, params={k: v for k, v in params.items() if v is not None})
        return self._read(response)

    @staticmethod
    def _read(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 409:
            raise VersionConflict(response.text[:300])
        if response.status_code >= 400:
            raise ConfluenceError(
                f"{response.request.method} {response.request.url.path} -> "
                f"{response.status_code}: {response.text[:400]}"
            )
        return response.json() if response.content else {}

    # -------------------------------------------------------------- reads --

    def account_id(self) -> str | None:
        """Our own account id, when the token can be told. Usually it cannot.

        **This was designed to be how rule 6 works, and it is not.** The plan
        was to ignore a page version whose `version.authorId` is us. The author
        id is genuinely there in the v2 page payload, so the idea is sound --
        but every route to "who am I" is refused for a scoped API token:

            GET /wiki/api/v2/users/current      -> 401 scope does not match
            GET /wiki/rest/api/user/current     -> 401 scope does not match
            GET https://api.atlassian.com/me    -> 401 Unauthorized

        with `read:user:confluence` granted on the token. `read:me` is an
        account scope rather than a product one and is not grantable to an API
        token at all, which is the underlying reason.

        So this returns None on a scoped token and rule 6 does not rest on it:
        `register.page_writes` records the exact version each of our PUTs
        produced, and the watcher compares against that. Kept because it does
        work with a classic token, where it is a useful second filter -- a
        colleague editing through the same integration account is invisible to
        the version ledger and visible here.
        """
        if self._account_id is None:
            try:
                self._account_id = str(self._get("/wiki/api/v2/users/current").get("accountId", ""))
            except ConfluenceError:
                self._account_id = ""
        return self._account_id or None

    def space_id(self) -> str | None:
        if self._space_id is None and self.space_key:
            results = self._get("/wiki/api/v2/spaces", keys=self.space_key, limit=1).get(
                "results", []
            )
            self._space_id = str(results[0]["id"]) if results else ""
        return self._space_id or None

    def pages(self, limit: int = 250) -> list[PageRef]:
        """Every page carrying the configured label.

        Filtered client-side, because CQL search is unreachable with a scoped
        token (see the module docstring). One extra call per page for its
        labels; on a large space that is the dominant cost of a sweep, and it is
        the reason `rr watch` checks a page list rather than re-crawling.
        """
        out: list[PageRef] = []
        cursor: str | None = None
        space = self.space_id()

        while True:
            page = self._get(
                "/wiki/api/v2/pages",
                limit=min(limit, 250),
                cursor=cursor,
                **({"space-id": space} if space else {}),
            )
            for entry in page.get("results", []):
                page_id = str(entry["id"])
                labels = self.labels(page_id)
                if self.label and self.label not in labels:
                    continue
                version = entry.get("version") or {}
                out.append(
                    PageRef(
                        page_id=page_id,
                        title=str(entry.get("title", "")),
                        version=int(version.get("number", 1)),
                        labels=labels,
                        url=str((entry.get("_links") or {}).get("webui", "")),
                        # Present and correct in the v2 payload, and useless on
                        # its own -- see `account_id` for why the watcher cannot
                        # usually learn which id is ours.
                        author_id=str(version.get("authorId", "")),
                    )
                )
            cursor = _cursor(page)
            if not cursor:
                return out

    def labels(self, page_id: str) -> tuple[str, ...]:
        body = self._get(f"/wiki/api/v2/pages/{page_id}/labels", limit=100)
        return tuple(str(entry.get("name", "")) for entry in body.get("results", []))

    def read(self, page_id: str) -> Document:
        body = self._get(f"/wiki/api/v2/pages/{page_id}", **{"body-format": "storage"})
        storage = ((body.get("body") or {}).get("storage") or {}).get("value", "")
        return parse(
            storage,
            page_id=page_id,
            version=int((body.get("version") or {}).get("number", 1)),
            title=str(body.get("title", "")),
        )

    # ------------------------------------------------------------- writes --

    def write(self, page_id: str, body: str, expected_version: int, title: str = "") -> int:
        """A whole-page PUT with the version incremented, and no retry on conflict.

        The version number is optimistic concurrency for free: a human edit
        landing between the read and this write fails it. Retrying blind would
        be the worst possible response — the passage may have moved or may say
        something different now — so the conflict propagates and the caller
        re-resolves the anchor.

        `title` is required by the API even for a body-only change, so it is
        carried through from the read rather than being invented here; sending
        an empty one renames the page.
        """
        if not title:
            title = str(
                self._get(f"/wiki/api/v2/pages/{page_id}").get("title", "")
            )  # never send a blank title
        payload = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": body},
            "version": {
                "number": expected_version + 1,
                "message": "runbook-reconciler: approved fix to one passage",
            },
        }
        response = self._client.put(f"/wiki/api/v2/pages/{page_id}", json=payload)
        if response.status_code == 409:
            raise VersionConflict(
                f"page {page_id} moved past version {expected_version} while this edit was "
                f"being reviewed; re-resolve the anchor rather than retrying"
            )
        return int((self._read(response).get("version") or {}).get("number", expected_version + 1))

    def comment(self, page_id: str, text: str) -> str:
        """The fallback for a passage this tool refuses to edit.

        A footer comment rather than an inline one: an inline comment needs a
        text selection to anchor to, and the passages that reach this path are
        exactly the ones whose anchoring this tool has just declared it cannot
        do safely. Claiming an inline anchor here would be a capability present
        and broken.
        """
        body = self._read(
            self._client.post(
                "/wiki/api/v2/footer-comments",
                json={
                    "pageId": page_id,
                    "body": {"representation": "storage", "value": text},
                },
            )
        )
        return str(body.get("id", ""))


def _cursor(body: dict[str, Any]) -> str | None:
    """Confluence paginates with an opaque cursor inside a `next` URL."""
    next_link = ((body.get("_links") or {}).get("next")) or ""
    if "cursor=" not in next_link:
        return None
    return next_link.split("cursor=", 1)[1].split("&", 1)[0]


__all__ = ["ConfluenceError", "ConfluenceSource", "Credentials", "discover"]
