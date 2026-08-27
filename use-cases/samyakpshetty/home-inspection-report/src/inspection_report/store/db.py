"""Postgres: the record of truth for an inspection in progress.

An inspection is walked over hours, on a phone, in an attic and a crawlspace, and the report
is assembled afterwards. So the state that matters — the findings, the severities, the photo
hashes and the decisions taken at the gate — lives in a database rather than in a process.

Two things this buys that memory does not:

* **A walk survives a restart.** Close the tab, drop the connection, redeploy the service, and
  the inspection is where it was.
* **Photograph uploads stay idempotent across runs.** A photo's identity is the hash of its
  cleaned bytes, so the URL it was given is remembered and never bought twice.

The schema is applied on connect and is safe to re-run.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from inspection_report.domain.models import Finding, Inspection, Inspector, Photo, Property
from inspection_report.logging import get_logger
from inspection_report.store import blobs
from inspection_report.store.blobs import BlobStore

_log = get_logger("inspection_report.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspections (
    id             UUID PRIMARY KEY,
    address_line   TEXT        NOT NULL,
    city           TEXT        NOT NULL,
    postcode       TEXT        NOT NULL DEFAULT '',
    year_built     INTEGER,
    property_type  TEXT        NOT NULL DEFAULT '',
    inspector_name TEXT        NOT NULL,
    licence_number TEXT        NOT NULL DEFAULT '',
    firm_name      TEXT        NOT NULL DEFAULT '',
    inspected_on   DATE        NOT NULL,
    template_key   TEXT        NOT NULL DEFAULT 'buyer_summary',
    stage          TEXT        NOT NULL DEFAULT 'draft',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
    id             UUID PRIMARY KEY,
    inspection_id  UUID        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    system_key     TEXT        NOT NULL,
    severity_key   TEXT        NOT NULL,
    location       TEXT        NOT NULL DEFAULT '',
    observation    TEXT        NOT NULL,
    recommendation TEXT        NOT NULL DEFAULT '',
    plain_language TEXT        NOT NULL DEFAULT '',
    position       INTEGER     NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS findings_by_inspection ON findings (inspection_id, position);

CREATE TABLE IF NOT EXISTS photos (
    id            UUID PRIMARY KEY,
    finding_id    UUID        NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    sha256        TEXT        NOT NULL,
    filename      TEXT        NOT NULL,
    content_type  TEXT        NOT NULL,
    size_bytes    INTEGER     NOT NULL,
    width         INTEGER     NOT NULL DEFAULT 0,
    height        INTEGER     NOT NULL DEFAULT 0,
    caption       TEXT        NOT NULL DEFAULT '',
    position      INTEGER     NOT NULL DEFAULT 0,
    bytes         BYTEA       NOT NULL,
    thumbnail     BYTEA,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS photos_by_finding ON photos (finding_id, position);

-- The upload cache. Keyed by content, because that is what a photograph's identity is:
-- the same bytes are the same photograph however many findings or runs reference them, and
-- an upload that has been paid for once is never paid for again.
CREATE TABLE IF NOT EXISTS photo_uploads (
    sha256     TEXT PRIMARY KEY,
    remote_url TEXT        NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every proposal the AI made and what was decided about it, including the rail's verdict.
-- Kept because "why does the report say this" must be answerable after the fact.
CREATE TABLE IF NOT EXISTS proposals (
    id            UUID PRIMARY KEY,
    inspection_id UUID        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    finding_id    UUID        REFERENCES findings(id) ON DELETE SET NULL,
    job_id        TEXT        NOT NULL DEFAULT '',
    change_id     TEXT        NOT NULL DEFAULT '',
    old_text      TEXT        NOT NULL DEFAULT '',
    new_text      TEXT        NOT NULL DEFAULT '',
    rail_clean    BOOLEAN     NOT NULL DEFAULT TRUE,
    rail_breaches JSONB       NOT NULL DEFAULT '[]'::jsonb,
    decision      TEXT        NOT NULL DEFAULT 'pending',
    decided_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS proposals_by_inspection ON proposals (inspection_id);
"""


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://inspect:inspect@db:5432/inspect")


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(url or database_url(), row_factory=dict_row) as conn:
        yield conn


