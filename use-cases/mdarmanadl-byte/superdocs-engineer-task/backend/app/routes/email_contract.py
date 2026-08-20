import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.email_contract import (
    EmailContractCreate,
    EmailContractGenerate,
)
from app.services.email_contract import (
    email_contract_service,
)
from app.services.superdocs import (
    superdocs_client,
)
from fastapi.responses import Response

router = APIRouter(
    prefix="/api/email-contracts",
    tags=["email-contracts"],
)


def parse_superdocs_response(response):
    if not isinstance(response, dict):
        return {}

    raw = response.get("superdocs_response")

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "response": raw,
            }

    return response


# ---------------------------------------------------------
# CREATE CONTRACT SESSION
# ---------------------------------------------------------

@router.post("/create")
async def create_contract(
    data: EmailContractCreate,
):
    return await email_contract_service.create_contract(
        data
    )


# ---------------------------------------------------------
# GENERATE FIRST-PASS CONTRACT
# ---------------------------------------------------------

@router.post("/generate")
async def generate_contract(
    data: EmailContractGenerate,
):
    contract = await email_contract_service.get_contract(
        data.contract_id
    )

    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Email contract not found.",
        )

    

    prompt = f"""
You are an Email-to-Contract document agent.

The user has supplied a fictional email negotiation
thread.

NEGOTIATION THREAD
==================
{data.negotiation_thread}
==================

CONTRACT TYPE
=============
{data.contract_type}

Your job is to create a FIRST-PASS CONTRACT.

IMPORTANT SOURCE RULE:

The negotiation thread above is the ONLY source
of business terms.

First identify the terms that were actually agreed.

Then draft the contract using an appropriate
existing contract template.

The final editable document must contain every
agreed business term.

AGREEMENT RULES:

- Include only terms that were actually agreed.
- If one party proposed something and the other
  party rejected it, DO NOT include it.
- If a proposal was never accepted, DO NOT treat
  it as an agreed term.
- Preserve agreed prices exactly.
- Preserve agreed dates exactly.
- Preserve agreed payment terms exactly.
- Preserve agreed deliverables exactly.
- Preserve agreed responsibilities exactly.
- Preserve agreed termination terms exactly.

DO NOT INVENT:

- prices
- dates
- parties
- payment schedules
- deliverables
- obligations
- penalties
- warranties
- termination conditions
- governing law
- addresses
- legal clauses

If a normal contract field is not supported by
the negotiation, write:

"Not specified in negotiation."

Do not fill missing information using assumptions.

TEMPLATE REQUIREMENT:

Use an appropriate existing SuperDocs contract
template for the contract type.

The result must be an editable contract document,
not merely a summary of the emails.

REVIEW REQUIREMENT:

Generate the contract as proposed document changes
with human approval enabled.

The user must be able to review and approve the
changes before they become final.
"""

    try:
        result = await superdocs_client.chat(
            session_id=contract.session_id,
            message=prompt,
            approval_mode="ask_every_time",
        )

        parsed = parse_superdocs_response(result)

        document_changes = (
            parsed.get("document_changes")
            or {}
        )

        contract.status = "generated"

        contract.job_id = parsed.get(
            "job_id"
        )

        contract.pending_changes = (
            document_changes.get(
                "pending_changes"
            )
            or parsed.get(
                "pending_changes"
            )
            or []
        )

        contract.response = parsed

        return {
            "contract_id": contract.contract_id,
            "session_id": contract.session_id,
            "contract_type": contract.contract_type,
            "status": contract.status,
            "job_id": contract.job_id,
            "pending_changes": contract.pending_changes,
            "response": result,
        }

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


# ---------------------------------------------------------
# CONTRACT STATUS
# ---------------------------------------------------------

@router.get("/{contract_id}/status")
async def get_contract_status(
    contract_id: str,
):
    contract = await email_contract_service.get_contract(
        contract_id
    )

    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Email contract not found.",
        )

    return {
        "contract_id": contract.contract_id,
        "session_id": contract.session_id,
        "contract_type": contract.contract_type,
        "status": contract.status,
        "job_id": contract.job_id,
        "pending_changes": contract.pending_changes,
    }


# ---------------------------------------------------------
# GET COMPLETE CONTRACT STATE
# ---------------------------------------------------------

@router.get("/{contract_id}")
async def get_contract(
    contract_id: str,
):
    contract = await email_contract_service.get_contract(
        contract_id
    )

    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Email contract not found.",
        )

    return contract

@router.post("/{contract_id}/export")
async def export_email_contract(
    contract_id: str,
):
    contract = await email_contract_service.get_contract(
        contract_id
    )

    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Email contract not found.",
        )

    try:
        exported = await superdocs_client.export_document(
            session_id=contract.session_id,
            export_format="pdf",
        )

        headers = {}

        if exported.get("filename"):
            headers["Content-Disposition"] = (
                exported["filename"]
            )

        headers["Content-Disposition"] = (
            f'attachment; filename="email-contract-{contract_id}.pdf"'
        )

        return Response(
            content=exported["content"],
            media_type=exported["content_type"],
            headers=headers,
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )