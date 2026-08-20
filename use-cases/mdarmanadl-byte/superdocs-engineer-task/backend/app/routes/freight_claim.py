from typing import Annotated, Any
import json
import uuid

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel

from app.services.superdocs import superdocs_client
from app.services.freight_claim import freight_claim_service
from app.schemas.freight_claim import (
    ClaimEvidence,
    FreightClaimCreate,
)


router = APIRouter(
    prefix="/api/freight-claims",
    tags=["freight-claims"],
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def parse_superdocs_response(response: Any) -> dict:
    """
    SuperDocs /v1/chat returns a wrapper like:

    {
        "superdocs_status": 200,
        "superdocs_response": "{\"response\":\"...\"}"
    }

    Normalize it to the actual SuperDocs JSON.
    """

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


async def get_claim_by_session(session_id: str):
    claim = await freight_claim_service.get_by_session(
        session_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim session not found.",
        )

    return claim


# ---------------------------------------------------------
# 1. Upload evidence
# ---------------------------------------------------------

@router.post("/upload")
async def upload_claim_evidence(
    carrier: Annotated[str, Form(...)],
    document_types: Annotated[str, Form(...)],
    files: list[UploadFile],
):
    try:
        try:
            types = json.loads(document_types)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="document_types must be valid JSON.",
            )

        if not isinstance(types, list):
            raise HTTPException(
                status_code=400,
                detail="document_types must be a JSON array.",
            )

        if not files:
            raise HTTPException(
                status_code=400,
                detail="At least one evidence file is required.",
            )

        if len(files) != len(types):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Number of document types must match "
                    "number of files."
                ),
            )

        allowed_types = {
            "pod",
            "invoice",
            "damage_photo",
            "repair_quote",
            "salvage_quote",
        }

        for document_type in types:
            if document_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unsupported document type: "
                        f"{document_type}"
                    ),
                )

        session_id = f"freight-claim-{uuid.uuid4()}"

        evidence = []

        for upload_file, document_type in zip(
            files,
            types,
        ):
            file_bytes = await upload_file.read()

            if not file_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Empty file: "
                        f"{upload_file.filename}"
                    ),
                )

            content_type = (
                upload_file.content_type
                or "application/octet-stream"
            )

            # Create SuperDocs upload
            upload = await superdocs_client.create_upload(
                filename=upload_file.filename,
                content_type=content_type,
                size_bytes=len(file_bytes),
            )

            upload_id = upload["upload_id"]
            upload_url = upload["upload_url"]

            # Upload actual bytes
            await superdocs_client.upload_file_to_storage(
                upload_url=upload_url,
                file_bytes=file_bytes,
                content_type=content_type,
            )

            # Process document into SuperDocs session
            processed = await superdocs_client.process_upload(
                upload_id=upload_id,
                session_id=session_id,
                filename=upload_file.filename,
                open_mode="new_focused",
            )

            processed_content = processed.get("html", "")

            evidence.append(
                ClaimEvidence(
                    filename=upload_file.filename,
                    document_type=document_type,
                    upload_id=upload_id,
                    session_id=session_id,
                    content=processed_content,
                )
            )

        claim = await freight_claim_service.create_claim(
            FreightClaimCreate(
                carrier=carrier,
                evidence=evidence,
            ),
            session_id=session_id,
        )

        return {
            "claim_id": claim.claim_id,
            "session_id": claim.session_id,
            "carrier": claim.carrier,
            "status": claim.status,
            "evidence": [
                item.model_dump()
                for item in claim.evidence
            ],
        }

    except HTTPException:
        raise

    except Exception as error:
        import traceback

        print("\n========== FREIGHT CLAIM UPLOAD ERROR ==========")
        print("ERROR:", repr(error))
        traceback.print_exc()
        print("================================================\n")

        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


# ---------------------------------------------------------
# 2. Generate claim letter
# ---------------------------------------------------------

class GenerateClaimRequest(BaseModel):
    session_id: str
    carrier: str