def apply_schema(conn: psycopg.Connection[dict[str, Any]]) -> None:
    """Bring the schema up to date. Idempotent, and safe when two processes start together.

    Delegates to the migration runner. ``SCHEMA`` below is kept as the readable description
    of the current shape — it is what ``migrations/0001_initial.sql`` contains — but it is no
    longer what creates anything, because a `CREATE TABLE IF NOT EXISTS` block cannot add a
    column to a database that already has the table.
    """
    from inspection_report.store import migrate

    migrate.apply(conn)


# ------------------------------------------------------------------ writes


def insert_finding(
    conn: psycopg.Connection[dict[str, Any]], *, inspection_id: UUID, finding: Finding
) -> None:
    """Append one finding, touching nothing else.

    Recording a finding used to load the whole inspection, append in memory, and write the
    set back. Two requests arriving together each wrote their own stale snapshot and the
    later one erased the earlier one's finding — and, through the photo cascade, its
    photographs. Six concurrent adds left two findings and one photograph out of eight.
    An append is one row; it is written as one row.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(max(position), -1) + 1 AS next FROM findings WHERE inspection_id = %s",
            (inspection_id,),
        )
        row = cur.fetchone()
        cur.execute(
            """
            INSERT INTO findings (id, inspection_id, system_key, severity_key, location,
                observation, recommendation, plain_language, position)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                finding.id,
                inspection_id,
                finding.system_key,
                finding.severity_key,
                finding.location,
                finding.observation,
                finding.recommendation,
                finding.plain_language,
                int(row["next"]) if row else 0,
            ),
        )
    conn.commit()


def save_inspection(
    conn: psycopg.Connection[dict[str, Any]], inspection: Inspection, *, prune: bool = False
) -> None:
    """Upsert an inspection and its findings, in one transaction.

    Findings are **upserted**. Removing one requires ``prune=True``, from a caller that owns
    the whole set. That
    distinction is the whole point: ``photos.finding_id`` is ``ON DELETE CASCADE``, so
    clearing the findings and re-inserting them — which is what this used to do — destroyed
    every photograph on the inspection. Re-inserting a finding with the same id does not
    bring its photographs back.

    It fired on the ordinary path: attach a photograph to a finding, record the next
    finding, and the first photograph was gone. Approving decisions and exporting did the
    same thing, because both save the inspection on their way through.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO inspections (id, address_line, city, postcode, year_built,
                property_type, inspector_name, licence_number, firm_name, inspected_on,
                template_key, stage)
            VALUES (%(id)s, %(address_line)s, %(city)s, %(postcode)s, %(year_built)s,
                %(property_type)s, %(inspector_name)s, %(licence_number)s, %(firm_name)s,
                %(inspected_on)s, %(template_key)s, %(stage)s)
            ON CONFLICT (id) DO UPDATE SET
                address_line = EXCLUDED.address_line, city = EXCLUDED.city,
                postcode = EXCLUDED.postcode, year_built = EXCLUDED.year_built,
                property_type = EXCLUDED.property_type,
                inspector_name = EXCLUDED.inspector_name,
                licence_number = EXCLUDED.licence_number, firm_name = EXCLUDED.firm_name,
                inspected_on = EXCLUDED.inspected_on, template_key = EXCLUDED.template_key,
                stage = EXCLUDED.stage, updated_at = now()
            """,
            {
                "id": inspection.id,
                "address_line": inspection.property.address_line,
                "city": inspection.property.city,
                "postcode": inspection.property.postcode,
                "year_built": inspection.property.year_built,
                "property_type": inspection.property.property_type,
                "inspector_name": inspection.inspector.name,
                "licence_number": inspection.inspector.licence_number,
                "firm_name": inspection.inspector.firm_name,
                "inspected_on": inspection.inspected_on,
                "template_key": inspection.template_key,
                "stage": str(inspection.stage),
            },
        )
        # Only a caller that genuinely owns the whole set may prune, and it has to say so.
        # Everything else — approving decisions, exporting, moving the stage on — holds a
        # snapshot that another request may already have added to, and deleting from that
        # snapshot is how one request erases another's work.
        if prune:
            cur.execute(
                "DELETE FROM findings WHERE inspection_id = %s AND NOT (id = ANY(%s))",
                (inspection.id, [f.id for f in inspection.findings]),
            )
        for position, finding in enumerate(inspection.findings):
            cur.execute(
                """
                INSERT INTO findings (id, inspection_id, system_key, severity_key, location,
                    observation, recommendation, plain_language, position)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    system_key = EXCLUDED.system_key,
                    severity_key = EXCLUDED.severity_key,
                    location = EXCLUDED.location,
                    observation = EXCLUDED.observation,
                    recommendation = EXCLUDED.recommendation,
                    plain_language = EXCLUDED.plain_language,
                    position = EXCLUDED.position
                """,
                (
                    finding.id,
                    inspection.id,
                    finding.system_key,
                    finding.severity_key,
                    finding.location,
                    finding.observation,
                    finding.recommendation,
                    finding.plain_language,
                    position,
                ),
            )
    conn.commit()


