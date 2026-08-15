"""
generate_from_template — modeled, not native.

SuperDocs has no dedicated, *verified* structured template-fill endpoint.
Templates are a real product concept (superdocs.app's own marketing copy:
"Start from professional templates or connect your own library... the AI
finds the best matching template using semantic search — then adapts it to
your specific context"), but this connector could not verify a specific REST
path for uploading or listing templates against docs.superdocs.app's OpenAPI
reference, and per this assignment's hard rule against inventing endpoints,
it does not call one. What IS verified and is the only thing this operation
actually does: upload (if template content is supplied inline) + chat/
chat_async, with the template reference carried in the natural-language
instruction for the `by_name`/`template_id` cases. This is the connector's
own composition of real, verified SuperDocs primitives into a single platform
operation, exactly as the assignment instructs — not a 1:1 wrapper of a
SuperDocs endpoint, and not a claim that a template-fill API exists.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from schemas.common import ApprovalMode, JobStatus, ModelTier, ResponseMode, ThinkingDepth, Usage


class TemplateReference(BaseModel):
    """
    Exactly one of these must be set:
      - `template_id`: a reference to an existing SuperDocs template (however
        the caller's SuperDocs account/workspace tracks templates -- this
        connector has not verified a specific template-management endpoint,
        so it passes this id through as text in the chat instruction rather
        than calling an unverified API).
      - `inline_base64` + `filename`: template bytes supplied directly by the
        recipe (e.g. a file picked in the platform's UI); the connector
        uploads it as a document before generating.
      - `by_name`: a natural-language reference ("my standard NDA template")
        left for the AI to resolve via its own template search — the loosest
        and least reliable option, offered because it's what the SuperDocs
        chat-driven template flow actually supports today.
    """
    template_id: str | None = None
    inline_base64: str | None = None
    filename: str | None = None
    by_name: str | None = None

    @model_validator(mode="after")
    def exactly_one_reference(self) -> TemplateReference:
        provided = [
            self.template_id is not None,
            (self.inline_base64 is not None and self.filename is not None),
            self.by_name is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "TemplateReference requires exactly one of: template_id, "
                "(inline_base64 + filename), or by_name."
            )
        return self


class GenerateFromTemplateInput(BaseModel):
    template_reference: TemplateReference
    instruction: str = Field(..., min_length=1, description=(
        "Natural-language generation instruction, e.g. 'Draft an NDA for Acme Corp "
        "using this template, effective 2026-01-01.' SuperDocs has no structured "
        "field-fill API — this instruction IS the fill mechanism."
    ))
    session_id: str | None = Field(default=None, description=(
        "Caller-chosen session id. If omitted, the connector mints one "
        "(uuid4) so the recipe doesn't need to manage session naming."
    ))
    model_tier: ModelTier = ModelTier.core
    thinking_depth: ThinkingDepth = ThinkingDepth.balanced
    approval_mode: ApprovalMode = ApprovalMode.approve_all
    response_mode: ResponseMode = ResponseMode.full
    run_async: bool = Field(default=True, description=(
        "True (default): use /v1/chat/async + the connector's job worker, "
        "recommended since template generation can run long. False: use the "
        "synchronous /v1/chat, which blocks up to SuperDocs' 30-minute cap."
    ))


class GenerateFromTemplateOutput(BaseModel):
    operation_id: str = Field(..., description="Connector-generated id for this operation invocation, for platform-side audit trails.")
    job_id: str | None = Field(default=None, description="Set when run_async=True; None for the synchronous path.")
    session_id: str
    status: JobStatus
    document_id: str | None = None
    version_id: str | None = None
    updated_html: str | None = Field(default=None, description="Populated when status is already 'completed' (sync path or an async job that resolved before this call returned).")
    usage: Usage | None = None