@router.post("/generate")
async def generate_claim(
    data: GenerateClaimRequest,
):
    claim = await get_claim_by_session(
        data.session_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim not found.",
        )

    evidence_context = []

    for item in claim.evidence:
        evidence_context.append(
            f"""
--- EVIDENCE DOCUMENT ---
Filename: {item.filename}
Document Type: {item.document_type}

Extracted Content:
{item.content or "No extracted content available."}
--- END EVIDENCE ---
"""
        )

    evidence_text = "\n".join(evidence_context)

    prompt = f"""
Prepare a freight cargo damage claim for carrier:
{data.carrier}

IMPORTANT:
The evidence below is the COMPLETE source of truth.

You MUST inspect EVERY evidence document below.

Do NOT rely on which document is currently focused
in the SuperDocs session.

EVIDENCE
========

{evidence_text}

Create the claim letter with:

1. CLAIM INFORMATION
- Carrier
- Shipment/reference number
- Claim date if present
- Other identifying information present in evidence

2. DELIVERY EXCEPTION
Quote the delivery exception notation EXACTLY
as it appears in the POD.

Do not paraphrase it.

3. DAMAGE DESCRIPTION
Describe damage using the uploaded photographs
and supporting evidence.

Do not invent damage.

4. CLAIM VALUE
Use the commercial invoice amount EXACTLY
as written.

If a repair or salvage quote contains an amount,
include that amount EXACTLY as written.

Never calculate, round, estimate, or invent amounts.

5. SUPPORTING EVIDENCE
List EVERY uploaded evidence document:

- POD
- Commercial Invoice
- Damage Photograph
- Repair Quote
- Salvage Quote if present

6. REQUEST FOR RESOLUTION
Write a professional request for the carrier
to process the claim.

STRICT ACCURACY RULES:

- Never invent shipment numbers.
- Never invent dates.
- Never invent amounts.
- Never alter currency values.
- Never invent damage.
- Never invent carrier policies.
- If information is missing, say it is missing.
- Every factual value must come from the evidence above.

Return the claim as an editable document.
"""

    try:
        response = await superdocs_client.chat(
            session_id=data.session_id,
            message=prompt,
            approval_mode="ask_every_time",
        )

        parsed = parse_superdocs_response(response)

        document_changes = (
            parsed.get("document_changes")
            or {}
        )

        claim.status = "claim_generated"

        claim.job_id = parsed.get("job_id")

        claim.claim_response = parsed

        claim.pending_changes = (
            document_changes.get("pending_changes")
            or parsed.get("pending_changes")
            or []
        )

        return {
            "status": "generated",
            "claim_id": claim.claim_id,
            "session_id": claim.session_id,
            "carrier": claim.carrier,
            "superdocs_response": response,
        }

    except Exception as error:
        import traceback

        print("\n========== FREIGHT CLAIM GENERATE ERROR ==========")
        print("ERROR:", repr(error))
        traceback.print_exc()
        print("===================================================\n")

        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

# ---------------------------------------------------------
# 3. Build indexed claim packet
# ---------------------------------------------------------

class BuildPacketRequest(BaseModel):
    session_id: str
    carrier: str


@router.post("/packet")
async def build_claim_packet(
    data: BuildPacketRequest,
):
    claim = await get_claim_by_session(
        data.session_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim not found.",
        )

    evidence_context = []

    for item in claim.evidence:
        evidence_context.append(
            f"""
--- EVIDENCE DOCUMENT ---
Filename: {item.filename}
Document Type: {item.document_type}

Extracted Content:
{item.content or "No extracted content available."}
--- END EVIDENCE ---
"""
        )

    evidence_text = "\n".join(evidence_context)

    prompt = f"""
Using the existing freight claim and ALL evidence
provided below, assemble the final freight claim
packet for {data.carrier}.

IMPORTANT:
The evidence below is the complete source of truth.
Inspect EVERY evidence document.

EVIDENCE
========

{evidence_text}

The packet MUST contain:

1. Carrier-specific cover page.

2. Evidence index / table of contents.

3. Claim letter.

4. Proof of Delivery / delivery exception.

5. Commercial invoice.

6. Damage photographs.

7. A short factual caption for every damage photo.

8. Repair quote or salvage quote.

9. Shipment/reference information found in
   the evidence.

IMPORTANT:

- Preserve original evidence.
- Do not invent facts.
- Do not change invoice amounts.
- Do not change reference numbers.
- Do not invent dates.
- Do not invent damage.
- Photo captions must be grounded in the
  uploaded evidence.
- Missing evidence must be explicitly marked
  as missing.
- Keep the packet ordered and clearly labeled.

The resulting packet must remain editable and
ready for human review.
"""

    try:
        response = await superdocs_client.chat(
            session_id=data.session_id,
            message=prompt,
            approval_mode="ask_every_time",
        )

        parsed = parse_superdocs_response(response)

        document_changes = (
            parsed.get("document_changes")
            or {}
        )

        claim.status = "packet_generated"

        claim.packet_response = parsed

        claim.job_id = (
            parsed.get("job_id")
            or claim.job_id
        )

        claim.pending_changes = (
            document_changes.get("pending_changes")
            or parsed.get("pending_changes")
            or []
        )

        return {
            "status": "packet_generated",
            "claim_id": claim.claim_id,
            "session_id": claim.session_id,
            "carrier": claim.carrier,
            "superdocs_response": response,
        }

    except Exception as error:
        import traceback

        print(
            "\n========== FREIGHT CLAIM PACKET ERROR =========="
        )
        print("ERROR:", repr(error))
        traceback.print_exc()
        print(
            "=================================================\n"
        )

        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

# ---------------------------------------------------------
# 4. Chaser — edit existing packet
# ---------------------------------------------------------

class ChaserRequest(BaseModel):
    session_id: str
    carrier: str
    follow_up_date: str