def save_photo(
    conn: psycopg.Connection[dict[str, Any]],
    *,
    finding_id: UUID,
    photo: Photo,
    data: bytes,
    thumbnail: bytes | None,
    position: int = 0,
    store: BlobStore | None = None,
) -> None:
    """Keep one photograph: the bytes in the blob store, a key and its metadata in the row.

    The blob is written **before** the row, so a crash between the two leaves an unreferenced
    file rather than a row pointing at bytes that were never stored. Keys are content hashes,
    so re-writing after a crash overwrites an identical file.
    """
    store = store or blobs.default_store()
    key = photo.sha256
    thumb_key = blobs.thumbnail_key(photo.sha256) if thumbnail else None

    store.put(key, data)
    if thumbnail is not None and thumb_key is not None:
        store.put(thumb_key, thumbnail)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO photos (id, finding_id, sha256, filename, content_type, size_bytes,
                width, height, caption, position, storage_key, thumbnail_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET caption = EXCLUDED.caption,
                position = EXCLUDED.position,
                storage_key = EXCLUDED.storage_key,
                thumbnail_key = EXCLUDED.thumbnail_key
            """,
            (
                photo.id,
                finding_id,
                photo.sha256,
                photo.filename,
                photo.content_type,
                photo.size_bytes,
                photo.width,
                photo.height,
                photo.caption,
                position,
                key,
                thumb_key,
            ),
        )
    conn.commit()


# The three ways a photograph can be reached, as whole statements rather than a clause
# pasted into an f-string. Nothing user-supplied ever reached that f-string, but a query
# assembled by concatenation is a pattern worth not having in a file that handles deletes.
_KEYS_BY_PHOTO = "SELECT storage_key, thumbnail_key FROM photos WHERE id = %s"
_KEYS_BY_FINDING = "SELECT storage_key, thumbnail_key FROM photos WHERE finding_id = %s"
_KEYS_BY_INSPECTION = (
    "SELECT storage_key, thumbnail_key FROM photos "
    "WHERE finding_id IN (SELECT id FROM findings WHERE inspection_id = %s)"
)


def _keys_for(conn: psycopg.Connection[dict[str, Any]], query: str, param: Any) -> set[str]:
    """Every blob key reachable from one row, before that row is deleted."""
    with conn.cursor() as cur:
        cur.execute(query, (param,))
        keys: set[str] = set()
        for row in cur.fetchall():
            keys.update(k for k in (row["storage_key"], row["thumbnail_key"]) if k)
    return keys


def forget_orphan_blobs(
    conn: psycopg.Connection[dict[str, Any]],
    keys: set[str],
    *,
    store: BlobStore | None = None,
) -> int:
    """Delete blobs nothing points at any more. Returns how many.

    Refcounted rather than cascaded, because a key is a content hash: two findings that
    photographed the same thing share one blob, and deleting one finding must not take the
    other's evidence with it. Called after the rows are gone, so the database is the
    authority on what is still referenced.
    """
    if not keys:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT storage_key AS k FROM photos WHERE storage_key = ANY(%s) "
            "UNION SELECT DISTINCT thumbnail_key FROM photos WHERE thumbnail_key = ANY(%s)",
            (list(keys), list(keys)),
        )
        still_used = {row["k"] for row in cur.fetchall() if row["k"]}

    blob_store = store or blobs.default_store()
    orphans = keys - still_used
    for key in orphans:
        blob_store.delete(key)
    if orphans:
        _log.info("blobs_reclaimed", extra={"count": len(orphans)})
    return len(orphans)


def delete_photo(
    conn: psycopg.Connection[dict[str, Any]], photo_id: UUID, *, store: BlobStore | None = None
) -> bool:
    """Remove one photograph. Returns whether there was one."""
    keys = _keys_for(conn, _KEYS_BY_PHOTO, photo_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM photos WHERE id = %s RETURNING id", (photo_id,))
        gone = cur.fetchone() is not None
    conn.commit()
    if gone:
        forget_orphan_blobs(conn, keys, store=store)
    return gone


def delete_finding(
    conn: psycopg.Connection[dict[str, Any]], finding_id: UUID, *, store: BlobStore | None = None
) -> bool:
    """Remove one finding and the photographs attached to it."""
    keys = _keys_for(conn, _KEYS_BY_FINDING, finding_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM findings WHERE id = %s RETURNING id", (finding_id,))
        gone = cur.fetchone() is not None
    conn.commit()
    if gone:
        forget_orphan_blobs(conn, keys, store=store)
    return gone


def delete_inspection(
    conn: psycopg.Connection[dict[str, Any]],
    inspection_id: UUID,
    *,
    store: BlobStore | None = None,
) -> bool:
    """Remove an inspection and everything under it.

    Findings, photographs, proposals and jobs go by cascade; the blobs are reclaimed here
    because the filesystem is not part of the transaction.
    """
    keys = _keys_for(conn, _KEYS_BY_INSPECTION, inspection_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM inspections WHERE id = %s RETURNING id", (inspection_id,))
        gone = cur.fetchone() is not None
    conn.commit()
    if gone:
        forget_orphan_blobs(conn, keys, store=store)
        _log.info("inspection_deleted", extra={"inspection": str(inspection_id)})
    return gone


def remember_upload(
    conn: psycopg.Connection[dict[str, Any]], *, sha256: str, remote_url: str
) -> None:
    """Record that these bytes have already been uploaded, and to where."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO photo_uploads (sha256, remote_url) VALUES (%s, %s)
            ON CONFLICT (sha256) DO NOTHING
            """,
            (sha256, remote_url),
        )
    conn.commit()


def known_uploads(conn: psycopg.Connection[dict[str, Any]]) -> dict[str, str]:
    """Every photograph already uploaded, by content hash. Feeds upload idempotency."""
    with conn.cursor() as cur:
        cur.execute("SELECT sha256, remote_url FROM photo_uploads")
        return {r["sha256"]: r["remote_url"] for r in cur.fetchall()}


# Stable namespace for deriving a proposal's primary key from (inspection, change_id).
_PROPOSAL_NS = UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def record_proposals(
    conn: psycopg.Connection[dict[str, Any]],
    *,
    inspection_id: UUID,
    rows: list[dict[str, Any]],
) -> None:
    """Keep every proposal and the rail's verdict on it, decided or not.

    A proposal is identified by its ``change_id`` within an inspection, so the primary key is
    derived from that pair rather than minted fresh. It used to be a new ``uuid4()`` on every
    call, which meant the ``ON CONFLICT`` below never fired: recording the same round twice —
    once when the proposals arrive, once when they are decided — inserted a second set instead
    of updating the first, and left the audit trail holding a stale `pending` copy of every
    decided change. "Why does the report say this" has to have one answer.
    """
    with conn.cursor() as cur:
        for row in rows:
            row = {
                **row,
                "id": uuid5(_PROPOSAL_NS, f"{inspection_id}:{row['change_id']}"),
            }
            cur.execute(
                """
                INSERT INTO proposals (id, inspection_id, finding_id, job_id, change_id,
                    old_text, new_text, rail_clean, rail_breaches, decision, decided_at)
                VALUES (%(id)s, %(inspection_id)s, %(finding_id)s, %(job_id)s, %(change_id)s,
                    %(old_text)s, %(new_text)s, %(rail_clean)s, %(rail_breaches)s,
                    %(decision)s, %(decided_at)s)
                ON CONFLICT (id) DO UPDATE SET decision = EXCLUDED.decision,
                    decided_at = EXCLUDED.decided_at
                """,
                {
                    **row,
                    "inspection_id": inspection_id,
                    "rail_breaches": json.dumps(row.get("rail_breaches", [])),
                },
            )
    conn.commit()


# ------------------------------------------------------------------- reads


def load_inspection(
    conn: psycopg.Connection[dict[str, Any]], inspection_id: UUID
) -> Inspection | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM inspections WHERE id = %s", (inspection_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "SELECT * FROM findings WHERE inspection_id = %s ORDER BY position",
            (inspection_id,),
        )
        finding_rows = cur.fetchall()
        finding_ids = [r["id"] for r in finding_rows]
        photos_by_finding: dict[UUID, list[Photo]] = {fid: [] for fid in finding_ids}
        if finding_ids:
            cur.execute(
                "SELECT * FROM photos WHERE finding_id = ANY(%s) ORDER BY position",
                (finding_ids,),
            )
            for p in cur.fetchall():
                photos_by_finding[p["finding_id"]].append(
                    Photo(
                        id=p["id"],
                        sha256=p["sha256"],
                        filename=p["filename"],
                        content_type=p["content_type"],
                        size_bytes=p["size_bytes"],
                        width=p["width"],
                        height=p["height"],
                        caption=p["caption"],
                    )
                )

    uploads = known_uploads(conn)
    findings = []
    for r in finding_rows:
        photos = photos_by_finding.get(r["id"], [])
        for photo in photos:
            photo.remote_url = uploads.get(photo.sha256, "")
        findings.append(
            Finding(
                id=r["id"],
                system_key=r["system_key"],
                severity_key=r["severity_key"],
                location=r["location"],
                observation=r["observation"],
                recommendation=r["recommendation"],
                plain_language=r["plain_language"],
                photos=photos,
            )
        )

    return Inspection(
        id=row["id"],
        property=Property(
            address_line=row["address_line"],
            city=row["city"],
            postcode=row["postcode"],
            year_built=row["year_built"],
            property_type=row["property_type"],
        ),
        inspector=Inspector(
            name=row["inspector_name"],
            licence_number=row["licence_number"],
            firm_name=row["firm_name"],
        ),
        inspected_on=row["inspected_on"],
        template_key=row["template_key"],
        stage=row["stage"],
        findings=findings,
    )


def list_inspections(conn: psycopg.Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    """The inspections list, with enough for a card without loading every photograph."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.address_line, i.city, i.postcode, i.inspector_name, i.firm_name,
                   i.inspected_on, i.stage, i.template_key, i.updated_at,
                   COUNT(f.id) AS finding_count
            FROM inspections i
            LEFT JOIN findings f ON f.inspection_id = i.id
            GROUP BY i.id
            ORDER BY i.updated_at DESC
            """
        )
        return list(cur.fetchall())


def photo_bytes(
    conn: psycopg.Connection[dict[str, Any]],
    photo_id: UUID,
    *,
    thumbnail: bool = False,
    store: BlobStore | None = None,
) -> tuple[bytes, str] | None:
    """One photograph's bytes, from the blob store — or from the row if it predates it.

    The fallback is what makes 0002 a migration rather than a data loss: a row written before
    the blob store still carries its bytes and still serves. It goes when a deployment has
    backfilled and a later migration drops the columns.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT storage_key, thumbnail_key, bytes, thumbnail, content_type "
            "FROM photos WHERE id = %s",
            (photo_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None

    mime = "image/jpeg" if thumbnail else row["content_type"]
    key = row["thumbnail_key"] if thumbnail else row["storage_key"]
    if key:
        data = (store or blobs.default_store()).get(key)
        if data is not None:
            return data, mime
        # A key that points at nothing is worth a line: the row and the store disagree.
        _log.error("blob_missing", extra={"photo": str(photo_id), "key": key[:12]})

    legacy = row["thumbnail"] if thumbnail else row["bytes"]
    if legacy is None:
        return None
    return bytes(legacy), mime


def photo_bytes_by_url(
    conn: psycopg.Connection[dict[str, Any]], url: str, *, store: BlobStore | None = None
) -> bytes | None:
    """The bytes behind a SuperDocs image URL, from our own record.

    The offline exporter needs image bytes to draw them, and it used to ask the fake, which
    only remembers what it uploaded in the life of one process. Two things then combine
    badly: uploads are cached by content hash so a photograph is never sent twice, and the
    API restarts. After that the exporter could not resolve a photograph it had every right
    to expect, dropped it, and left its caption sitting under nothing — a report delivered
    without its evidence.

    The database always has the bytes, so it is the honest place to ask.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.storage_key, p.bytes FROM photos p "
            "JOIN photo_uploads u ON u.sha256 = p.sha256 "
            "WHERE u.remote_url = %s LIMIT 1",
            (url,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    if row["storage_key"]:
        data = (store or blobs.default_store()).get(row["storage_key"])
        if data is not None:
            return data
    return bytes(row["bytes"]) if row["bytes"] is not None else None


def photo_data_for(
    conn: psycopg.Connection[dict[str, Any]],
    inspection_id: UUID,
    *,
    store: BlobStore | None = None,
) -> dict[str, bytes]:
    """Every photograph's cleaned bytes for one inspection, keyed by filename.

    Keyed by filename because that is what the render pipeline asks for; identity for
    upload purposes is still the content hash.
    """
    blob_store = store or blobs.default_store()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.filename, p.storage_key, p.bytes FROM photos p
            JOIN findings f ON f.id = p.finding_id
            WHERE f.inspection_id = %s
            """,
            (inspection_id,),
        )
        rows = cur.fetchall()

    out: dict[str, bytes] = {}
    for row in rows:
        data = blob_store.get(row["storage_key"]) if row["storage_key"] else None
        if data is None and row["bytes"] is not None:
            data = bytes(row["bytes"])  # written before the blob store; still serves
        if data is None:
            _log.error("blob_missing", extra={"photo_filename": row["filename"]})
            continue
        out[row["filename"]] = data
    return out


def load_proposals(
    conn: psycopg.Connection[dict[str, Any]], inspection_id: UUID
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM proposals WHERE inspection_id = %s ORDER BY created_at",
            (inspection_id,),
        )
        return list(cur.fetchall())


def clear_proposals(conn: psycopg.Connection[dict[str, Any]], inspection_id: UUID) -> None:
    """A fresh proposal round replaces the last one; stale cards must not linger at a gate."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM proposals WHERE inspection_id = %s", (inspection_id,))
    conn.commit()


def load_skeleton(
    conn: psycopg.Connection[dict[str, Any]], content_sha: str, provider: str
) -> str | None:
    """The skeleton this provider returned for these exact format bytes, if we hold it.

    Keyed by provider as well as by hash: the hash describes the .docx we registered, not the
    document that came back, so without it a skeleton the offline fake produced would be
    served to a live run — which is precisely the claim the round trip exists to support.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT html FROM template_skeletons WHERE content_sha = %s AND provider = %s",
            (content_sha, provider),
        )
        row = cur.fetchone()
        return str(row["html"]) if row else None


def save_skeleton(
    conn: psycopg.Connection[dict[str, Any]],
    *,
    content_sha: str,
    provider: str,
    format_key: str,
    template_name: str,
    html: str,
) -> None:
    """Remember it, so a format costs one operation per version rather than one per report.

    ``DO NOTHING`` rather than an update: two workers can materialise the same format at the
    same moment, and the row they would write is the same document either way.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO template_skeletons "
            "(content_sha, provider, format_key, template_name, html) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (content_sha, provider) DO NOTHING",
            (content_sha, provider, format_key, template_name, html),
        )
    conn.commit()
