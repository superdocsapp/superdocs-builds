"""8B — scan, confirm, dismiss, and the log that outlives all three.

Driven through the real routes with the real store, on the recorded document
that hides an SSN in a tracked deletion and a card number in a comment. No
keys, no network, no Word: tier 3 is off in this suite, which means every
assertion below is about what the pane does with findings rather than about
whether a model produced them.

The claim under test is narrow and it is the assignment's: **nothing is removed
without a human click, and the log records what happened rather than what was
intended.**
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import UNIDENTIFIED, create_app
from service.settings import Settings

# Vendored beside the tests, not read from a repository root. This project
# ships as a standalone pull request, so it may not assume anything exists
# outside its own folder — the same reason `_portable/` holds a copy of the
# shared client rather than importing it.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "superdocs_responses"

SSN = "123-45-6789"
CARD = "4111 1111 1111 1111"


def client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path, **overrides)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def upload(
    api: TestClient, *, session_id: str = "", reviewer: str = "", name: str = "hidden.docx"
) -> dict:
    data = (FIXTURES / "13_hidden_export.docx").read_bytes()
    response = api.post(
        "/scan",
        files={"file": (name, data, "application/octet-stream")},
        data={"session_id": session_id, "reviewer": reviewer},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    return client(tmp_path)


class TestScan:
    def test_it_finds_what_the_body_hides(self, api: TestClient) -> None:
        body = upload(api)
        by_part = {row["part_type"]: row["text"] for row in body["candidates"]}

        assert by_part["tracked_del"] == SSN
        assert by_part["comment"] == CARD

    def test_every_candidate_starts_pending(self, api: TestClient) -> None:
        """There is no route that creates a confirmed candidate. The state
        machine cannot skip the human, by construction rather than by policy."""
        assert {row["status"] for row in upload(api)["candidates"]} == {"pending"}

    def test_it_reports_which_tiers_ran(self, api: TestClient) -> None:
        """With no key this scan saw patterns only. Returning an empty list
        without saying that would let "nothing found" mean two different
        things."""
        body = upload(api)

        assert body["scan"]["tiers"] == ["patterns"]
        assert body["scan"]["llm_blocks"] == 0

    def test_it_reports_where_it_looked(self, api: TestClient) -> None:
        """"Nothing found" is worth little; "nothing found across 6 body blocks,
        1 comment and 1 tracked deletion" is checkable against the document."""
        coverage = upload(api)["scan"]["coverage"]

        assert coverage["body"] > 0
        assert coverage["comment"] == 1
        assert coverage["tracked_del"] == 1

    def test_the_boundary_is_on_the_scan_response(self, api: TestClient) -> None:
        body = upload(api)

        assert "comments" in body["covers"]
        assert "docProps" in body["does_not_cover"]

    def test_an_empty_upload_is_refused_rather_than_reported_clean(
        self, api: TestClient
    ) -> None:
        response = api.post(
            "/scan", files={"file": ("empty.docx", b"", "application/octet-stream")}
        )

        assert response.status_code == 400

    def test_something_that_is_not_a_document_is_refused_by_name(
        self, api: TestClient
    ) -> None:
        """A 415 saying what is wrong, not a 200 with an empty list — which a
        reviewer would read as "your document is clean"."""
        response = api.post(
            "/scan", files={"file": ("photo.zip", b"PK\x03\x04broken", "application/zip")}
        )

        assert response.status_code == 415


