"""
RECIPE 1 — Generate a contract from a template.

Flow (matches the brief exactly):
    1. generate_from_template
    2. async SuperDocs job starts
    3. return operation/job ID immediately (non-blocking)
    4. connector worker polls in the background
    5. completed callback fires
    6. the recipe (the platform) receives the generated document/result

Failure branch: if the SuperDocs job itself fails (model error, timeout) or
the poll loop exceeds max_poll_seconds, a 'failed' callback event is fired
instead of 'completed' — the platform's recipe branches on `event.status` in
its own callback handler; this connector never silently drops a failure.

Retry handling: the underlying HTTP calls already retry transient failures
(connector/http_client.py's retry contract). This recipe adds nothing on top
of that for the SuperDocs call itself, since retrying "generate a contract"
at the recipe level would risk double-generating documents.
"""
from __future__ import annotations

from dataclasses import dataclass

from connector.callbacks import CallbackDispatcher
from connector.http_client import SuperDocsHTTPClient
from connector.worker import JobWorker
from schemas.generate_from_template import GenerateFromTemplateInput, TemplateReference


@dataclass
class GenerateContractRecipeInput:
    customer_name: str
    template_reference: TemplateReference
    contract_details: str  # free-text instruction detail, e.g. "effective 2026-01-01, 12 month term"
    callback_dispatcher: CallbackDispatcher
    model_tier: str = "core"


@dataclass
class GenerateContractRecipeOutput:
    operation_id: str
    job_id: str | None
    session_id: str
    status: str


async def run_recipe_1(
    client: SuperDocsHTTPClient, worker: JobWorker, recipe_input: GenerateContractRecipeInput
) -> GenerateContractRecipeOutput:
    from connector.operations.generate_from_template import generate_from_template

    instruction = (
        f"Draft a contract for {recipe_input.customer_name}. {recipe_input.contract_details}"
    )

    result = await generate_from_template(client, GenerateFromTemplateInput(
        template_reference=recipe_input.template_reference,
        instruction=instruction,
        run_async=True,  # non-blocking: the whole point of this recipe
    ))

    if result.job_id is not None:
        # Step 3/4/5/6: return immediately, poll + callback in the background.
        worker.start_background(result.job_id, recipe_input.callback_dispatcher, operation_id=result.operation_id)

    return GenerateContractRecipeOutput(
        operation_id=result.operation_id,
        job_id=result.job_id,
        session_id=result.session_id,
        status=result.status.value,
    )
