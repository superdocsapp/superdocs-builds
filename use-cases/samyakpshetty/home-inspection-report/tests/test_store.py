"""The database, against a real Postgres.

Marked ``postgres`` and skipped when there is no database, so the keyless suite stays keyless
and a stranger's `make check` is unaffected. `make test-db` runs these.

This file exists because of a bug that could not have been caught anywhere else. Saving an
inspection cleared its findings and re-inserted them, and ``photos.finding_id`` is
``ON DELETE CASCADE`` — so every photograph on the inspection was destroyed by the ordinary
act of recording the next finding. No amount of testing against the in-memory fake would have
seen it: the cascade is a property of the schema, not of the code.
"""

from __future__ import annotations

import pytest

from inspection_report import sample
from inspection_report.domain.models import Finding
from inspection_report.photos.pipeline import clean
from inspection_report.store import db

pytestmark = pytest.mark.postgres


@pytest.fixture
def conn():  # type: ignore[no-untyped-def]
    """A database, or a skip.

    `DATABASE_URL` is set by compose even when the db service is not running, so its presence
    proves nothing — the only honest check is whether a connection opens. Without that, a
    stranger running `make check` on a fresh clone gets four errors instead of a green run,
    which is the opposite of the promise the README makes.
    """
    try:
        with db.connect():
            pass
    except Exception as exc:
        # Any connection failure means "no database here", so the kind does not matter.
        pytest.skip(f"needs a Postgres ({type(exc).__name__}); try `make test-db`")
    with db.connect() as connection:
        db.apply_schema(connection)
        before = _inspection_ids(connection)
        yield connection
        # Remove only what this test made, so a developer's own data survives a test run.
        # Through the application's own delete, not raw SQL: that is what reclaims the
        # blobs. Deleting the rows directly left the photographs on the volume — a tidy
        # database and a growing disk.
        for made_id in _inspection_ids(connection) - before:
            db.delete_inspection(connection, made_id)


def _inspection_ids(connection) -> set:  # type: ignore[no-untyped-def]
    with connection.cursor() as cur:
        cur.execute("SELECT id FROM inspections")
        return {row["id"] for row in cur.fetchall()}


def _seeded(connection, *, store=None, mark: str = "") -> object:  # type: ignore[no-untyped-def]
    """One inspection with a photograph on its first finding.

    Registered with the fixture so it is removed afterwards. These tests run against the same
    database the application uses, and leaving rows behind filled the inspector's list with
    173 copies of the sample property — a test that litters the product it is testing.

    ``mark`` makes the photograph's *bytes* unique. Blob keys are content hashes, so a test
    that asserts a blob was reclaimed must not share its content with anything else in the
    database — the seeded sample property alone was enough to keep the key referenced and
    make the reclaim look broken when it was working exactly as designed.
    """
    inspection = sample.sample_inspection()
    inspection.findings = inspection.findings[:2]
    db.save_inspection(connection, inspection)
    first = inspection.findings[0]
    photo = first.photos[0]
    raw = sample.photo_bytes("roof", f"probe {mark or photo.filename}")
    cleaned = clean(raw, filename=photo.filename)
    photo.sha256 = cleaned.sha256
    db.save_photo(
        connection,
        finding_id=first.id,
        photo=photo,
        data=cleaned.data,
        thumbnail=cleaned.thumbnail,
        store=store,
    )
    return inspection


def _photo_count(connection, inspection) -> int:  # type: ignore[no-untyped-def]
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM photos p JOIN findings f ON f.id = p.finding_id "
            "WHERE f.inspection_id = %s",
            (inspection.id,),
        )
        row = cur.fetchone()
    return int(row["n"])


