from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from review_fsm.models import ReviewEvent, ReviewEventType, ReviewSnapshot
from review_fsm.persistence import ReviewRuntime
from review_fsm.reconciliation import (
    DurableJobProvider,
    ReviewReconciliationError,
    reconcile_runtime,
)


class CreateBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1, max_length=128)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class DispatchEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    type: ReviewEventType
    payload: dict[str, JsonValue] = Field(default_factory=dict)


def create_review_router(
    runtime_factory: Callable[[], ReviewRuntime],
    provider_factory: Callable[[], DurableJobProvider],
) -> APIRouter:
    router = APIRouter(prefix="/review-fsm", tags=["Review state machine"])

    def runtime() -> ReviewRuntime:
        return runtime_factory()

    def provider() -> DurableJobProvider:
        return provider_factory()

    @router.post("/batches", response_model=ReviewSnapshot, status_code=201)
    async def create_batch(
        body: CreateBatchRequest,
        active: Annotated[ReviewRuntime, Depends(runtime)],
    ) -> ReviewSnapshot:
        return await active.create(body.batch_id, context=body.context)

    @router.get("/batches/{batch_id}", response_model=ReviewSnapshot)
    async def get_batch(
        batch_id: str,
        active: Annotated[ReviewRuntime, Depends(runtime)],
    ) -> ReviewSnapshot:
        snapshot = await active.load(batch_id)
        if snapshot is None:
            raise HTTPException(404, "Review batch not found")
        return snapshot

    @router.post("/batches/{batch_id}/events", response_model=ReviewSnapshot)
    async def dispatch_event(
        batch_id: str,
        body: DispatchEventRequest,
        active: Annotated[ReviewRuntime, Depends(runtime)],
    ) -> ReviewSnapshot:
        result = await active.dispatch(
            ReviewEvent(batch_id=batch_id, **body.model_dump(mode="json"))
        )
        return result.snapshot

    @router.post("/batches/{batch_id}/reconcile", response_model=ReviewSnapshot)
    async def reconcile_batch(
        batch_id: str,
        active: Annotated[ReviewRuntime, Depends(runtime)],
        durable_provider: Annotated[DurableJobProvider, Depends(provider)],
    ) -> ReviewSnapshot:
        try:
            return await reconcile_runtime(
                active, batch_id=batch_id, provider=durable_provider
            )
        except ReviewReconciliationError as exc:
            raise HTTPException(409, detail={"code": exc.code, "message": exc.message}) from exc

    return router
