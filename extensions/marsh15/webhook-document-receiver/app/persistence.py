import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.security import VerifiedWebhook
from app.superdocs import PendingChange


class DeliveryCollisionError(RuntimeError):
    """A delivery ID was reused with different authenticated bytes."""


class LeaseLostError(RuntimeError):
    """A stale worker attempted to mutate a job after losing its lease."""


@dataclass(frozen=True)
class AcceptedDelivery:
    delivery_id: UUID
    job_id: UUID
    status: str
    duplicate: bool


@dataclass(frozen=True)
class ClaimedJob:
    job_id: UUID
    delivery_id: UUID
    external_delivery_id: str
    input_data: dict[str, object]
    attempt_count: int
    superdocs_session_id: str | None
    superdocs_job_id: str | None
    external_wait_kind: str | None
    retry_count: int
    external_effect_started_at: datetime | None
    recovered: bool
    leased_by: str
    route_config: dict[str, object]


@dataclass(frozen=True)
class ReviewDecision:
    change_id: str
    approved: bool
    reason: str | None = None


class DeliveryStore:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    @staticmethod
    def _assert_lease(connection, job: ClaimedJob) -> None:
        owned = connection.execute(
            """
            SELECT 1 FROM jobs
            WHERE id = %s AND state = 'processing' AND leased_by = %s
              AND lease_until > now()
            FOR UPDATE
            """,
            (job.job_id, job.leased_by),
        ).fetchone()
        if owned is None:
            raise LeaseLostError("Worker lease is no longer valid")

    def accept(
        self,
        *,
        verified: VerifiedWebhook,
        event_type: str,
        route_id: str,
        route_config_version: str,
        input_data: Mapping[str, object],
        route_config: Mapping[str, object] | None = None,
        sanitized_metadata: Mapping[str, object] | None = None,
    ) -> AcceptedDelivery:
        collision = False
        with self.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO deliveries (
                    provider, external_delivery_id, event_type, payload_sha256,
                    sanitized_metadata, route_id, route_config_version, state
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    verified.provider,
                    verified.event_id,
                    event_type,
                    verified.payload_sha256,
                    Jsonb(dict(sanitized_metadata or {})),
                    route_id,
                    route_config_version,
                ),
            ).fetchone()

            if inserted is not None:
                job = connection.execute(
                    """
                    INSERT INTO jobs (delivery_id, input_data, route_config)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        inserted[0],
                        Jsonb(dict(input_data)),
                        Jsonb(dict(route_config or {})),
                    ),
                ).fetchone()
                if job is None:
                    raise RuntimeError("Job insert returned no identity")
                return AcceptedDelivery(
                    delivery_id=inserted[0],
                    job_id=job[0],
                    status="queued",
                    duplicate=False,
                )

            existing = connection.execute(
                """
                SELECT d.id, d.payload_sha256, d.state, j.id
                FROM deliveries d
                JOIN jobs j ON j.delivery_id = d.id
                WHERE d.provider = %s AND d.external_delivery_id = %s
                FOR UPDATE OF d
                """,
                (verified.provider, verified.event_id),
            ).fetchone()
            if existing is None and verified.provider == "github":
                existing = connection.execute(
                    """
                    SELECT d.id, d.payload_sha256, d.state, j.id
                    FROM deliveries d
                    JOIN jobs j ON j.delivery_id = d.id
                    WHERE d.provider = 'github' AND d.payload_sha256 = %s
                    FOR UPDATE OF d
                    """,
                    (verified.payload_sha256,),
                ).fetchone()
            if existing is None:
                raise RuntimeError("Conflicting delivery disappeared during acceptance")
            if existing[1] != verified.payload_sha256:
                connection.execute(
                    """
                    INSERT INTO delivery_transitions (
                        delivery_id, previous_state, next_state, reason_code,
                        sanitized_detail, actor_type
                    )
                    VALUES (%s, %s, %s, 'delivery_id_collision', %s, 'ingress')
                    """,
                    (
                        existing[0],
                        existing[2],
                        existing[2],
                        Jsonb({"provider": verified.provider}),
                    ),
                )
                collision = True
            else:
                return AcceptedDelivery(
                    delivery_id=existing[0],
                    job_id=existing[3],
                    status=existing[2],
                    duplicate=True,
                )
        if collision:
            raise DeliveryCollisionError("Delivery ID was reused with a different payload")
        raise RuntimeError("Delivery acceptance reached an impossible state")

    def status(self, delivery_id: UUID) -> dict[str, object] | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT d.id, d.provider, d.external_delivery_id, d.event_type,
                       d.state, d.received_at, d.updated_at, j.id, j.state,
                       j.attempt_count, j.retry_count, j.last_error_class,
                       j.last_error_message, j.external_wait_kind
                FROM deliveries d
                JOIN jobs j ON j.delivery_id = d.id
                WHERE d.id = %s
                """,
                (delivery_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "delivery_id": str(row[0]),
            "provider": row[1],
            "external_delivery_id": row[2],
            "event_type": row[3],
            "status": row[4],
            "received_at": row[5].isoformat(),
            "updated_at": row[6].isoformat(),
            "job_id": str(row[7]),
            "job_status": row[8],
            "attempt_count": row[9],
            "retry_count": row[10],
            "last_error": (
                {"class": row[11], "message": row[12]} if row[11] else None
            ),
            "external_wait_kind": row[13],
        }

    def artifact(self, delivery_id: UUID) -> dict[str, object] | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT filename, mime_type, content, byte_size, sha256
                FROM artifacts
                WHERE delivery_id = %s
                """,
                (delivery_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "filename": row[0],
            "mime_type": row[1],
            "content": bytes(row[2]),
            "byte_size": row[3],
            "sha256": row[4],
        }

    def transitions(self, delivery_id: UUID) -> list[dict[str, object]]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT previous_state, next_state, reason_code,
                       sanitized_detail, actor_type, created_at
                FROM delivery_transitions
                WHERE delivery_id = %s
                ORDER BY created_at, id
                """,
                (delivery_id,),
            ).fetchall()
        return [
            {
                "previous_state": row[0],
                "next_state": row[1],
                "reason_code": row[2],
                "detail": row[3],
                "actor_type": row[4],
                "created_at": row[5].isoformat(),
            }
            for row in rows
        ]

    def claim(self, *, worker_id: str, lease_seconds: int) -> ClaimedJob | None:
        with self.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                WITH claimable AS (
                    SELECT id, state = 'processing' AS recovered
                    FROM jobs
                    WHERE (state = 'queued' AND available_at <= now())
                       OR (state = 'retry_wait' AND available_at <= now())
                       OR (state = 'processing' AND lease_until < now())
                    ORDER BY available_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs j
                SET state = 'processing',
                    attempt_count = attempt_count + 1,
                    leased_by = %s,
                    lease_until = now() + (%s * interval '1 second'),
                    updated_at = now()
                FROM claimable
                WHERE j.id = claimable.id
                RETURNING j.id, j.delivery_id, j.input_data, j.attempt_count,
                          j.superdocs_session_id, j.superdocs_job_id, j.external_wait_kind,
                          j.retry_count, j.external_effect_started_at, claimable.recovered,
                          j.leased_by, j.route_config
                """,
                (worker_id, lease_seconds),
            ).fetchone()
            if row is None:
                return None
            delivery = connection.execute(
                """
                UPDATE deliveries
                SET state = 'processing', updated_at = now()
                WHERE id = %s
                RETURNING external_delivery_id
                """,
                (row[1],),
            ).fetchone()
            if delivery is None:
                raise RuntimeError("Claimed job has no delivery")
            return ClaimedJob(
                job_id=row[0],
                delivery_id=row[1],
                external_delivery_id=delivery[0],
                input_data=row[2],
                attempt_count=row[3],
                superdocs_session_id=row[4],
                superdocs_job_id=row[5],
                external_wait_kind=row[6],
                retry_count=row[7],
                external_effect_started_at=row[8],
                recovered=row[9],
                leased_by=row[10],
                route_config=row[11],
            )

    def mark_starting(self, *, job: ClaimedJob) -> None:
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                UPDATE jobs SET external_effect_started_at = now(), updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (job.job_id,),
            )
            connection.execute(
                """
                UPDATE deliveries SET state = 'starting_superdocs', updated_at = now()
                WHERE id = %s
                """,
                (job.delivery_id,),
            )

    def save_started(
        self,
        *,
        job: ClaimedJob,
        session_id: str,
        superdocs_job_id: str,
        poll_after_seconds: float = 0,
    ) -> None:
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', superdocs_session_id = %s, superdocs_job_id = %s,
                    leased_by = NULL, lease_until = NULL,
                    available_at = now() + (%s * interval '1 second'), updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (session_id, superdocs_job_id, poll_after_seconds, job.job_id),
            )

    def requeue(
        self,
        *,
        job: ClaimedJob,
        poll_after_seconds: float,
        clear_wait_kind: bool = False,
    ) -> None:
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', leased_by = NULL, lease_until = NULL,
                    available_at = now() + (%s * interval '1 second'),
                    external_wait_kind = CASE WHEN %s THEN NULL ELSE external_wait_kind END,
                    updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (poll_after_seconds, clear_wait_kind, job.job_id),
            )
            connection.execute(
                "UPDATE deliveries SET state = 'processing', updated_at = now() WHERE id = %s",
                (job.delivery_id,),
            )

    def mark_external_action(self, *, job: ClaimedJob, kind: str, delivery_state: str) -> None:
        if kind not in {"submitting_decisions", "continuing_job", "exporting"}:
            raise ValueError("Unknown external action marker")
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                "UPDATE jobs SET external_wait_kind = %s, updated_at = now() WHERE id = %s",
                (kind, job.job_id),
            )
            connection.execute(
                "UPDATE deliveries SET state = %s, updated_at = now() WHERE id = %s",
                (delivery_state, job.delivery_id),
            )

    def needs_attention(self, *, job: ClaimedJob, reason: str) -> None:
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                UPDATE jobs
                SET state = 'needs_attention', leased_by = NULL, lease_until = NULL,
                    last_error_class = 'ExternalStateError',
                    last_error_message = %s, updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (reason.replace("\n", " ")[:512], job.job_id),
            )
            connection.execute(
                """
                UPDATE deliveries SET state = 'needs_attention', updated_at = now()
                WHERE id = %s
                """,
                (job.delivery_id,),
            )

    def retry(self, *, job: ClaimedJob, error: Exception, delay_seconds: float) -> None:
        message = str(error).replace("\n", " ")[:512]
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                UPDATE jobs
                SET state = 'retry_wait', retry_count = retry_count + 1,
                    available_at = now() + (%s * interval '1 second'),
                    leased_by = NULL, lease_until = NULL,
                    last_error_class = %s, last_error_message = %s,
                    external_effect_started_at = CASE
                        WHEN superdocs_job_id IS NULL THEN NULL
                        ELSE external_effect_started_at
                    END,
                    updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (delay_seconds, type(error).__name__[:128], message, job.job_id),
            )
            connection.execute(
                "UPDATE deliveries SET state = 'retry_wait', updated_at = now() WHERE id = %s",
                (job.delivery_id,),
            )

    def manual_retry(self, *, delivery_id: UUID, actor_id: str) -> dict[str, object]:
        with self.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT j.id, j.state, j.superdocs_job_id
                FROM jobs j
                WHERE j.delivery_id = %s
                FOR UPDATE
                """,
                (delivery_id,),
            ).fetchone()
            if row is None:
                raise LookupError("Delivery not found")
            if row[1] == "needs_attention":
                raise ValueError(
                    "Delivery requires external-state reconciliation before retry"
                )
            if row[1] != "failed":
                raise ValueError(f"Delivery job in state {row[1]!r} is not safe to retry")
            connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', available_at = now(), leased_by = NULL,
                    lease_until = NULL, last_error_class = NULL,
                    last_error_message = NULL, updated_at = now()
                WHERE id = %s
                """,
                (row[0],),
            )
            connection.execute(
                """
                UPDATE deliveries
                SET state = 'queued', updated_at = now()
                WHERE id = %s
                """,
                (delivery_id,),
            )
            connection.execute(
                """
                UPDATE delivery_transitions
                SET actor_type = 'administrator', reason_code = 'manual_retry',
                    sanitized_detail = %s
                WHERE id = (
                    SELECT id FROM delivery_transitions
                    WHERE delivery_id = %s AND next_state = 'queued'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                )
                """,
                (Jsonb({"actor_id": actor_id[:128]}), delivery_id),
            )
            return {
                "delivery_id": str(delivery_id),
                "job_id": str(row[0]),
                "status": "queued",
                "resume_mode": "poll_existing" if row[2] else "start_new",
            }

    def save_review(self, *, job: ClaimedJob, changes: tuple[PendingChange, ...]) -> None:
        if not changes:
            raise ValueError("Change review requires at least one proposed change")
        if any(change.operation not in {"edit", "create", "delete"} for change in changes):
            raise ValueError("Change review contains an unknown operation")
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            for change in changes:
                connection.execute(
                    """
                    INSERT INTO pending_changes (
                        delivery_id, external_change_id, operation, chunk_id,
                        old_html, new_html, ai_explanation
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (delivery_id, external_change_id) DO UPDATE
                    SET operation = EXCLUDED.operation,
                        chunk_id = EXCLUDED.chunk_id,
                        old_html = EXCLUDED.old_html,
                        new_html = EXCLUDED.new_html,
                        ai_explanation = EXCLUDED.ai_explanation,
                        updated_at = now()
                    """,
                    (
                        job.delivery_id,
                        change.change_id,
                        change.operation,
                        change.chunk_id,
                        change.old_html,
                        change.new_html,
                        change.ai_explanation,
                    ),
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'awaiting_approval', external_wait_kind = 'change_review',
                    leased_by = NULL, lease_until = NULL, updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (job.job_id,),
            )
            connection.execute(
                """
                UPDATE deliveries
                SET state = 'awaiting_approval', updated_at = now()
                WHERE id = %s
                """,
                (job.delivery_id,),
            )

    def list_changes(self, delivery_id: UUID) -> list[dict[str, object]]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT external_change_id, operation, chunk_id, old_html,
                       new_html, ai_explanation, review_state
                FROM pending_changes
                WHERE delivery_id = %s
                ORDER BY created_at, external_change_id
                """,
                (delivery_id,),
            ).fetchall()
        return [
            {
                "change_id": row[0],
                "operation": row[1],
                "chunk_id": row[2],
                "old_html": row[3],
                "new_html": row[4],
                "ai_explanation": row[5],
                "review_state": row[6],
            }
            for row in rows
        ]

    def submit_decisions(
        self,
        *,
        delivery_id: UUID,
        decisions: list[ReviewDecision],
        actor_id: str,
        batch_id: UUID,
    ) -> bool:
        if not decisions:
            raise ValueError("At least one decision is required")
        if len({decision.change_id for decision in decisions}) != len(decisions):
            raise ValueError("A change may be decided only once per request")
        with self.pool.connection() as connection, connection.transaction():
            job = connection.execute(
                """
                SELECT j.id, j.state, j.external_wait_kind
                FROM jobs j
                WHERE j.delivery_id = %s
                FOR UPDATE
                """,
                (delivery_id,),
            ).fetchone()
            if job is None:
                raise LookupError("Delivery not found")
            if job[1] != "awaiting_approval" or job[2] != "change_review":
                raise ValueError("Delivery is not awaiting change-review decisions")
            for decision in decisions:
                change = connection.execute(
                    """
                    SELECT id, review_state
                    FROM pending_changes
                    WHERE delivery_id = %s AND external_change_id = %s
                    FOR UPDATE
                    """,
                    (delivery_id, decision.change_id),
                ).fetchone()
                if change is None:
                    raise ValueError(f"Unknown pending change: {decision.change_id}")
                if change[1] != "pending":
                    raise ValueError(f"Change already decided: {decision.change_id}")
                connection.execute(
                    """
                    INSERT INTO decisions (change_id, approved, reason, actor_id, batch_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (change[0], decision.approved, decision.reason, actor_id, batch_id),
                )
                connection.execute(
                    """
                    UPDATE pending_changes
                    SET review_state = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    ("approved" if decision.approved else "rejected", change[0]),
                )
            remaining = connection.execute(
                """
                SELECT count(*) FROM pending_changes
                WHERE delivery_id = %s AND review_state = 'pending'
                """,
                (delivery_id,),
            ).fetchone()
            all_resolved = remaining == (0,)
            if all_resolved:
                connection.execute(
                    """
                    UPDATE jobs
                    SET state = 'queued', available_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (job[0],),
                )
                connection.execute(
                    """
                    UPDATE deliveries SET state = 'approving', updated_at = now()
                    WHERE id = %s
                    """,
                    (delivery_id,),
                )
            return all_resolved

    def decision_payload(self, job: ClaimedJob) -> list[dict[str, object]]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT p.external_change_id, d.approved, d.reason
                FROM pending_changes p
                JOIN decisions d ON d.change_id = p.id
                WHERE p.delivery_id = %s
                ORDER BY p.created_at, p.external_change_id
                """,
                (job.delivery_id,),
            ).fetchall()
        return [
            {
                "change_id": row[0],
                "approved": row[1],
                **({"feedback": row[2]} if row[2] else {}),
            }
            for row in rows
        ]

    def complete(
        self,
        *,
        job: ClaimedJob,
        export_format: str,
        filename: str,
        mime_type: str,
        content: bytes,
        max_artifact_bytes: int,
        superdocs_session_id: str,
        superdocs_job_id: str,
    ) -> None:
        if len(content) > max_artifact_bytes:
            raise ValueError("Exported artifact exceeds the configured size limit")
        digest = hashlib.sha256(content).hexdigest()
        storage_key = f"deliveries/{job.delivery_id}/{filename}"
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                INSERT INTO artifacts (
                    delivery_id, export_format, storage_key, content,
                    byte_size, sha256, mime_type, filename
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (delivery_id) DO UPDATE
                SET export_format = EXCLUDED.export_format,
                    storage_key = EXCLUDED.storage_key,
                    content = EXCLUDED.content,
                    byte_size = EXCLUDED.byte_size,
                    sha256 = EXCLUDED.sha256,
                    mime_type = EXCLUDED.mime_type,
                    filename = EXCLUDED.filename,
                    created_at = now()
                """,
                (
                    job.delivery_id,
                    export_format,
                    storage_key,
                    content,
                    len(content),
                    digest,
                    mime_type,
                    filename,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'completed', leased_by = NULL, lease_until = NULL,
                    superdocs_session_id = %s, superdocs_job_id = %s, updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (superdocs_session_id, superdocs_job_id, job.job_id),
            )
            connection.execute(
                "UPDATE deliveries SET state = 'completed', updated_at = now() WHERE id = %s",
                (job.delivery_id,),
            )

    def fail(self, *, job: ClaimedJob, error: Exception) -> None:
        message = str(error).replace("\n", " ")[:512]
        with self.pool.connection() as connection, connection.transaction():
            self._assert_lease(connection, job)
            connection.execute(
                """
                UPDATE jobs
                SET state = 'failed', leased_by = NULL, lease_until = NULL,
                    last_error_class = %s, last_error_message = %s, updated_at = now()
                WHERE id = %s AND state = 'processing'
                """,
                (type(error).__name__[:128], message, job.job_id),
            )
            connection.execute(
                "UPDATE deliveries SET state = 'failed', updated_at = now() WHERE id = %s",
                (job.delivery_id,),
            )