class TestPhotographsSurviveAnOrdinaryDay:
    def test_recording_another_finding_keeps_the_earlier_photograph(self, conn) -> None:  # type: ignore[no-untyped-def]
        inspection = _seeded(conn)
        assert _photo_count(conn, inspection) == 1

        inspection.findings.append(
            Finding(system_key="roof", severity_key="monitor", observation="ridge tiles seated")
        )
        db.save_inspection(conn, inspection)
        assert _photo_count(conn, inspection) == 1, "adding a finding destroyed a photograph"

    def test_saving_the_same_inspection_twice_keeps_it(self, conn) -> None:  # type: ignore[no-untyped-def]
        """Approving decisions and exporting both save on their way through."""
        inspection = _seeded(conn)
        db.save_inspection(conn, inspection)
        db.save_inspection(conn, inspection)
        assert _photo_count(conn, inspection) == 1

    def test_an_edited_finding_is_updated_not_replaced(self, conn) -> None:  # type: ignore[no-untyped-def]
        inspection = _seeded(conn)
        inspection.findings[0].plain_language = "Found a gap in the flashing at the chimney."
        db.save_inspection(conn, inspection)

        reloaded = db.load_inspection(conn, inspection.id)
        assert reloaded is not None
        assert reloaded.findings[0].plain_language.startswith("Found a gap")
        assert _photo_count(conn, inspection) == 1

    def test_a_removed_finding_really_goes(self, conn) -> None:  # type: ignore[no-untyped-def]
        """The upsert must not become a leak: deleting a finding still deletes it."""
        inspection = _seeded(conn)
        keep = inspection.findings[0]
        inspection.findings = [keep]
        db.save_inspection(conn, inspection, prune=True)

        reloaded = db.load_inspection(conn, inspection.id)
        assert reloaded is not None
        assert [f.id for f in reloaded.findings] == [keep.id]


class TestConcurrentWritesDoNotEraseEachOther:
    """Two requests arriving together must both survive.

    Recording a finding used to load the inspection, append in memory and write the set
    back, so the later writer erased the earlier one's finding — and its photographs with
    it. Six concurrent adds left two findings out of eight.
    """

    def test_concurrent_appends_all_land(self, conn) -> None:  # type: ignore[no-untyped-def]
        import threading

        inspection = _seeded(conn)
        before = len(inspection.findings)
        errors: list[BaseException] = []

        def add(n: int) -> None:
            try:
                # A connection per thread, as the server has a connection per request.
                with db.connect() as own:
                    db.insert_finding(
                        own,
                        inspection_id=inspection.id,
                        finding=Finding(
                            system_key="roof",
                            severity_key="monitor",
                            observation=f"concurrent {n}",
                        ),
                    )
            except BaseException as exc:  # pragma: no cover - reported, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        reloaded = db.load_inspection(conn, inspection.id)
        assert reloaded is not None
        assert len(reloaded.findings) == before + 6, "a concurrent write erased another"
        assert _photo_count(conn, inspection) == 1, "a concurrent write destroyed a photograph"

    def test_saving_the_inspection_does_not_prune_by_default(self, conn) -> None:  # type: ignore[no-untyped-def]
        """Exporting holds a snapshot; it must not delete what arrived after it was taken."""
        inspection = _seeded(conn)
        stale = db.load_inspection(conn, inspection.id)
        assert stale is not None

        db.insert_finding(
            conn,
            inspection_id=inspection.id,
            finding=Finding(system_key="roof", severity_key="monitor", observation="arrived later"),
        )
        # The stale snapshot is written back, as `decide` and `export` both do.
        db.save_inspection(conn, stale)

        reloaded = db.load_inspection(conn, inspection.id)
        assert reloaded is not None
        assert any(f.observation == "arrived later" for f in reloaded.findings)


