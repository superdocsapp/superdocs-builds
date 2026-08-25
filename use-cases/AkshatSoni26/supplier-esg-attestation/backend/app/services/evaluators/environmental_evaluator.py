import re
import uuid
from typing import List, Tuple
from app.helpers.text_extractor import extract_verbatim_quote
from app.schemas.assessment import EnvironmentalMetrics, FindingSchema
from app.schemas.enums import ESGPillar, FindingSeverity, SupplierTier


class EnvironmentalEvaluator:
    """Evaluates environmental disclosures against GHG protocols and ISO standards."""

    @staticmethod
    def evaluate(raw_text: str, tier: str) -> Tuple[EnvironmentalMetrics, List[FindingSchema]]:
        lower_text = raw_text.lower()
        findings: List[FindingSchema] = []
        env = EnvironmentalMetrics()

        # Scope 1 emissions
        if "scope 1" in lower_text:
            env.ghg_scope_1_reported = True
            m1 = re.search(r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:mt|metric tons?)\s*co2e", lower_text)
            if m1:
                env.ghg_scope_1_mt_co2e = float(m1.group(1).replace(",", ""))

        # Scope 2 emissions
        if "scope 2" in lower_text and ("not track" not in lower_text and "do not measure" not in lower_text):
            env.ghg_scope_2_reported = True
            m2 = re.search(r"scope 2.*?(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:mt|metric tons?)\s*co2e", lower_text)
            if m2:
                env.ghg_scope_2_mt_co2e = float(m2.group(1).replace(",", ""))

        # Scope 3 tracking
        if "scope 3" in lower_text and ("measured" in lower_text or "tracked" in lower_text or "yes" in lower_text):
            env.ghg_scope_3_tracked = True

        # ISO 14001 certification
        if "iso 14001" in lower_text and ("certified" in lower_text or "valid" in lower_text or "yes" in lower_text) and "not yet" not in lower_text:
            env.iso_14001_certified = True

        # Renewable energy percentage
        ren_match = re.search(r"(\d+)%\s*(?:renewable|clean\s*energy|solar|wind)", lower_text)
        if ren_match:
            env.renewable_energy_percentage = float(ren_match.group(1))

        # Gap Finding: Scope 2 missing for Tier 1 Strategic
        if tier == SupplierTier.TIER_1_STRATEGIC.value and not env.ghg_scope_2_reported:
            quote = extract_verbatim_quote(
                raw_text,
                ["scope 2", "indirect emissions", "electricity emissions", "do not measure"],
                "We currently do not track Scope 2 indirect emissions from electricity consumption."
            )
            findings.append(FindingSchema(
                id=str(uuid.uuid4()),
                pillar=ESGPillar.ENVIRONMENTAL,
                severity=FindingSeverity.HIGH,
                standard_clause="Clause E1.1: Mandatory Annual Scope 1 & 2 GHG Disclosures",
                shortfall_summary="Supplier failed to calculate or verify Scope 2 greenhouse gas emissions.",
                supplier_exact_quote=quote,
                source_location="Environmental Section / Emissions Log",
                recommended_action="Execute Scope 2 inventory based on utility electricity bills and submit third-party audit within 30 days."
            ))

        # Gap Finding: ISO 14001 missing for Tier 1 Strategic
        if tier == SupplierTier.TIER_1_STRATEGIC.value and not env.iso_14001_certified:
            quote = extract_verbatim_quote(
                raw_text,
                ["iso 14001", "ems", "environmental management"],
                "ISO 14001 certification has not yet been audited for the current fiscal year."
            )
            findings.append(FindingSchema(
                id=str(uuid.uuid4()),
                pillar=ESGPillar.ENVIRONMENTAL,
                severity=FindingSeverity.MEDIUM,
                standard_clause="Clause E1.4: Certified Environmental Management System (ISO 14001)",
                shortfall_summary="Lack of active ISO 14001 EMS certification for primary manufacturing operations.",
                supplier_exact_quote=quote,
                source_location="Environmental Certifications Section",
                recommended_action="Provide EMS roadmap and target date for ISO 14001 audit completion."
            ))

        return env, findings
