"""Seed the database with a fixed 5-document demo pile.

Loads 5 fixed microfinance documents from samples/demo_pile/ (2 loan
agreements from different lenders, 1 modification, 1 repayment statement,
and 1 collections field-visit note), stores the document bytes under
uploads/, inserts document rows, creates a pipeline run, and links
everything to a pile.

The pile carries deliberate compliance issues and cross-document
contradictions so the pipeline has real findings to surface, plus one
document (the collections note) that contains an embedded prompt-injection
attempt. The injection text is stored verbatim as ordinary document
content — it is data to be ingested and flagged, never an instruction the
seed or pipeline honors.

If a previously seeded demo pile exists but its stored files are missing
(e.g. seeded by an older version that wrote fake `local://` storage refs),
the broken demo data is purged and re-seeded.

Usage:
    python scripts/seed_demo.py

Requires:
    DATABASE_URL environment variable (defaults to local docker-compose value)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/docdb",
)

# Directory holding the fixed demo documents (resolved relative to the
# project root, not the current working directory, so `make seed` works
# regardless of where it is invoked from).
DEMO_PILE_DIR = Path(__file__).resolve().parent.parent / "samples" / "demo_pile"


@dataclass
class DemoDocument:
    """A single fixed demo document (mirrors the fields seed_demo consumes)."""

    filename: str
    document_type: str
    content: bytes


@dataclass
class DemoConflict:
    """One documented cross-document contradiction in the demo pile."""

    field_name: str
    expected_value: str
    contradicting_value: str
    repayment_filename: str


@dataclass
class DemoManifest:
    """Describes the embedded conflicts in the fixed demo pile."""

    conflicts: list[DemoConflict] = field(default_factory=list)


@dataclass
class DemoPile:
    """A fixed pile of demo documents plus its conflict manifest."""

    documents: list[DemoDocument] = field(default_factory=list)
    manifest: DemoManifest = field(default_factory=DemoManifest)


# Ordered list of the fixed demo documents: (filename, document_type).
# document_type uses the pipeline's registered types where applicable; the
# collections note has no registered extractor and routes to the LLM-only
# path, which is intentional demo coverage.
DEMO_DOCUMENTS: list[tuple[str, str]] = [
    ("doc1_loan_agreement.txt", "loan_agreement"),
    ("doc2_modification_agreement.txt", "modification_agreement"),
    ("doc3_repayment_statement.txt", "repayment_statement"),
    ("doc4_second_loan_agreement.txt", "loan_agreement"),
    ("doc5_collections_note.txt", "collections_note"),
]


def load_demo_pile() -> DemoPile:
    """Load the 5 fixed demo documents and build the conflict manifest.

    Reads each file's raw bytes from samples/demo_pile/. Fails loudly if any
    expected file is missing, so a broken checkout is caught before it
    reaches the database.
    """
    documents: list[DemoDocument] = []
    for filename, doc_type in DEMO_DOCUMENTS:
        path = DEMO_PILE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Fixed demo document not found: {path}. "
                "Expected 5 files under samples/demo_pile/."
            )
        documents.append(
            DemoDocument(
                filename=filename,
                document_type=doc_type,
                content=path.read_bytes(),
            )
        )

    # Documented cross-document contradictions the reviewer should expect the
    # pipeline to surface. These describe what is factually inconsistent
    # between the fixed documents; they are printed by the seed as a preview
    # of ground truth, not used to short-circuit any evaluation.
    conflicts = [
        DemoConflict(
            field_name="interest_rate_applied_from_instalment_7",
            expected_value="22.50% (per modification MOD-01)",
            contradicting_value="26.00% (used to compute instalment 7 in repayment)",
            repayment_filename="doc3_repayment_statement.txt",
        ),
        DemoConflict(
            field_name="penal_charge_cap",
            expected_value="<= 5% of overdue instalment (loan agreement Clause 6.2)",
            contradicting_value="6.2% penal charge levied on instalment 7",
            repayment_filename="doc3_repayment_statement.txt",
        ),
    ]

    return DemoPile(documents=documents, manifest=DemoManifest(conflicts=conflicts))

# Same convention as src/pipeline/upload_api.py — relative "uploads/" resolves
# both on the host (project root) and inside the API container
# (./uploads is volume-mounted at /app/uploads).
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))

DEMO_SEED = 42  # Stable marker identifying demo-owned rows for idempotent re-seeding


def seed_demo() -> dict:
    """Seed the fixed demo pile in-process and return a structured result.

    This is the importable core used by both the CLI (`main()`) and the
    backend `/demo/seed` endpoint. It performs no shell execution and takes
    no caller-supplied input — it only reads the fixed files under
    samples/demo_pile/ and writes to the configured DATABASE_URL.

    Returns a dict describing the outcome:
        {"status": "seeded", "pile_id", "run_id", "document_count", "conflicts": [...]}
        {"status": "skipped", "reason": "already_seeded", "document_count"}

    Raises:
        Exception: on any database or file error (the caller decides how to
        surface it). The transaction is rolled back before the raise.
    """
    print("=== Seeding demo pile ===")
    print(f"Database: {DATABASE_URL.split('@')[-1]}")  # Print host only, not creds

    # Load the fixed 5-document demo pile from samples/demo_pile/
    pile = load_demo_pile()

    print(f"Loaded {len(pile.documents)} fixed documents with {len(pile.manifest.conflicts)} documented conflicts")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # Check if demo data already exists (idempotent, self-healing)
            cur.execute(
                """
                SELECT dv.storage_ref
                FROM documents d
                JOIN document_versions dv ON dv.document_id = d.id
                WHERE d.metadata->>'demo_seed' = %s
                """,
                (str(DEMO_SEED),),
            )
            existing_refs = [row[0] for row in cur.fetchall()]
            if existing_refs:
                # Also check if the demo pile still exists and is active
                cur.execute(
                    """
                    SELECT id
                    FROM piles
                    WHERE metadata->>'demo_seed' = %s AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (str(DEMO_SEED),),
                )
                active_pile_row = cur.fetchone()
                if active_pile_row and all(Path(ref).exists() for ref in existing_refs):
                    active_pile_id = str(active_pile_row[0])
                    cur.execute(
                        """
                        SELECT id
                        FROM runs
                        WHERE pile_id = %s
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        (active_pile_id,),
                    )
                    active_run_row = cur.fetchone()
                    print(f"Demo pile already seeded ({len(existing_refs)} documents found). Skipping.")
                    return {
                        "status": "skipped",
                        "reason": "already_seeded",
                        "pile_id": active_pile_id,
                        "run_id": str(active_run_row[0]) if active_run_row else None,
                        "document_count": len(existing_refs),
                    }
                print(
                    "Demo pile missing or archived. Purging stale demo data and re-seeding."
                )
                _purge_demo_data(cur)

            run_id = str(uuid.uuid4())
            pile_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

            # Create the demo pile
            cur.execute(
                """
                INSERT INTO piles (id, name, status, created_at, updated_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    pile_id,
                    "Demo Microfinance",
                    "active",
                    now,
                    now,
                    json.dumps({"demo_seed": str(DEMO_SEED)}),
                ),
            )

            # Insert documents and versions
            document_ids: list[str] = []
            for doc in pile.documents:
                doc_id = str(uuid.uuid4())
                version_id = str(uuid.uuid4())
                content_hash = hashlib.sha256(doc.content).hexdigest()

                # Store the bytes on disk like the upload API does, and
                # reference the real path. The synthetic generator emits
                # plain-text content for every document (the "pdf" format
                # is only a filename cosmetic), so the honest MIME type is
                # text/plain — registering text bytes as application/pdf
                # would crash PDF extraction.
                ext = Path(doc.filename).suffix or ".txt"
                storage_path = UPLOAD_DIR / f"{doc_id}{ext}"
                storage_path.write_bytes(doc.content)

                cur.execute(
                    """
                    INSERT INTO documents (id, filename, mime_type, ingested_at, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        doc_id,
                        doc.filename,
                        "text/plain",
                        now,
                        json.dumps(
                            {"document_type": doc.document_type, "demo_seed": str(DEMO_SEED)}
                        ),
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO document_versions (id, document_id, version_number, content_hash, storage_ref, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (version_id, doc_id, 1, content_hash, str(storage_path), now),
                )

                document_ids.append(doc_id)
                print(f"  + {doc.filename} ({doc.document_type}, stored at {storage_path})")

                # Link document to pile
                cur.execute(
                    """
                    INSERT INTO pile_documents (pile_id, document_id, added_at)
                    VALUES (%s, %s, %s)
                    """,
                    (pile_id, doc_id, now),
                )

            # Create a pipeline run
            cur.execute(
                """
                INSERT INTO runs (id, status, config_snapshot, started_at, initiator, version, pile_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    "pending",
                    json.dumps({"playbook_id": "microfinance_v1", "pile_document_ids": document_ids}),
                    now,
                    "seed_demo",
                    1,
                    pile_id,
                ),
            )

            # Note: source_locations require claim_id (FK to claims table),
            # so ground-truth provenance is populated when the pipeline runs extraction.

        conn.commit()
        print(f"\nDone. Run ID: {run_id}")
        print(f"Documents: {len(document_ids)}")
        print(f"Conflicts embedded: {len(pile.manifest.conflicts)}")
        for c in pile.manifest.conflicts:
            print(f"  - {c.field_name}: expected {c.expected_value}, "
                  f"got {c.contradicting_value} ({c.repayment_filename})")

        return {
            "status": "seeded",
            "pile_id": pile_id,
            "run_id": run_id,
            "document_count": len(document_ids),
            "conflicts": [
                {
                    "field_name": c.field_name,
                    "expected_value": c.expected_value,
                    "contradicting_value": c.contradicting_value,
                    "repayment_filename": c.repayment_filename,
                }
                for c in pile.manifest.conflicts
            ],
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    """CLI entry point: run the seed and preserve exit-code semantics."""
    try:
        seed_demo()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _purge_demo_data(cur) -> None:
    """Delete every row belonging to demo piles, respecting RESTRICT FKs.

    Deletion order mirrors src/pipeline/run_cleanup.py, extended with the
    pile/document chain: decisions → approval_queue → source_locations →
    claims → run_steps → runs → pile_documents → document_versions →
    documents → piles. deliverables cascade with their run.
    """
    cur.execute(
        "SELECT id FROM piles WHERE metadata->>'demo_seed' = %s",
        (str(DEMO_SEED),),
    )
    pile_ids = [row[0] for row in cur.fetchall()]
    if not pile_ids:
        return

    cur.execute(
        """
        SELECT d.id FROM documents d
        JOIN pile_documents pd ON pd.document_id = d.id
        WHERE pd.pile_id = ANY(%s::uuid[])
        """,
        (pile_ids,),
    )
    doc_ids = [row[0] for row in cur.fetchall()]

    cur.execute(
        """
        SELECT dv.id FROM document_versions dv
        WHERE dv.document_id = ANY(%s::uuid[])
        """,
        (doc_ids,),
    )
    version_ids = [row[0] for row in cur.fetchall()]

    cur.execute(
        "SELECT id FROM runs WHERE pile_id = ANY(%s::uuid[])",
        (pile_ids,),
    )
    run_ids = [row[0] for row in cur.fetchall()]

    # Empty-list guards: Postgres cannot infer the type of an empty array
    # literal, so each scope is only deleted when it has members.
    if run_ids:
        # 1. Decisions on the demo runs' approval-queue entries
        cur.execute(
            """
            DELETE FROM decisions
            WHERE approval_queue_id IN (
                SELECT id FROM approval_queue WHERE run_id = ANY(%s::uuid[])
            )
            """,
            (run_ids,),
        )
        # 2. The demo runs' approval-queue entries
        cur.execute("DELETE FROM approval_queue WHERE run_id = ANY(%s::uuid[])", (run_ids,))
        # 3. Source locations of claims from demo runs or on demo versions
        cur.execute(
            """
            DELETE FROM source_locations
            WHERE claim_id IN (
                SELECT id FROM claims
                WHERE run_id = ANY(%s::uuid[]) OR document_version_id = ANY(%s::uuid[])
            )
            """,
            (run_ids, version_ids),
        )
        # 4. The claims themselves
        cur.execute(
            "DELETE FROM claims WHERE run_id = ANY(%s::uuid[]) OR document_version_id = ANY(%s::uuid[])",
            (run_ids, version_ids),
        )
        # 5. Run steps, then runs (deliverables cascade with runs)
        cur.execute("DELETE FROM run_steps WHERE run_id = ANY(%s::uuid[])", (run_ids,))
    if version_ids:
        # Claims may exist on demo versions from runs outside the demo piles
        cur.execute(
            """
            DELETE FROM source_locations
            WHERE claim_id IN (
                SELECT id FROM claims WHERE document_version_id = ANY(%s::uuid[])
            )
            """,
            (version_ids,),
        )
        cur.execute("DELETE FROM claims WHERE document_version_id = ANY(%s::uuid[])", (version_ids,))
    cur.execute("DELETE FROM runs WHERE pile_id = ANY(%s::uuid[])", (pile_ids,))
    # 6. Pile links, versions, documents, piles
    cur.execute("DELETE FROM pile_documents WHERE pile_id = ANY(%s::uuid[])", (pile_ids,))
    if doc_ids:
        cur.execute("DELETE FROM document_versions WHERE document_id = ANY(%s::uuid[])", (doc_ids,))
        cur.execute("DELETE FROM documents WHERE id = ANY(%s::uuid[])", (doc_ids,))
    cur.execute("DELETE FROM piles WHERE id = ANY(%s::uuid[])", (pile_ids,))

    print(
        f"Purged {len(pile_ids)} pile(s), {len(doc_ids)} document(s), "
        f"{len(run_ids)} run(s) of broken demo data."
    )


if __name__ == "__main__":
    main()