class TestMigrations:
    """Ordered SQL files, applied once, and immutable afterwards.

    The schema used to be a single CREATE TABLE IF NOT EXISTS block run on every start,
    which works exactly once: a second release cannot add a column, because the table is
    already there and the statement does nothing.
    """

    def _dir(self, tmp_path):  # type: ignore[no-untyped-def]
        import shutil
        from pathlib import Path

        target = tmp_path / "migrations"
        target.mkdir()
        shutil.copy(Path("migrations/0001_initial.sql"), target / "0001_initial.sql")
        return target

    def test_a_second_release_can_add_a_column(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.store import migrate

        directory = self._dir(tmp_path)
        migrate.apply(conn, directory)
        (directory / "0002_probe.sql").write_text(
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS probe_column TEXT;"
        )
        try:
            assert migrate.apply(conn, directory) == ["0002_probe.sql"]
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 AS ok FROM information_schema.columns "
                    "WHERE table_name='inspections' AND column_name='probe_column'"
                )
                assert cur.fetchone() is not None
        finally:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE inspections DROP COLUMN IF EXISTS probe_column")
                cur.execute("DELETE FROM schema_migrations WHERE name = '0002_probe.sql'")
            conn.commit()

    def test_applying_twice_runs_nothing_the_second_time(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.store import migrate

        directory = self._dir(tmp_path)
        migrate.apply(conn, directory)
        assert migrate.apply(conn, directory) == []

    def test_editing_an_applied_migration_is_refused(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Two deployments must never disagree about what a migration contains."""
        from inspection_report.store import migrate

        directory = self._dir(tmp_path)
        migrate.apply(conn, directory)
        (directory / "0001_initial.sql").write_text("SELECT 1;")

        with pytest.raises(migrate.MigrationError) as exc:
            migrate.apply(conn, directory)
        assert "0001_initial.sql" in str(exc.value)
        assert "immutable" in str(exc.value)

    def test_a_missing_directory_says_what_to_do(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.store import migrate

        with pytest.raises(migrate.MigrationError) as exc:
            migrate.apply(conn, tmp_path / "nope")
        assert "MIGRATIONS_DIR" in str(exc.value)


class TestDeleting:
    """Removing things, and the blobs that go with them.

    A blob is keyed by its content hash, so two findings that photographed the same thing
    share one file. Deleting is therefore refcounted, not cascaded — cascading would take
    the other finding's evidence with it.
    """

    def _blob_count(self, tmp_path) -> int:  # type: ignore[no-untyped-def]
        return len([p for p in tmp_path.rglob("*") if p.is_file()])

    def test_deleting_a_photograph_reclaims_its_blob(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.store.blobs import FilesystemBlobStore

        store = FilesystemBlobStore(tmp_path)
        inspection = _seeded(conn, store=store, mark="test_deleting_a_photograph_reclaims_its_blob")
        assert self._blob_count(tmp_path) == 2  # the photograph and its thumbnail

        photo = inspection.findings[0].photos[0]  # type: ignore[attr-defined]
        assert db.delete_photo(conn, photo.id, store=store)
        assert self._blob_count(tmp_path) == 0

    def test_a_shared_blob_survives_deleting_one_of_its_rows(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The property that makes cascading wrong."""
        from inspection_report.domain.models import Photo
        from inspection_report.store.blobs import FilesystemBlobStore

        store = FilesystemBlobStore(tmp_path)
        inspection = _seeded(
            conn, store=store, mark="test_a_shared_blob_survives_deleting_one_of_its_rows"
        )
        original = inspection.findings[0].photos[0]  # type: ignore[attr-defined]
        raw = sample.photo_bytes(
            "roof", "probe test_a_shared_blob_survives_deleting_one_of_its_rows"
        )
        cleaned = clean(raw, filename=original.filename)

        # A second finding photographs the same thing: same bytes, same hash, same blob.
        twin = Photo(
            sha256=original.sha256,
            filename=original.filename,
            content_type=original.content_type,
            size_bytes=original.size_bytes,
            width=original.width,
            height=original.height,
        )
        db.save_photo(
            conn,
            finding_id=inspection.findings[1].id,  # type: ignore[attr-defined]
            photo=twin,
            data=cleaned.data,
            thumbnail=cleaned.thumbnail,
            store=store,
        )
        assert self._blob_count(tmp_path) == 2, "identical bytes must share one blob"

        db.delete_photo(conn, original.id, store=store)
        assert self._blob_count(tmp_path) == 2, "the other finding's evidence was destroyed"

        db.delete_photo(conn, twin.id, store=store)
        assert self._blob_count(tmp_path) == 0, "the last reference should reclaim it"

    def test_deleting_a_finding_takes_its_photographs(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.store.blobs import FilesystemBlobStore

        store = FilesystemBlobStore(tmp_path)
        inspection = _seeded(
            conn, store=store, mark="test_deleting_a_finding_takes_its_photographs"
        )
        first = inspection.findings[0]  # type: ignore[attr-defined]

        assert db.delete_finding(conn, first.id, store=store)
        reloaded = db.load_inspection(conn, inspection.id)  # type: ignore[attr-defined]
        assert reloaded is not None
        assert first.id not in [f.id for f in reloaded.findings]
        assert self._blob_count(tmp_path) == 0

    def test_deleting_an_inspection_takes_everything(self, conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from inspection_report.store.blobs import FilesystemBlobStore

        store = FilesystemBlobStore(tmp_path)
        inspection = _seeded(conn, store=store, mark="test_deleting_an_inspection_takes_everything")

        assert db.delete_inspection(conn, inspection.id, store=store)  # type: ignore[attr-defined]
        assert db.load_inspection(conn, inspection.id) is None  # type: ignore[attr-defined]
        assert self._blob_count(tmp_path) == 0

    def test_deleting_something_that_is_not_there_says_so(self, conn) -> None:  # type: ignore[no-untyped-def]
        from uuid import uuid4

        assert db.delete_inspection(conn, uuid4()) is False
        assert db.delete_finding(conn, uuid4()) is False
        assert db.delete_photo(conn, uuid4()) is False
