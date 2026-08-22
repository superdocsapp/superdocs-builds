import os
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.db.models import SupplierModel, AttestationCycleModel
from app.schemas.enums import SupplierTier, Region, AttestationStatus
from app.schemas.questionnaire import QuestionnaireIssuanceRequest, QuestionnaireIssuanceResponse
from app.services.superdocs_service import SuperDocsClientService
from app.helpers.template_renderer import TemplateRenderer


class IssuanceService:
    """Service responsible for generating and issuing customized supplier attestation packages."""

    def __init__(self, db: AsyncSession, superdocs_client: SuperDocsClientService | None = None):
        self.db = db
        self.superdocs = superdocs_client or SuperDocsClientService()

    def _read_template(self, filename: str) -> str:
        filepath = os.path.join(settings.TEMPLATES_DIR, filename)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return f"# Template {filename} not found."

    async def issue_questionnaire(self, request: QuestionnaireIssuanceRequest) -> QuestionnaireIssuanceResponse:
        # Fetch supplier
        stmt = select(SupplierModel).where(SupplierModel.id == request.supplier_id)
        res = await self.db.execute(stmt)
        supplier = res.scalar_one_or_none()
        if not supplier:
            raise ValueError(f"Supplier {request.supplier_id} not found.")

        # 1. Base Code of Conduct
        base_coc = self._read_template("code_of_conduct_base.md")

        # 2. Tier Questionnaire
        tier_map = {
            SupplierTier.TIER_1_STRATEGIC.value: "tier1_questionnaire.md",
            SupplierTier.TIER_2_MANUFACTURING.value: "tier2_questionnaire.md",
            SupplierTier.TIER_3_COMMODITY.value: "tier3_questionnaire.md",
        }
        tier_filename = tier_map.get(supplier.tier, "tier3_questionnaire.md")
        tier_content = self._read_template(tier_filename)

        # 3. Regional Annex
        annex_map = {
            Region.EU.value: ("EU CSRD/CSDDD/REACH Addendum", "annex_eu_csrd.md"),
            Region.NORTH_AMERICA.value: ("US UFLPA & Trade Compliance Addendum", "annex_us_uflpa.md"),
            Region.APAC.value: ("APAC Labor & Environmental Standards Addendum", "annex_apac_labor.md"),
        }
        annex_info = annex_map.get(supplier.region, ("Global Standard Addendum", "annex_eu_csrd.md"))
        regional_content = self._read_template(annex_info[1])

        # Compile complete customized document via Jinja2 template
        full_document_markdown = TemplateRenderer.render(
            "attestation_package.md.j2",
            cycle_year=request.cycle_year,
            supplier=supplier,
            issuance_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            base_coc=base_coc,
            tier_content=tier_content,
            regional_content=regional_content,
        )

        # Upload document to SuperDocs
        doc_filename = f"ESG_Attestation_{supplier.code}_{request.cycle_year}.md"
        sd_upload = await self.superdocs.upload_document(doc_filename, full_document_markdown)
        sd_export = await self.superdocs.export_document(sd_upload.document_id, format_type="pdf")

        # Create or update attestation cycle in DB
        cycle_stmt = select(AttestationCycleModel).where(
            AttestationCycleModel.supplier_id == supplier.id,
            AttestationCycleModel.cycle_year == request.cycle_year
        )
        cycle_res = await self.db.execute(cycle_stmt)
        attestation = cycle_res.scalar_one_or_none()

        if not attestation:
            attestation = AttestationCycleModel(
                id=str(uuid.uuid4()),
                supplier_id=supplier.id,
                cycle_year=request.cycle_year,
                status=AttestationStatus.ISSUED.value,
                issued_document_id=sd_upload.document_id,
                issued_document_url=sd_export.download_url
            )
            self.db.add(attestation)
        else:
            attestation.status = AttestationStatus.ISSUED.value
            attestation.issued_document_id = sd_upload.document_id
            attestation.issued_document_url = sd_export.download_url

        await self.db.commit()
        await self.db.refresh(attestation)

        return QuestionnaireIssuanceResponse(
            attestation_id=attestation.id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            tier=SupplierTier(supplier.tier),
            region=Region(supplier.region),
            cycle_year=request.cycle_year,
            status=AttestationStatus.ISSUED,
            document_title=f"ESG Attestation - {supplier.name}",
            document_content_markdown=full_document_markdown,
            included_annexes=[tier_filename.replace(".md", ""), annex_info[0]],
            superdocs_document_id=sd_upload.document_id,
            export_url=sd_export.download_url,
            issued_at=datetime.now(timezone.utc)
        )