class TestRescan:
    def test_a_rescan_of_the_same_session_adds_nothing_new(self, api: TestClient) -> None:
        first = upload(api)
        second = upload(api, session_id=first["session_id"])

        assert second["session_id"] == first["session_id"]
        assert second["scan"]["new"] == 0
        assert len(second["candidates"]) == len(first["candidates"])

    def test_a_rescan_does_not_reset_a_decision(self, api: TestClient) -> None:
        """The one that matters. A reviewer types a sentence, re-scans, and the
        eleven things they already answered must not come back as questions."""
        first = upload(api)
        target = first["candidates"][0]
        api.post(f"/candidates/{target['id']}/dismiss", json={"reviewer": "R"})

        after = upload(api, session_id=first["session_id"])
        same = next(row for row in after["candidates"] if row["id"] == target["id"])

        assert same["status"] == "dismissed"

    def test_scanning_without_a_session_id_opens_a_new_one(self, api: TestClient) -> None:
        assert upload(api)["session_id"] != upload(api)["session_id"]

    def test_an_unknown_session_id_does_not_lose_the_scan(self, api: TestClient) -> None:
        """A stale id from a reloaded pane must not 404 the one button that
        works. It opens a fresh session and says which one it used."""
        body = upload(api, session_id="00000000-0000-0000-0000-000000000000")

        assert body["session_id"] != "00000000-0000-0000-0000-000000000000"
        assert body["candidates"]


class TestDecisions:
    def test_dismissing_records_that_somebody_looked(self, api: TestClient) -> None:
        body = upload(api, reviewer="Priya")
        target = body["candidates"][0]

        response = api.post(f"/candidates/{target['id']}/dismiss", json={"reviewer": "Priya"})

        assert response.json()["candidate"]["status"] == "dismissed"
        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        assert [entry["text"] for entry in log["dismissed"]] == [target["text"]]

    def test_a_successful_redaction_is_logged_with_the_text_and_the_actor(
        self, api: TestClient
    ) -> None:
        body = upload(api, reviewer="Priya")
        target = next(row for row in body["candidates"] if row["text"] == CARD)

        api.post(
            f"/candidates/{target['id']}/redacted",
            json={"applied": 1, "failed": [], "reviewer": "Priya"},
        )

        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        removed = log["removed"]
        assert len(removed) == 1
        assert removed[0]["text"] == CARD
        assert removed[0]["reviewer"] == "Priya"
        assert removed[0]["part_type"] == "comment"
        assert removed[0]["chunk_id"] == "comments:0"
        assert removed[0]["marker"] == "[CREDIT CARD REDACTED]"

    def test_a_failed_redaction_is_not_logged_as_a_removal(self, api: TestClient) -> None:
        """The failure this whole tool exists to prevent.

        Word cannot replace text inside a tracked deletion — `search` does not
        match struck-through runs. If that came back as "redacted", the log
        would state a document is clean while the SSN is still in the file.
        """
        body = upload(api)
        target = next(row for row in body["candidates"] if row["part_type"] == "tracked_del")

        response = api.post(
            f"/candidates/{target['id']}/redacted",
            json={
                "applied": 0,
                "failed": [{"text": SSN, "reason": "inside a tracked change — not editable"}],
            },
        )

        assert response.json()["candidate"]["status"] == "failed"
        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        assert log["removed"] == []
        assert len(log["failed"]) == 1

    def test_zero_occurrences_replaced_is_a_failure_even_with_no_error(
        self, api: TestClient
    ) -> None:
        """A host that reports success having changed nothing is the quiet
        version of the same lie."""
        body = upload(api)
        target = body["candidates"][0]

        response = api.post(
            f"/candidates/{target['id']}/redacted", json={"applied": 0, "failed": []}
        )

        assert response.json()["candidate"]["status"] == "failed"

    def test_deciding_on_a_candidate_that_does_not_exist_is_a_404(
        self, api: TestClient
    ) -> None:
        assert api.post("/candidates/nope/dismiss", json={}).status_code == 404
        assert api.post("/candidates/nope/redacted", json={"applied": 1}).status_code == 404


