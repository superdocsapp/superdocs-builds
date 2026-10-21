"""IdempotencyStore must be a durable no-op-on-retry cache — see core/idempotency.py."""

from __future__ import annotations

from core.idempotency import IdempotencyStore


def test_get_returns_none_for_unknown_key(idempotency_store: IdempotencyStore) -> None:
    assert idempotency_store.get("test:unknown") is None


def test_put_then_get_roundtrips(idempotency_store: IdempotencyStore) -> None:
    idempotency_store.put("test:key-1", {"result": "first call"})
    assert idempotency_store.get("test:key-1") == {"result": "first call"}


def test_retry_with_same_key_does_not_overwrite(
    idempotency_store: IdempotencyStore,
) -> None:
    """The core guarantee: first write wins, a retried put() with the same key
    is a no-op — this is what makes a caller-level retry provably safe."""
    idempotency_store.put("test:key-2", {"result": "original"})
    idempotency_store.put("test:key-2", {"result": "this must be ignored"})
    assert idempotency_store.get("test:key-2") == {"result": "original"}
