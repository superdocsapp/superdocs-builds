"""Multi-tenant isolation: separate credentials, separate Box/SuperDocs
clients, and separate data stores (review queue, audit history,
checkpoints, idempotency, run/metrics counters) per tenant, so a second
enterprise customer can never see a first customer's files, metadata, or
audit trail through this API.

What this does NOT do yet: a self-serve Box OAuth "Connect your Box
account" flow. Tenant Box/SuperDocs credentials are still supplied by an
operator, either via a tenant config file (TENANTS_CONFIG_PATH) or, for
a single-tenant deployment, the same top-level BOX_*/SUPERDOCS_* env vars
this app has always read. Building the OAuth consent flow itself (Box's
own authorization-code exchange, encrypted-at-rest token storage, token
refresh) is real, separate work -- this module makes the rest of the
system tenant-aware so that flow has somewhere real to plug into, rather
than requiring another full data-model rework later.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from app.clients.box_client import BoxClient
from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.clients.real_box_client import RealBoxClient
from app.clients.real_superdocs_client import RealSuperDocsClient
from app.clients.superdocs_client import SuperDocsClient
from app.storage.sqlite_backend import (
    SqliteCheckpointStore,
    SqliteHistoryStore,
    SqliteIdempotencyStore,
    SqliteReviewQueue,
)
from app.workflow.checkpoint import CheckpointStore
from app.workflow.dead_letter import DeadLetterQueue
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.idempotency import IdempotencyStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.retry import CircuitBreaker
from app.workflow.review_queue import ReviewQueue

logger = logging.getLogger("box_workflow.tenancy")

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


@dataclass(frozen=True)
class TenantConfig:
    """One customer's isolated identity: their API key, and (optionally)
    their own Box/SuperDocs credentials. If box_* fields are omitted, the
    tenant falls back to this deployment's top-level BOX_*/SUPERDOCS_* env
    vars -- correct for a single-tenant deployment (the common case this
    build actually needs to support today) and a real per-tenant override
    point for a genuinely multi-tenant one."""

    tenant_id: str
    api_key: str
    box_client_id: Optional[str] = None
    box_client_secret: Optional[str] = None
    box_enterprise_id: Optional[str] = None
    box_jwt_private_key: Optional[str] = None
    superdocs_api_key: Optional[str] = None
    review_threshold: float = 0.7
    # Per-field override, e.g. {"contract_value": 0.85}. A field not
    # listed here falls back to review_threshold. Lets a tenant demand
    # a tighter bar on fields where being wrong is expensive (money,
    # legal terms) without a policy engine.
    field_thresholds: dict = field(default_factory=dict)

    def __post_init__(self):
        if not _TENANT_ID_RE.match(self.tenant_id):
            raise ValueError(
                f"invalid tenant_id {self.tenant_id!r}: must be alphanumeric "
                "plus '_'/'-', 1-64 chars (it's used as a filesystem path "
                "component for that tenant's SQLite database)"
            )
        if not self.api_key:
            raise ValueError(f"tenant {self.tenant_id!r} has no api_key configured")


@dataclass
class TenantContext:
    """Everything one tenant's requests touch, and nothing another
    tenant's requests can reach through it: their own Box/SuperDocs
    clients, their own pipeline, their own review queue / audit history /
    checkpoints / idempotency store, and their own run/metrics counters."""

    tenant_id: str
    box: BoxClient
    superdocs: SuperDocsClient
    pipeline: BoxMetadataWritebackPipeline
    review_queue: Any
    history: Any
    dead_letter: DeadLetterQueue = field(default_factory=DeadLetterQueue)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    runs: dict = field(default_factory=dict)
    runs_lock: threading.Lock = field(default_factory=threading.Lock)
    metrics_lock: threading.Lock = field(default_factory=threading.Lock)
    metrics: dict = field(
        default_factory=lambda: {
            "runs_processed_total": 0,
            "runs_skipped_total": 0,
            "stage_failures_total": 0,
            "operations_total": 0,
        }
    )
    latency_samples_ms: deque = field(default_factory=lambda: deque(maxlen=500))


def _build_box_client(cfg: TenantConfig) -> BoxClient:
    if cfg.box_client_id and cfg.box_client_secret and cfg.box_enterprise_id:
        return RealBoxClient(
            client_id=cfg.box_client_id,
            client_secret=cfg.box_client_secret,
            enterprise_id=cfg.box_enterprise_id,
            rsa_private_key_data=cfg.box_jwt_private_key,
        )
    # No per-tenant Box credentials configured: fall back to this
    # deployment's shared BOX_* env vars (single-tenant case), then to
    # the in-memory fake, matching the pre-multi-tenancy behavior exactly
    # so existing single-tenant deployments don't need to change anything.
    return RealBoxClient.from_env() or FakeBoxClient()


def _build_superdocs_client(cfg: TenantConfig) -> SuperDocsClient:
    if cfg.superdocs_api_key:
        return RealSuperDocsClient(
            api_key=cfg.superdocs_api_key,
            base_url=os.environ.get("SUPERDOCS_API_BASE", "https://api.superdocs.app"),
            model_tier=os.environ.get("SUPERDOCS_MODEL_TIER", "core"),
        )
    return RealSuperDocsClient.from_env() or FakeSuperDocsClient()


def _build_stores(
    tenant_id: str,
    db_dir: Optional[str],
    review_threshold: float = 0.7,
    field_thresholds: Optional[dict] = None,
):
    """Each tenant gets its own SQLite file (tenant-{id}.db under
    db_dir), not shared tables in one file -- a query bug that forgets a
    WHERE tenant_id = ? clause can leak across tables in a shared-schema
    design; separate files make that class of bug structurally
    impossible instead of relying on every query getting the filter
    right. With no db_dir configured (dev/test), stores are in-memory
    and still fully isolated per tenant, just not durable -- same
    tradeoff as the pre-multi-tenancy single-tenant path."""
    if not db_dir:
        return (
            IdempotencyStore(),
            ReviewQueue(threshold=review_threshold, field_thresholds=field_thresholds),
            MetadataHistoryStore(),
            CheckpointStore(),
        )
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, f"tenant-{tenant_id}.db")
    return (
        SqliteIdempotencyStore(db_path),
        SqliteReviewQueue(db_path, threshold=review_threshold, field_thresholds=field_thresholds),
        SqliteHistoryStore(db_path),
        SqliteCheckpointStore(db_path),
    )


def build_tenant_context(cfg: TenantConfig, db_dir: Optional[str]) -> TenantContext:
    box = _build_box_client(cfg)
    superdocs = _build_superdocs_client(cfg)
    idempotency, review_queue, history, checkpoint = _build_stores(
        cfg.tenant_id, db_dir, cfg.review_threshold, cfg.field_thresholds
    )
    dead_letter = DeadLetterQueue()
    circuit_breaker = CircuitBreaker(
        failure_threshold=int(os.environ.get("WORKFLOW_CIRCUIT_FAILURE_THRESHOLD", "5")),
        reset_after_seconds=float(os.environ.get("WORKFLOW_CIRCUIT_RESET_SECONDS", "30")),
    )
    pipeline = BoxMetadataWritebackPipeline(
        box,
        superdocs,
        idempotency,
        review_queue=review_queue,
        history=history,
        checkpoint=checkpoint,
        circuit_breaker=circuit_breaker,
        dead_letter=dead_letter,
    )
    return TenantContext(
        tenant_id=cfg.tenant_id,
        box=box,
        superdocs=superdocs,
        pipeline=pipeline,
        review_queue=review_queue,
        history=history,
        dead_letter=dead_letter,
        circuit_breaker=circuit_breaker,
    )


class TenantRegistry:
    """Resolves an API key to a tenant's isolated context. Two ways to
    configure tenants:

    1. TENANTS_CONFIG_PATH (a JSON file: a list of the TenantConfig
       fields above) -- the real multi-tenant path, one entry per
       customer.
    2. WORKFLOW_API_KEYS (comma-separated bare keys, the pre-multi-tenancy
       format) -- kept working unchanged for backward compatibility.
       Each key becomes its own tenant, named tenant-0, tenant-1, ...,
       sharing this deployment's single set of top-level BOX_*/
       SUPERDOCS_* credentials (since bare keys carry no per-tenant Box
       identity). This is what a single-tenant deployment should keep
       using; TENANTS_CONFIG_PATH is for an operator serving more than
       one customer from one deployment.

    If neither is set, auth is disabled (dev/test) and every request
    resolves to a single unauthenticated "default" tenant -- matching
    the behavior before multi-tenancy existed.
    """

    def __init__(self, db_dir: Optional[str] = None) -> None:
        self._db_dir = db_dir
        self._configs_by_key: dict[str, TenantConfig] = {}
        self._contexts: dict[str, TenantContext] = {}
        self._lock = threading.Lock()
        self.auth_enabled = False
        self._load()

    def _load(self) -> None:
        config_path = os.environ.get("TENANTS_CONFIG_PATH")
        if config_path:
            with open(config_path) as f:
                raw = json.load(f)
            for entry in raw:
                cfg = TenantConfig(**entry)
                self._configs_by_key[cfg.api_key] = cfg
            self.auth_enabled = True
            logger.info("loaded %d tenant(s) from %s", len(self._configs_by_key), config_path)
            return

        raw_keys = os.environ.get("WORKFLOW_API_KEYS", "")
        keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        if keys:
            for i, key in enumerate(keys):
                cfg = TenantConfig(tenant_id=f"tenant-{i}", api_key=key)
                self._configs_by_key[key] = cfg
            self.auth_enabled = True
            return

        # No auth configured at all: single implicit tenant, no key
        # required. Dev/test only -- see the ENVIRONMENT=production
        # startup guard in app/api/main.py, which refuses this mode.
        self._configs_by_key = {}
        self.auth_enabled = False

    def resolve(self, presented_key: Optional[str]) -> Optional[str]:
        """Returns the tenant_id for a presented bearer token using
        constant-time comparison against every configured key (not just
        early-exiting on the first match), or None if auth is disabled
        and no key was required. Raises nothing -- the caller (the
        require_api_key dependency) turns a None-with-auth-enabled result
        into a 401."""
        import secrets as _secrets

        if not self.auth_enabled:
            return "default"
        if presented_key is None:
            return None
        matched = None
        for key, cfg in self._configs_by_key.items():
            if _secrets.compare_digest(presented_key, key):
                matched = cfg.tenant_id
        return matched

    def context_for(self, tenant_id: str) -> TenantContext:
        with self._lock:
            ctx = self._contexts.get(tenant_id)
            if ctx is None:
                cfg = next(c for c in self._configs_by_key.values() if c.tenant_id == tenant_id) if self.auth_enabled else TenantConfig(tenant_id="default", api_key="unused")
                ctx = build_tenant_context(cfg, self._db_dir)
                self._contexts[tenant_id] = ctx
            return ctx

    def all_contexts(self) -> list[TenantContext]:
        with self._lock:
            return list(self._contexts.values())