class TestTheLog:
    def test_an_unnamed_reviewer_is_recorded_as_unidentified_not_invented(
        self, api: TestClient
    ) -> None:
        body = upload(api)
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/redacted", json={"applied": 2, "failed": []})

        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()

        assert log["removed"][0]["reviewer"] == UNIDENTIFIED

    def test_the_log_states_what_it_does_not_cover(self, api: TestClient) -> None:
        body = upload(api)
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/redacted", json={"applied": 1, "failed": []})
        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()

        assert "docProps" in log["does_not_cover"]
        assert "not a certificate" in log["does_not_cover"]

    def test_the_page_renders_and_escapes_the_document_text(self, tmp_path: Path) -> None:
        """Every string on that page came out of somebody's contract. A
        document containing `<script>` must not run it in the reviewer's
        browser — untrusted input on the way out as much as on the way in.
        """
        api = client(tmp_path)
        # Three strings, three routes into the page, none of them ours: the
        # filename comes from the document, the reviewer name is typed, and the
        # redacted text is whatever the contract said.
        response = api.post(
            "/scan",
            files={
                "file": (
                    "<script>alert('name')</script>.txt",
                    b"Contact <img src=x onerror=alert('body')> on 123-45-6789",
                    "text/plain",
                )
            },
            data={"reviewer": "<script>alert('who')</script>"},
        )
        document_hash = response.json()["document_hash"]
        target = response.json()["candidates"][0]
        api.post(
            f"/candidates/{target['id']}/dismiss",
            json={"reviewer": "<script>alert('who')</script>", "reason": "<b>keep</b>"},
        )

        page = api.get("/audit", params={"document": document_hash})

        assert page.status_code == 200
        assert "<script>" not in page.text
        assert "<b>keep</b>" not in page.text
        assert page.text.count("&lt;script&gt;") >= 2

    def test_the_log_is_reachable_without_a_document_hash(self, api: TestClient) -> None:
        """The pane can be reloaded; the log it produced still has to open."""
        body = upload(api)
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/redacted", json={"applied": 1, "failed": []})

        assert api.get("/audit").status_code == 200

    def test_with_nothing_logged_it_says_so_rather_than_showing_an_empty_log(
        self, tmp_path: Path
    ) -> None:
        assert client(tmp_path).get("/audit").status_code == 404


class TestNothingSensitiveIsPersisted:
    """The review is in memory; only the log reaches a disk."""

    def test_a_scan_alone_writes_nothing(self, tmp_path: Path) -> None:
        """Twenty-four findings, each quoting somebody's contract, and not one
        of them on disk until a human decides something."""
        api = client(tmp_path)
        assert upload(api)["candidates"]

        assert _log_rows(tmp_path) == 0

    def test_only_the_decision_is_written(self, tmp_path: Path) -> None:
        api = client(tmp_path)
        body = upload(api)
        api.post(f"/candidates/{body['candidates'][0]['id']}/dismiss", json={})

        assert _log_rows(tmp_path) == 1

    def test_a_restart_loses_the_review_and_keeps_the_log(self, tmp_path: Path) -> None:
        """Exactly what "in memory" means, asserted rather than described.

        A new app over the same data directory is what a container restart is.
        The candidate is gone; the record of the decision is not.
        """
        first = client(tmp_path)
        body = upload(first)
        target = body["candidates"][0]
        first.post(f"/candidates/{target['id']}/dismiss", json={})

        restarted = client(tmp_path)

        assert restarted.post(f"/candidates/{target['id']}/dismiss", json={}).status_code == 404
        assert len(restarted.get("/audit.json").json()["dismissed"]) == 1

    def test_the_404_tells_a_reviewer_what_to_do(self, tmp_path: Path) -> None:
        """"Not Found" for a candidate the pane is still showing is baffling.
        The reason it vanished is the design, so the message says so."""
        detail = client(tmp_path).post("/candidates/gone/dismiss", json={}).json()["detail"]

        assert "reloaded" in detail
        assert "Scan again" in detail

    def test_abandoned_sessions_do_not_accumulate(self, tmp_path: Path) -> None:
        """A pane reload orphans a session. Without a cap, a long-running
        service would hold every document anybody ever scanned — the same
        problem as writing them down, in RAM."""
        api = client(tmp_path)
        review = api.app.state.review  # type: ignore[attr-defined]
        for _ in range(review._max + 4):
            upload(api)

        assert len(review._sessions) == review._max


def _log_rows(data_dir: Path) -> int:
    import sqlite3

    database = data_dir / "db" / "redaction.db"
    if not database.exists():
        return 0
    with sqlite3.connect(database) as conn:
        return int(conn.execute("SELECT count(*) FROM redaction_log").fetchone()[0])


class TestATierFailingMidScan:
    """Absence degrades; it never crashes. Found the hard way, on a live
    machine whose DNS went down between two scans — the provider call raised,
    and a 500 took out the only button in the pane along with the fourteen
    pattern findings that were already in hand."""

    class Exploding:
        def structured(self, **_: object) -> tuple[dict, object]:
            raise ConnectionError("Connection error.")

    def test_the_scan_still_returns_what_the_other_tiers_found(
        self, tmp_path: Path
    ) -> None:
        # A key, so tier 3 is genuinely configured — the failure under test is
        # a working configuration whose provider stopped answering, not an
        # absent one, which `missing_requirements` already covers.
        api = client(tmp_path, openai_api_key="sk-test")
        api.app.state.scanner._llm = self.Exploding()  # type: ignore[attr-defined]

        body = upload(api)

        assert body["candidates"], "pattern findings must survive a tier 3 outage"

    def test_it_stops_claiming_the_tier_ran(self, tmp_path: Path) -> None:
        """The line that keeps "nothing found" honest. If `llm` stayed in the
        list, a scan that never reached the provider would look like a scan
        that reached it and found nothing."""
        api = client(tmp_path, openai_api_key="sk-test")
        api.app.state.scanner._llm = self.Exploding()  # type: ignore[attr-defined]

        scan = upload(api)["scan"]

        assert "llm" not in scan["tiers"]
        assert any("Tier 3 stopped partway" in note for note in scan["notes"])
        assert any("Connection error" in note for note in scan["notes"])

    def test_it_gives_up_after_the_first_failure(self, tmp_path: Path) -> None:
        """Twelve blocks must not mean twelve failed calls, each with its own
        retries — that turns a four-second scan into a two-minute one and ends
        in exactly the same place."""
        calls = {"n": 0}

        class Counting(self.Exploding):
            def structured(self, **kwargs: object) -> tuple[dict, object]:
                calls["n"] += 1
                return super().structured(**kwargs)

        api = client(tmp_path, openai_api_key="sk-test")
        api.app.state.scanner._llm = Counting()  # type: ignore[attr-defined]
        upload(api)

        assert calls["n"] == 1


class TestUndo:
    """A decision a reviewer can take back — and a log that still remembers."""

    def test_a_dismissal_returns_to_pending(self, api: TestClient) -> None:
        body = upload(api)
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/dismiss", json={})

        response = api.post(f"/candidates/{target['id']}/revert", json={"reviewer": "Priya"})

        assert response.json()["candidate"]["status"] == "pending"

    def test_a_rescan_still_shows_it_as_pending(self, api: TestClient) -> None:
        """The row is answerable again, not resurrected as something new."""
        body = upload(api)
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/redacted", json={"applied": 1, "failed": []})
        api.post(f"/candidates/{target['id']}/revert", json={})

        after = upload(api, session_id=body["session_id"])
        same = next(row for row in after["candidates"] if row["id"] == target["id"])

        assert same["status"] == "pending"
        assert after["scan"]["new"] == 0

    def test_the_removal_stays_in_the_log(self, api: TestClient) -> None:
        """**The rule this feature could most easily break.** A log records what
        happened, not what is currently true. The text WAS removed and then put
        back; erasing the first half would make the log agree with the document
        at the cost of being false about the past."""
        body = upload(api, reviewer="Priya")
        target = next(row for row in body["candidates"] if row["text"] == CARD)
        api.post(
            f"/candidates/{target['id']}/redacted",
            json={"applied": 1, "failed": [], "reviewer": "Priya"},
        )

        api.post(f"/candidates/{target['id']}/revert", json={"reviewer": "Priya"})

        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        assert len(log["removed"]) == 1, "the removal is history and stays"
        assert len(log["reverted"]) == 1
        assert log["reverted"][0]["text"] == CARD
        assert log["reverted"][0]["reviewer"] == "Priya"

    def test_the_revert_records_what_it_undid(self, api: TestClient) -> None:
        body = upload(api)
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/dismiss", json={})
        api.post(f"/candidates/{target['id']}/revert", json={})

        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        assert "dismissed" in log["reverted"][0]["detail"]

    def test_undoing_something_never_decided_is_refused(self, api: TestClient) -> None:
        """Otherwise the log would carry a revert of a decision nobody made."""
        body = upload(api)

        response = api.post(f"/candidates/{body['candidates'][0]['id']}/revert", json={})

        assert response.status_code == 409

    def test_undoing_a_vanished_review_says_so(self, tmp_path: Path) -> None:
        assert client(tmp_path).post("/candidates/gone/revert", json={}).status_code == 404


class TestDownloadingTheLog:
    """The pane cannot download a file, so the service writes one.

    A Word task pane is a sandboxed iframe: `window.open` is blocked and an
    `<a download>` on a blob URL is inert in the Office WebView. Both fail the
    way the old audit-log button failed — silently. The service has a writable
    directory mounted from the host, so it writes there and reports the path.
    """

    def test_it_writes_the_log_and_says_where(self, tmp_path: Path) -> None:
        api = client(tmp_path)
        body = upload(api, reviewer="Priya")
        target = body["candidates"][0]
        api.post(f"/candidates/{target['id']}/dismiss", json={"reviewer": "Priya"})

        written = api.post(
            "/audit/download", params={"document": body["document_hash"]}
        ).json()

        assert written["path"].startswith("data/logs/")
        assert written["path"].endswith(".csv")
        assert (tmp_path / "logs" / Path(written["path"]).name).exists()
        assert written["entries"] == 1
        # One file, not two. The pane asks for a spreadsheet; the boundary the
        # CSV cannot carry is served at /audit.json instead.
        assert sorted(p.suffix for p in (tmp_path / "logs").iterdir()) == [".csv"]

    def test_the_boundary_is_still_reachable_even_though_the_csv_cannot_hold_it(
        self, api: TestClient
    ) -> None:
        """A log claiming more coverage than the tool has is worse than none. A
        spreadsheet cannot state that without junk rows above the header, so it
        is served beside the file rather than dropped."""
        body = upload(api, reviewer="Priya")
        target = next(row for row in body["candidates"] if row["text"] == CARD)
        api.post(
            f"/candidates/{target['id']}/redacted",
            json={"applied": 1, "failed": [], "reviewer": "Priya"},
        )
        api.post("/audit/download")

        served = api.get("/audit.json", params={"document": body["document_hash"]}).json()

        assert served["removed"][0]["text"] == CARD
        assert "docProps" in served["does_not_cover"]
        assert "not a certificate" in served["does_not_cover"]

    def test_a_second_download_does_not_overwrite_the_first(
        self, tmp_path: Path
    ) -> None:
        """Overwriting would destroy the log somebody exported before their last
        four decisions."""
        api = client(tmp_path)
        body = upload(api)
        api.post(f"/candidates/{body['candidates'][0]['id']}/dismiss", json={})

        first = api.post("/audit/download").json()["path"]
        api.post(f"/candidates/{body['candidates'][1]['id']}/dismiss", json={})
        second = api.post("/audit/download").json()

        assert second["path"] != first
        assert second["entries"] == 2
        assert len(list((tmp_path / "logs").glob("*.csv"))) == 2

    def test_a_hostile_document_name_cannot_escape_the_folder(
        self, tmp_path: Path
    ) -> None:
        """The filename comes from the open document, and `../../etc/passwd` is
        a legal thing to call a file."""
        api = client(tmp_path)
        body = upload(api, name="../../../etc/passwd.docx")
        api.post(f"/candidates/{body['candidates'][0]['id']}/dismiss", json={})

        written = api.post("/audit/download").json()
        name = Path(written["path"]).name

        assert "/" not in name
        assert ".." not in name
        assert (tmp_path / "logs" / name).exists()

    def test_downloading_with_nothing_logged_says_so(self, tmp_path: Path) -> None:
        assert client(tmp_path).post("/audit/download").status_code == 404


class TestTheCsvLog:
    def test_it_has_a_header_and_one_row_per_decision(self, tmp_path: Path) -> None:
        import csv as csvlib

        api = client(tmp_path)
        body = upload(api, reviewer="Priya")
        api.post(f"/candidates/{body['candidates'][0]['id']}/dismiss", json={"reviewer": "Priya"})
        target = next(row for row in body["candidates"] if row["text"] == CARD)
        api.post(
            f"/candidates/{target['id']}/redacted",
            json={"applied": 1, "failed": [], "reviewer": "Priya"},
        )

        written = api.post("/audit/download").json()
        rows = list(csvlib.DictReader((tmp_path / "logs" / Path(written["path"]).name).open()))

        assert [row["action"] for row in rows] == ["dismissed", "redacted"]
        assert rows[1]["text"] == CARD
        assert rows[1]["replaced_with"] == "[CREDIT CARD REDACTED]"
        assert rows[1]["part"] == "comment"
        assert rows[1]["reviewer"] == "Priya"

    def test_a_formula_in_the_document_cannot_execute_in_excel(
        self, tmp_path: Path
    ) -> None:
        """CSV injection. Every `text` cell is verbatim contract content, so a
        document containing `=HYPERLINK(...)` becomes a live formula the moment
        the log is opened in Excel — the same class of hole the audit page's
        HTML escaping closes."""
        import csv as csvlib

        api = client(tmp_path)
        body = api.post(
            "/scan",
            files={"file": ("x.txt", b'=cmd|" /c calc"!A1 and 123-45-6789', "text/plain")},
        ).json()
        api.post(f"/candidates/{body['candidates'][0]['id']}/dismiss", json={})

        written = api.post("/audit/download").json()
        raw = (tmp_path / "logs" / Path(written["path"]).name).read_text()
        rows = list(csvlib.DictReader((tmp_path / "logs" / Path(written["path"]).name).open()))

        assert "\n=" not in raw and not raw.split("\n")[1].startswith("=")
        for row in rows:
            for value in row.values():
                assert not str(value).startswith(("=", "+", "@")), value


class TestMarkers:
    def test_each_candidate_carries_what_will_replace_it(self, api: TestClient) -> None:
        """The pane shows it, Word writes it, the log records it — one field, so
        the three cannot disagree about what was left in the document."""
        by_text = {row["text"]: row for row in upload(api)["candidates"]}

        assert by_text[CARD]["marker"] == "[CREDIT CARD REDACTED]"
        assert by_text[SSN]["marker"] == "[SSN REDACTED]"

    def test_the_log_records_the_marker_the_pane_actually_wrote(
        self, api: TestClient
    ) -> None:
        """A tracked deletion is removed by **accepting the change**, so no
        marker goes into the document. Recording the candidate's marker anyway
        would put a string in the log that appears nowhere in the file."""
        body = upload(api)
        target = next(row for row in body["candidates"] if row["part_type"] == "tracked_del")

        api.post(
            f"/candidates/{target['id']}/redacted",
            json={
                "applied": 1,
                "failed": [],
                "marker": "",
                "detail": "removed by accepting the tracked deletion",
            },
        )

        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        row = log["removed"][0]
        assert row["marker"] == ""
        assert row["detail"] == "removed by accepting the tracked deletion"

    def test_it_falls_back_to_the_candidate_marker_when_none_is_sent(
        self, api: TestClient
    ) -> None:
        body = upload(api)
        target = next(row for row in body["candidates"] if row["text"] == CARD)

        api.post(f"/candidates/{target['id']}/redacted", json={"applied": 1, "failed": []})

        log = api.get("/audit.json", params={"document": body["document_hash"]}).json()
        assert log["removed"][0]["marker"] == "[CREDIT CARD REDACTED]"


class TestNothingIsRemovedByTheService:
    def test_there_is_no_route_that_edits_a_document(self, api: TestClient) -> None:
        """Asserted against the route table, not against a promise in a README.

        Every mutating route records a decision. If somebody later adds a
        `/redact` that performs the removal server-side, this fails — which is
        the point: the human click is the only path, and a test is the only
        thing that keeps it that way.
        """
        paths = {route.path for route in api.app.routes}  # type: ignore[attr-defined]

        assert paths >= {"/scan", "/candidates/{candidate_id}/dismiss", "/audit"}
        assert not any(path.rstrip("/").endswith("/redact") for path in paths)