@router.post("/chaser")
async def generate_chaser(
    data: ChaserRequest,
):
    claim = await get_claim_by_session(
        data.session_id
    )

    prompt = f"""
Edit the EXISTING freight claim packet in this
SuperDocs session to create a follow-up chaser
for {data.carrier}.

Follow-up date:
{data.follow_up_date}

This MUST be a targeted edit of the existing
claim packet.

DO NOT create a fresh unrelated claim letter.

Preserve EXACTLY:

- shipment/reference numbers
- the claim amount currently stated in the existing claim packet
- original evidence
- original delivery exception
- original damage description
- existing claim facts

IMPORTANT:
Do NOT derive the claim amount from the commercial invoice.

Do NOT replace the existing claim amount with the
invoice amount.

The follow-up must preserve the exact monetary amount
already stated in the existing claim packet.

Only change what is necessary for the follow-up:

- follow-up date
- wording/tone appropriate for a chaser
- request for an update

Do NOT invent:

- carrier response
- payment
- approval
- denial
- claim status
- new amounts
- new dates
- new facts

The result should remain part of the existing
claim packet.
"""

    try:
        response = await superdocs_client.chat(
            session_id=data.session_id,
            message=prompt,
            approval_mode="ask_every_time",
        )

        parsed = parse_superdocs_response(response)

        document_changes = (
            parsed.get("document_changes")
            or {}
        )

        claim.status = "chaser_generated"

        claim.chaser_response = parsed

        claim.job_id = (
            parsed.get("job_id")
            or claim.job_id
        )

        claim.pending_changes = (
            document_changes.get("pending_changes")
            or parsed.get("pending_changes")
            or []
        )

        return {
            "status": "chaser_generated",
            "claim_id": claim.claim_id,
            "session_id": claim.session_id,
            "carrier": claim.carrier,
            "follow_up_date": data.follow_up_date,
            "superdocs_response": response,
        }

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


# ---------------------------------------------------------
# 5. Approve a claim change
# ---------------------------------------------------------

class ClaimApprovalRequest(BaseModel):
    session_id: str
    job_id: str
    change_id: str
    approved: bool
    feedback: str | None = None


# @router.post("/approve")
# async def approve_claim(
#     data: ClaimApprovalRequest,
# ):
#     claim = await get_claim_by_session(
#         data.session_id
#     )

#     try:
#         result = await superdocs_client.approve_change(
#             session_id=data.session_id,
#             job_id=data.job_id,
#             change_id=data.change_id,
#             approved=data.approved,
#             feedback=data.feedback,
#         )

#         if data.approved:
#             claim.status = "approved"
#         else:
#             claim.status = "rejected"

#         return {
#             "status": "approval_processed",
#             "claim_id": claim.claim_id,
#             "result": result,
#         }

#     except Exception as error:
#         raise HTTPException(
#             status_code=502,
#             detail=str(error),
#         )


# ---------------------------------------------------------
# 6. Claim status
# ---------------------------------------------------------

@router.get("/{claim_id}/status")
async def get_claim_status(
    claim_id: str,
):
    claim = await freight_claim_service.get_claim(
        claim_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim not found.",
        )

    return {
        "claim_id": claim.claim_id,
        "session_id": claim.session_id,
        "carrier": claim.carrier,
        "status": claim.status,
        "job_id": claim.job_id,
        "pending_changes": claim.pending_changes,
    }


# ---------------------------------------------------------
# 7. Update claim status
# ---------------------------------------------------------

class ClaimStatusUpdate(BaseModel):
    status: str


@router.patch("/{claim_id}/status")
async def update_claim_status(
    claim_id: str,
    data: ClaimStatusUpdate,
):
    claim = await freight_claim_service.get_claim(
        claim_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim not found.",
        )

    claim.status = data.status

    return {
        "claim_id": claim.claim_id,
        "status": claim.status,
    }


# ---------------------------------------------------------
# 8. Get complete claim
# ---------------------------------------------------------

@router.get("/{claim_id}")
async def get_freight_claim(
    claim_id: str,
):
    claim = await freight_claim_service.get_claim(
        claim_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim not found.",
        )

    return claim

from fastapi.responses import Response


class ClaimExportRequest(BaseModel):
    session_id: str
    format: str = "pdf"


@router.post("/{claim_id}/export")
async def export_freight_claim(
    claim_id: str,
    data: ClaimExportRequest,
):
    claim = await freight_claim_service.get_claim(
        claim_id
    )

    if not claim:
        raise HTTPException(
            status_code=404,
            detail="Freight claim not found.",
        )

    if claim.session_id != data.session_id:
        raise HTTPException(
            status_code=400,
            detail="Session does not belong to this freight claim.",
        )

    allowed_formats = {
        "pdf",
        "docx",
    }

    export_format = data.format.lower()

    if export_format not in allowed_formats:
        raise HTTPException(
            status_code=400,
            detail="Export format must be pdf or docx.",
        )

    try:
        result = await superdocs_client.export_document(
            session_id=claim.session_id,
            export_format=export_format,
        )

        claim.status = "exported"

        if export_format == "pdf":
            default_content_type = "application/pdf"
        else:
            default_content_type = (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            )

        return Response(
            content=result["content"],
            media_type=(
                result.get("content_type")
                or default_content_type
            ),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="'
                    f'freight-claim-{claim.claim_id}.'
                    f'{export_format}"'
                )
            },
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )