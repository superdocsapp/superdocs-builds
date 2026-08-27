"""Starting a review from Notion: a row in the requests database, no terminal involved."""

from __future__ import annotations

from pathlib import Path

from _docx_fixtures import reviewed_docx
from notion_review.config import Config
from notion_review.docx_markup.stamp import identify_round, stamp_round_id
from notion_review.domain import RoundStatus
from notion_review.notion import FakeNotionClient
from notion_review.notion.base import NotionError
from notion_review.notion.queue_schema import STATUS_APPROVED
from notion_review.roundtrip.delivery import Deliverable, FolderDelivery, NotionRowDelivery
from notion_review.roundtrip.intake import FolderIntake, NotionRowIntake
from notion_review.roundtrip.requests import (
    DOCUMENT_PROP,
    RETURNED_PROP,
    STATUS_FAILED,
    STATUS_REQUESTED,
    STATUS_SENT,
    RequestBoards,
    create_request_database,
    files_in,
    request_properties,
)
from notion_review.roundtrip.service import ReviewService
from notion_review.store import SQLiteStore
from notion_review.superdocs import FakeSuperDocsClient


def _status(name: str) -> dict:
    return {"Status": {"select": {"name": name}}}


def _rt(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": value}, "plain_text": value}]}


def _setup(tmp_path: Path) -> tuple[ReviewService, FakeNotionClient, SQLiteStore, str, str, Path]:
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    requests_db = create_request_database(notion, parent_page_id=page_id)
    outbox = tmp_path / "outbox"
    service = ReviewService(
        intake=FolderIntake(tmp_path / "inbox"),
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=Config.from_env({}),
        delivery=FolderDelivery(outbox),
        boards=RequestBoards(notion),
    )
    return service, notion, store, requests_db, page_id, outbox


def _request_row(notion: FakeNotionClient, db: str, page_id: str, reviewers: str) -> str:
    row = notion.create_row(
        database_id=db,
        properties={
            "Page": {
                "title": [{"type": "text", "text": {"content": page_id}, "plain_text": page_id}]
            },
            "Status": {"select": {"name": STATUS_REQUESTED}},
            "Reviewers": _rt(reviewers),
        },
    )
    return row.page_id


def test_a_row_in_notion_sends_the_page_out_for_review(tmp_path: Path) -> None:
    service, notion, store, db, page_id, outbox = _setup(tmp_path)
    row_id = _request_row(notion, db, page_id, "dana@example.com, marcus@example.com")

    report = service.tick()

    assert len(report.sent) == 1
    round_id = report.sent[0]
    round_ = store.get(round_id)
    assert round_ is not None and round_.status == RoundStatus.SENT
    # The document was produced and delivered, stamped so it can find its way home.
    delivered = outbox / f"review-{round_id}.docx"
    assert delivered.exists()
    from notion_review.docx_markup.stamp import read_round_id

    assert read_round_id(delivered.read_bytes()) == round_id
    # And the row tells its own story.
    props = notion.row_properties(row_id)
    assert props["Status"] == {"select": {"name": STATUS_SENT}}
    assert round_id in str(props["Round"])
    assert "outbox" in str(props["Result"])


def test_a_sent_request_is_never_sent_twice(tmp_path: Path) -> None:
    service, notion, _store, db, page_id, _ = _setup(tmp_path)
    _request_row(notion, db, page_id, "dana@example.com")

    first = service.tick()
    second = service.tick()

    assert len(first.sent) == 1
    assert second.sent == []  # the row is no longer Requested


def test_a_row_naming_no_page_is_marked_failed_with_the_reason(tmp_path: Path) -> None:
    service, notion, _, db, _, _ = _setup(tmp_path)
    row_id = _request_row(notion, db, "not a page id at all", "dana@example.com")

    report = service.tick()

    assert report.sent == []
    props = notion.row_properties(row_id)
    assert props["Status"] == {"select": {"name": STATUS_FAILED}}
    assert "page id" in str(props["Result"])


def test_a_page_that_cannot_be_read_marks_the_row_failed(tmp_path: Path) -> None:
    service, notion, _, db, _, _ = _setup(tmp_path)
    missing = "3bb1ec1a70b08171a9b7edfe7fc0ffa5"  # well-formed, but not in this workspace
    row_id = _request_row(notion, db, missing, "dana@example.com")

    report = service.tick()  # must not raise

    assert report.sent == []
    assert notion.row_properties(row_id)["Status"] == {"select": {"name": STATUS_FAILED}}


def test_without_the_trigger_configured_the_service_ignores_requests(tmp_path: Path) -> None:
    # The Notion trigger is optional; a deployment can still drive everything from `send`.
    notion, page_id = FakeNotionClient.build_sample()
    store = SQLiteStore()
    db = create_request_database(notion, parent_page_id=page_id)
    _request_row(notion, db, page_id, "dana@example.com")
    service = ReviewService(
        intake=FolderIntake(tmp_path / "inbox"),
        notion=notion,
        superdocs=FakeSuperDocsClient(),
        store=store,
        config=Config.from_env({}),
    )

    assert service.tick().sent == []


def test_the_requests_schema_is_what_a_person_fills_in() -> None:
    schema = request_properties()
    assert set(schema) == {
        "Page",
        "Status",
        "Page URL",
        "Reviewers",
        "Round",
        "Result",
        "Document",  # the styled .docx goes out here
        "Returned",  # and the reviewers' marked-up copies come back here
        "Taken in",
    }
    options = {o["name"] for o in schema["Status"]["select"]["options"]}
    assert options == {STATUS_REQUESTED, STATUS_SENT, STATUS_FAILED}


def test_folder_delivery_writes_the_document(tmp_path: Path) -> None:
    delivery = FolderDelivery(tmp_path / "out")
    receipt = delivery.deliver(Deliverable(filename="a.docx", content=b"bytes"))
    assert (tmp_path / "out" / "a.docx").read_bytes() == b"bytes"
    assert "a.docx" in receipt


def _notion_row_service(
    tmp_path: Path,
) -> tuple[ReviewService, FakeNotionClient, SQLiteStore, str, str]:
    """The whole handoff inside Notion: no folder anywhere in the loop."""
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    requests_db = create_request_database(notion, parent_page_id=page_id)
    boards = RequestBoards(notion)
    service = ReviewService(
        intake=NotionRowIntake(notion, boards=boards),
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=Config.from_env({}),
        delivery=NotionRowDelivery(notion),
        boards=boards,
    )
    return service, notion, store, requests_db, page_id


def test_the_document_goes_out_attached_to_the_row_that_asked_for_it(tmp_path: Path) -> None:
    service, notion, _, requests_db, page_id = _notion_row_service(tmp_path)
    row = notion.create_row(
        database_id=requests_db,
        properties={
            "Page URL": {"url": f"https://notion.so/{page_id}"},
            **_status(STATUS_REQUESTED),
        },
    )

    report = service.tick()

    assert len(report.sent) == 1
    attached = files_in(notion.row_properties(row.page_id), DOCUMENT_PROP)
    assert len(attached) == 1
    assert attached[0].name == f"review-{report.sent[0]}.docx"
    # And it is the real styled document, carrying its own round id.
    assert identify_round(notion.download_file(attached[0].url), attached[0].name) == report.sent[0]
    assert notion.query_database(requests_db)[0].status == STATUS_SENT


def test_a_copy_dropped_back_on_the_row_is_taken_in_and_applied(tmp_path: Path) -> None:
    service, notion, store, requests_db, page_id = _notion_row_service(tmp_path)
    row = notion.create_row(
        database_id=requests_db,
        properties={
            "Page URL": {"url": f"https://notion.so/{page_id}"},
            **_status(STATUS_REQUESTED),
        },
    )
    round_id = service.tick().sent[0]

    # The reviewer marks up their copy in Word and drags it back onto the same row.
    notion.attach_file(
        row.page_id,
        property_name=RETURNED_PROP,
        content=stamp_round_id(reviewed_docx(), round_id),
        name="marked-up.docx",
    )
    taken = service.tick()

    assert taken.ingested == [round_id]
    round_ = store.get(round_id)
    assert round_ is not None
    aurora = next(e for e in round_.block_map if "Aurora ships in Q3" in e.original_text)
    for proposal in round_.pending():  # the owner approves, still in Notion
        notion.set_row_status(proposal.queue_row_id, STATUS_APPROVED)

    done = service.tick()

    assert done.completed == [round_id]
    assert "Q4" in notion.block_text(aurora.notion_block_id)
    # Nothing was touched twice: a further pass finds no new work on the row.
    assert service.tick().ingested == []


def test_a_returned_file_that_names_no_round_is_reported_on_its_own_row(tmp_path: Path) -> None:
    service, notion, _, requests_db, page_id = _notion_row_service(tmp_path)
    row = notion.create_row(
        database_id=requests_db,
        properties={
            "Page URL": {"url": f"https://notion.so/{page_id}"},
            **_status(STATUS_REQUESTED),
        },
    )
    service.tick()
    notion.attach_file(
        row.page_id, property_name=RETURNED_PROP, content=reviewed_docx(), name="unstamped.docx"
    )

    report = service.tick()

    assert report.rejected == ["unstamped.docx"]
    # The file is left where the reviewer put it, and the row says what went wrong.
    assert len(files_in(notion.row_properties(row.page_id), RETURNED_PROP)) == 1
    assert "round id" in notion.row_text(row.page_id, "Result")


def test_boards_are_discovered_from_what_is_shared_not_from_configuration() -> None:
    # Adding a team is sharing a board in Notion. Nothing is redeployed and no id is configured.
    notion, page_id = FakeNotionClient.build_sample()
    boards = RequestBoards(notion)
    assert boards.ids() == []

    first = create_request_database(notion, parent_page_id=page_id)
    boards = RequestBoards(notion)  # a fresh read, as a restart would do
    assert boards.ids() == [first]

    second = create_request_database(notion, parent_page_id=page_id)
    assert set(RequestBoards(notion).ids()) == {first, second}


def test_our_own_review_queues_are_never_mistaken_for_a_request_board() -> None:
    # Notion's search matches titles loosely, so searching for "Review requests" also returns
    # every "Review queue · round …" database this integration created. Only an exact title is
    # a board; polling a queue for requests would be nonsense.
    notion, page_id = FakeNotionClient.build_sample()
    board = create_request_database(notion, parent_page_id=page_id)
    notion.create_database(
        parent_page_id=page_id, title="Review queue · round round_abc123", properties={}
    )

    assert len(notion.search_databases("Review requests")) == 2  # the search is fuzzy
    assert RequestBoards(notion).ids() == [board]  # discovery is not


def test_a_board_shared_while_running_is_picked_up_without_a_restart() -> None:
    notion, page_id = FakeNotionClient.build_sample()
    now = [1000.0]
    boards = RequestBoards(notion, ttl_s=60.0, clock=lambda: now[0])
    assert boards.ids() == []

    added = create_request_database(notion, parent_page_id=page_id)

    assert boards.ids() == []  # still inside the cache window
    now[0] += 61.0
    assert boards.ids() == [added]  # picked up on the next refresh, no restart


def test_a_pinned_board_skips_discovery_entirely() -> None:
    notion, page_id = FakeNotionClient.build_sample()
    create_request_database(notion, parent_page_id=page_id)

    pinned = RequestBoards(notion, pinned=["db_pinned"])

    assert pinned.ids() == ["db_pinned"]  # a deployment can still serve exactly one board


def test_a_failed_search_keeps_serving_the_boards_already_known() -> None:
    class Flaky(FakeNotionClient):
        broken = False

        def search_databases(self, query: str):  # type: ignore[no-untyped-def]
            if self.broken:
                raise NotionError("search unavailable")
            return super().search_databases(query)

    notion = Flaky()
    page_id = notion.new_page("Home")
    board = create_request_database(notion, parent_page_id=page_id)
    now = [0.0]
    boards = RequestBoards(notion, ttl_s=1.0, clock=lambda: now[0])
    assert boards.ids() == [board]

    notion.broken = True
    now[0] += 5.0

    # Reviews already under way must not stall because discovery had a bad minute.
    assert boards.ids() == [board]


def test_a_board_that_vanished_is_dropped_and_then_retried_once_the_cooldown_passes() -> None:
    # Archiving or unsharing a board makes it unreadable at once, but Notion's search keeps
    # listing it as healthy until the index catches up. Without this the service would
    # rediscover a board it cannot read on every single pass.
    notion, page_id = FakeNotionClient.build_sample()
    board = create_request_database(notion, parent_page_id=page_id)
    now = [0.0]
    boards = RequestBoards(notion, ttl_s=1.0, gone_cooldown_s=100.0, clock=lambda: now[0])
    assert boards.ids() == [board]

    boards.forget(board)  # what a 404 from query_database triggers

    assert boards.ids() == []  # not served, even though search still lists it
    now[0] += 50.0
    assert boards.ids() == []  # still inside the cooldown

    now[0] += 60.0
    # A board archived by mistake and restored must come back, so this is a cooldown and not a
    # tombstone: it is retried, and it is still there.
    assert boards.ids() == [board]


def test_an_archived_board_is_never_served_even_while_search_still_lists_it() -> None:
    class Lagging(FakeNotionClient):
        def search_databases(self, query: str):  # type: ignore[no-untyped-def]
            return [
                db.model_copy(update={"archived": True}) for db in super().search_databases(query)
            ]

    notion = Lagging()
    page_id = notion.new_page("Home")
    create_request_database(notion, parent_page_id=page_id)

    assert len(notion.search_databases("Review requests")) == 1  # search still offers it
    assert RequestBoards(notion).ids() == []  # discovery does not


def test_the_service_forgets_a_board_that_404s_instead_of_warning_forever(tmp_path: Path) -> None:
    notion, page_id = FakeNotionClient.build_sample()
    board = create_request_database(notion, parent_page_id=page_id)
    boards = RequestBoards(notion)
    service = ReviewService(
        intake=NotionRowIntake(notion, boards=boards),
        notion=notion,
        superdocs=FakeSuperDocsClient(),
        store=SQLiteStore(),
        config=Config.from_env({}),
        delivery=NotionRowDelivery(notion),
        boards=boards,
    )
    assert boards.ids() == [board]

    notion.archive_database(board)  # somebody archives it mid-flight
    service.tick()  # must not raise

    assert boards.ids() == []
