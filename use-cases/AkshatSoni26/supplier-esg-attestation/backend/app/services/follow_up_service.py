import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import AttestationCycleModel, AssessmentModel, FindingModel, SupplierModel, FollowUpLetterModel
from app.schemas.enums import LetterStatus, ReviewDecision, FindingSeverity
from app.schemas.followup import FollowUpLetterCreate, FollowUpLetterResponse
from app.services.superdocs_service import SuperDocsClientService
from app.helpers.template_renderer import TemplateRenderer


class FollowUpService:
    """Service to generate targeted deficiency follow-up letters directly quoting supplier responses."""

    def __init__(self, db: AsyncSession, superdocs_client: SuperDocsClientService | None = None):
        self.db = db
        self.superdocs = superdocs_client or SuperDocsClientService()

    async def generate_follow_up_letter(self, request: FollowUpLetterCreate) -> FollowUpLetterResponse:
        # Load attestation
        stmt = (
            select(AttestationCycleModel)
            .where(AttestationCycleModel.id == request.attestation_id)
        )
        res = await self.db.execute(stmt)
        attestation = res.scalar_one_or_none()
        if not attestation:
            raise ValueError(f"Attestation {request.attestation_id} not found.")

        # Load supplier
        sup_stmt = select(SupplierModel).where(SupplierModel.id == attestation.supplier_id)
        sup_res = await self.db.execute(sup_stmt)
        supplier = sup_res.scalar_one_or_none()
        if not supplier:
            raise ValueError(f"Supplier not found for attestation {request.attestation_id}.")

        # Load assessment & findings
        ass_stmt = select(AssessmentModel).where(AssessmentModel.attestation_id == attestation.id)
        ass_res = await self.db.execute(ass_stmt)
        assessment = ass_res.scalar_one_or_none()
        if not assessment:
            raise ValueError(f"No assessment found for attestation {request.attestation_id}.")

        find_stmt = (
            select(FindingModel)
            .where(FindingModel.assessment_id == assessment.id)
            .where(FindingModel.review_decision != ReviewDecision.REJECTED.value)
        )
        find_res = await self.db.execute(find_stmt)
        findings = list(find_res.scalars().all())

        if not findings:
            raise ValueError("No actionable compliance findings exist for this supplier.")

        deadline_date = (datetime.now(timezone.utc) + timedelta(days=request.custom_remediation_deadline_days)).strftime("%B %d, %Y")
        today_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

        letter_content = TemplateRenderer.render(
            "deficiency_letter.md.j2",
            today_date=today_date,
            supplier=supplier,
            attestation=attestation,
            findings=findings,
            custom_remediation_deadline_days=request.custom_remediation_deadline_days,
            deadline_date=deadline_date,
        )

        # Upload and Export via SuperDocs
        doc_filename = f"ESG_Remediation_Notice_{supplier.code}_{attestation.cycle_year}.md"
        sd_upload = await self.superdocs.upload_document(doc_filename, letter_content)
        sd_export = await self.superdocs.export_document(sd_upload.document_id, format_type="pdf")

        # Save Follow-Up Letter in DB
        letter = FollowUpLetterModel(
            id=str(uuid.uuid4()),
            attestation_id=attestation.id,
            recipient_email=supplier.primary_contact_email,
            subject=f"[ACTION REQUIRED] ESG Attestation Remediation Notice - {supplier.name} ({supplier.code})",
            content_markdown=letter_content,
            superdocs_doc_id=sd_upload.document_id,
            superdocs_export_url=sd_export.download_url,
            status=LetterStatus.DRAFT.value
        )
        self.db.add(letter)
        await self.db.commit()
        await self.db.refresh(letter)

        return FollowUpLetterResponse(
            id=letter.id,
            attestation_id=attestation.id,
            recipient_email=letter.recipient_email,
            subject=letter.subject,
            content_markdown=letter.content_markdown,
            superdocs_doc_id=letter.superdocs_doc_id,
            superdocs_export_url=letter.superdocs_export_url,
            status=LetterStatus(letter.status),
            created_at=letter.created_at,
            updated_at=letter.updated_at
        )
