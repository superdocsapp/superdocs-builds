"""The HTTP layer, against a real Postgres.

Marked ``postgres`` and skipped without a database, like `test_store.py`. `make test-db` runs
these.

This file exists because the API had no tests at all, and two bugs lived in that gap. Both
were found by using the running application rather than by reading it, which is the argument
for the file: every check here goes through the routes an inspector's browser actually calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from inspection_report.api.app import app
from inspection_report.store import db

pytestmark = pytest.mark.postgres


@pytest.fixture
def client():  # type: ignore[no-untyped-def]
    try:
        with db.connect():
            pass
    except Exception as exc:
        pytest.skip(f"needs a Postgres ({type(exc).__name__}); try `make test-db`")
    with db.connect() as conn:
        db.apply_schema(conn)
        before = _inspection_ids(conn)
    with TestClient(app) as c:
        yield c
    # Clean up only what this test made, through the application's own delete so the
    # photograph blobs are reclaimed with the rows.
    with db.connect() as conn:
        for made in _inspection_ids(conn) - before:
            db.delete_inspection(conn, made)


def _inspection_ids(conn) -> set:  # type: ignore[no-untyped-def]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM inspections")
        return {row["id"] for row in cur.fetchall()}


def _new_inspection(client) -> str:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/inspections",
        json={
            "property": {"address_line": "9 Test Row", "city": "Fairhaven", "postcode": "FH1 1AA"},
            "inspector": {"name": "A Tester", "licence_number": "T-1", "firm_name": "Test Co"},
            "inspected_on": "2026-08-16",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_a_malformed_body_is_a_422_not_a_database_outage(client) -> None:  # type: ignore[no-untyped-def]
    """A bad request must not be reported as the database being down.

    `get_conn` is a yielding dependency, which is also where FastAPI re-raises whatever the
    endpoint threw — so its catch-all was relabelling request-validation errors as "the
    database is not reachable" while the database answered every other call in the same
    second. The cost is not the status code, it is that the message names the wrong system.
    """
    inspection_id = _new_inspection(client)

    response = client.post(
        f"/api/inspections/{inspection_id}/decisions",
        json={"nested": {"not": "a bool"}},
    )

    assert response.status_code == 422, response.text
    assert "database" not in response.text.lower()


def test_the_database_is_still_reported_when_it_really_is_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The narrowed handler must not have bought its correctness by going silent.

    Refusing to name a real outage would be the same failure in the other direction, so this
    points the application at a port nothing is listening on and expects the 503 to survive.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://inspect:inspect@127.0.0.1:1/inspect")
    with TestClient(app) as offline:
        response = offline.get("/api/inspections")

    assert response.status_code == 503
    assert "not reachable" in response.json()["detail"]


def test_health_and_ready_disagree_when_the_database_is_gone(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Liveness is not readiness: /health stays up so a blip is not a restart loop."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://inspect:inspect@127.0.0.1:1/inspect")
    with TestClient(app) as offline:
        assert offline.get("/health").status_code == 200
        assert offline.get("/ready").status_code == 503


class TestTheReportIsBuiltOnWhatSuperDocsReturns:
    """The format is SuperDocs' document, not our local file.

    The round trip existed and was exercised only by the CLI: the API and the worker both
    called `_template_html`, the documented *fallback*. So the running application — the one
    an inspector uses and the one in the demo — never asked SuperDocs for the format at all,
    while the README described a round trip. These pin the wiring, not the registry, which
    has its own tests.
    """

    def test_the_skeleton_comes_from_the_service(self, client) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.api import app as appmod

        with db.connect() as conn:
            _forget_skeletons(conn)
            html, source = appmod._materialised_template(conn, "buyer_summary")

        assert source == "superdocs"
        assert html.strip(), "an empty skeleton is not a format"

    def test_a_format_costs_one_operation_per_version_not_one_per_report(self, client) -> None:  # type: ignore[no-untyped-def]
        """Held against the format's content hash, so daily reports do not each pay for it."""
        from inspection_report.api import app as appmod

        with db.connect() as conn:
            _forget_skeletons(conn)
            first_html, first = appmod._materialised_template(conn, "buyer_summary")
            second_html, second = appmod._materialised_template(conn, "buyer_summary")

        assert (first, second) == ("superdocs", "cache")
        assert first_html == second_html, "the cache must return the same document"

    def test_an_unknown_format_is_refused_by_name(self, client) -> None:  # type: ignore[no-untyped-def]
        """And says which formats exist, rather than failing somewhere further in."""
        from fastapi import HTTPException

        from inspection_report.api import app as appmod

        with db.connect() as conn, pytest.raises(HTTPException) as exc:
            appmod._materialised_template(conn, "no-such-format")

        assert exc.value.status_code == 400
        assert "buyer_summary" in str(exc.value.detail)

    def test_a_skeleton_from_one_provider_is_never_served_to_another(self, client) -> None:  # type: ignore[no-untyped-def]
        """The cache must not be able to launder a fake document into a live run.

        Keyed on the format's content hash alone, it could: the hash describes the .docx we
        registered, not the document that came back. A live run would then have reported
        `cache` and built the report on bytes the offline fake produced — undoing the one
        thing the round trip is there to establish.
        """
        from inspection_report.api import app as appmod

        with db.connect() as conn:
            _forget_skeletons(conn)
            _, source = appmod._materialised_template(conn, "buyer_summary")
            assert source == "superdocs"

            # The same format bytes, asked for by a different provider.
            assert db.load_skeleton(conn, _sha_of("buyer_summary"), "fake") is not None
            assert db.load_skeleton(conn, _sha_of("buyer_summary"), "live") is None


def _sha_of(key: str) -> str:
    from inspection_report.api.app import TEMPLATE_DIR
    from inspection_report.templates import registry

    return registry.content_sha((TEMPLATE_DIR / f"{key}.docx").read_bytes())


def _forget_skeletons(conn) -> None:  # type: ignore[no-untyped-def]
    """Start cold. Safe to drop: it is a cache, re-materialised on demand."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM template_skeletons")
    conn.commit()
